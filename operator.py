#!/usr/bin/python3

from kubernetes import client, config
from docker_registry_client import DockerRegistryClient
import logging
from pprint import pprint
from urllib.parse import urlparse
import sys
import subprocess
import json

OP_NAME = "image-updater-operator"
annotation_enable = 'image-updater.k8s.tdawson.co.nz/enable'
annotations_wref = 'image-updater.k8s.tdawson.co.nz/watch-ref'

#TODO: replace this with a request to the api
def get_ref_digest( image_str ):
    popen = subprocess.Popen(
          ( "./skopeo", "--override-os", "linux", "inspect", "--no-tags", "--no-creds", "docker://"+image_str ),
          stdout=subprocess.PIPE
        )
    popen.wait()
    output = json.loads( popen.stdout.read() )
    
    return (output["Digest"])    

#Returns a dict of all containers: images from the supplied deplyment/daemonset.
#image returned is the desired ref to watch - aka the original refs.
def get_container_watch_refs( input ):
    
    containers = input.spec.template.spec.containers

    #If this is not the first run, so we get the orignal image string
    if annotations_wref in input.metadata.annotations:
        a_images = input.metadata.annotations[annotations_wref]
        return json.loads( a_images )
    else:
        images = dict()
        for cont in containers:
            if  "sha256" in cont.image:
                logger.error(f"Container {cont.name} in deployment {input.metadata.name} already using sha256 image-ref")
                continue
            images[cont.name] = cont.image
        return images

def get_container_images( deploy ):
    containers = deploy.spec.template.spec.containers
    images = dict()
    for cont in containers:
            images[cont.name] = cont.image
    return images

#checks if any images can be updated in a deployment
def check_image_update( client, deploy ):
    deploy_name = deploy.metadata.name
    deploy_ns = deploy.metadata.namespace
    print( f"Checking {deploy_ns}/{deploy_name} for image updates" )

    watch_images = get_container_watch_refs(deploy)
    current_images = get_container_images( deploy )
    new_images = dict()

    for cont,watch_img in watch_images.items():
        #check the current digest for the watch ref
        digest = get_ref_digest( watch_img )
        cur_img = current_images[cont]
        new_img = watch_img.split(":")[0] + "@" + digest
        if new_img != cur_img:
            new_images[ cont ] = new_img
            print( f"Container: {cont} Current Img:{cur_img} Updating to {new_img}" )
    
    if len( new_images ) > 0 :
        cont_imgs = [ { "name": k, "image": v } for (k,v) in new_images.items() ]
        patch = { "spec": { "template" : { "spec": { "containers": cont_imgs }}}}

        #TODO: wrap in try execpt
        resp = client.AppsV1Api().patch_namespaced_deployment( 
                deploy_name, 
                deploy_ns, 
                patch,
                pretty=True, 
                field_manager=OP_NAME, 
                field_validation="Strict"
            )
        #print( resp )


def set_watch_ref_annotation( client, deploy ):
    if annotations_wref in deploy.metadata.annotations:
        return

    cont_images = json.dumps(  get_container_watch_refs( deploy ) )
    deploy_name = deploy.metadata.name
    deploy_ns = deploy.metadata.namespace

    patch = {"metadata":{"annotations":{ annotations_wref : cont_images }}}

    #TODO: wrap in try execpt
    resp = client.AppsV1Api().patch_namespaced_deployment( 
            deploy_name, 
            deploy_ns, 
            patch,
            pretty=True, 
            field_manager=OP_NAME, 
            field_validation="Strict"
        )
        

def main():
    #Use Service Account
    #config.load_incluster_config()
    config.load_config()

    #TODO: add a leader election

    deployments = client.AppsV1Api().list_deployment_for_all_namespaces(
        async_req=False
    )

    #Select only deployments that are annotated with enabled=true
    filter_func =  lambda d: annotation_enable in d.metadata.annotations and d.metadata.annotations[annotation_enable].lower() == "true"
    deployments_enabled = filter( filter_func , deployments.items )

    for deploy in deployments_enabled:
        set_watch_ref_annotation( client, deploy )
        check_image_update( client, deploy )
        

if __name__ == '__main__':
    main()