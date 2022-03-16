#!/usr/bin/python3

from kubernetes import client, config, watch
from kubernetes.leaderelection import leaderelection
from kubernetes.leaderelection.resourcelock.configmaplock import ConfigMapLock
from kubernetes.leaderelection import electionconfig

from docker_registry_client import DockerRegistryClient
import logging
from pprint import pprint
from urllib.parse import urlparse
import sys
import subprocess
import json
import uuid
import sched
import time
import threading

OP_NAME = "image-updater-operator"
DEFAULT_PERIOD = int( 3600 )
annotation_enable = 'image-updater.k8s.tdawson.co.nz/enable'
annotations_wref = 'image-updater.k8s.tdawson.co.nz/watch-ref'
annotations_status = 'image-updater.k8s.tdawson.co.nz/status'
annotations_period = 'image-updater.k8s.tdawson.co.nz/period'

scheduler = sched.scheduler(time.time, time.sleep)

#key is gen_key output - used to find entry in schedular
#watched_resources = dict()

def gen_key( input ):
        return  "key_" + input.kind + "_"+ input.metadata.namespace + "_" + input.metadata.name

#Terrible O(N) lookup.
def find_in_sched( obj ):
    key = gen_key( obj )
    evt = list( filter(lambda d: "key" in d.kwargs and d.kwargs["key"] == key, scheduler.queue) )
    if len( evt ) > 0:
        return evt[0]
    else:
        return None

#Another Terrible O(N) remove func
def remove_from_sched( obj ):
    evt = find_in_sched( obj )
    if evt:
        print( "REMOVED Schedualed evt" )
        pprint(evt)
        scheduler.cancel(evt)

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
                logger.error(f"Container {cont.name} in deployment {input.metadata.name} already using sha256 image-ref, You may need to manually set the watch-ref annotation")
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

def set_update_status_annotation( client, deploy ):
    deploy_name = deploy.metadata.name
    deploy_ns = deploy.metadata.namespace

    status = { 
        "last-checked": int(time.time()) 
    }
    status_json = json.dumps(status)

    patch = {
        "metadata": { 
            "annotations": { 
                    annotations_status: status_json 
                } 
            }
        }
        
    #TODO: wrap in try execpt
    print( "Updating Last-Checked" )
    resp = client.AppsV1Api().patch_namespaced_deployment( 
            deploy_name, 
            deploy_ns, 
            patch,
            pretty=True, 
            field_manager=OP_NAME, 
            field_validation="Strict"
        )

def get_status_annotation( deploy ):
    raw_annotation = deploy.metadata.annotations[ annotations_status ]
    return json.loads( raw_annotation  )

def get_check_period( deploy ):
    if annotations_period in deploy.metadata.annotations:
        return int( deploy.metadata.annotations[ annotations_period ] )
    else:
        return DEFAULT_PERIOD

def get_last_check( deploy ):

    if annotations_status in deploy.metadata.annotations:
        raw_annotation = deploy.metadata.annotations[ annotations_status ] 
        #pprint( raw_annotation )
        j = json.loads( raw_annotation  )
        last = int( j[ "last-checked" ] )
        return last
    
    return 0

def get_and_reconsile( **args ):

    print( f"Scheduled update ts: {time.time()} {args}")

    if args["kind"] == "Deployment":
        #TODO: Catch exections from removed objeccts
        obj = client.AppsV1Api().read_namespaced_deployment( args["name"], args["namespace"] )
        if annotation_enable in obj.metadata.annotations and obj.metadata.annotations[annotation_enable].lower() == "true":
            set_update_status_annotation( client, obj )
            check_image_update( client, obj )
            period = get_check_period( obj )

            args = { 
                "kind": obj.kind,
                "namespace": obj.metadata.namespace,
                "name": obj.metadata.name,
                "key": gen_key( obj )
            }

            scheduler.enter( period , 5, get_and_reconsile, (), kwargs=args )

    
def reconsile_add(obj):
    #this has no side effects
    set_watch_ref_annotation( client, obj )

    last = get_last_check( obj )
    now = int(time.time())
    period = get_check_period( obj )
    print( f"time until update: { period - (now-last) }" ) 

    if (now - last) >  period:
        #update status, aka last check time first, this means that any following update events contain the new time.
        set_update_status_annotation( client, obj )
        check_image_update( client, obj )
    else:
        period = period - (now-last)

    args = { 
        "kind": obj.kind,
        "namespace": obj.metadata.namespace,
        "name": obj.metadata.name,
        "key": gen_key( obj )
    }


    scheduler.enter( period , 5, get_and_reconsile, (), args )

def annotation_enable_chk(d):
    return annotation_enable in d.metadata.annotations and d.metadata.annotations[annotation_enable].lower() == "true"

#when we add more watches https://engineering.bitnami.com/articles/kubernetes-async-watches.html
def start_controller():
    api_client = client.AppsV1Api()

    w = watch.Watch()
    for event in w.stream(api_client.list_deployment_for_all_namespaces):
        print("Event: %s %s %s" % (event['type'], event['object'].kind, event['object'].metadata.name))
        #pprint( event )
        d = event['object']
        key = gen_key( event['object'] )

        if annotation_enable_chk(d) and event['type'] == "ADDED":
            reconsile_add( d )

        #Check if the Annotation was removed, attempt to remove from sched if not enabled.
        if not annotation_enable_chk(d) and event['type'] == "MODIFIED":
            remove_from_sched( d )

        if event['type'] == "DELETED":
            remove_from_sched( d )

    sys.exit("Watch failed")


def stop_controller():
    logger.warn("No longer the leader")
    sys.exit(1)

def main():
    #TODO: add some arg parseing 
    # --global = check all namespace
    # --namespace = check only this namespace - also we should be running in this names - leader election...
    # --in-cluster = use svc account and in cluster env config.

    #Use Service Account
    #config.load_incluster_config()
    config.load_config()

    #Leader election
    # candidate_id = uuid.uuid4()
    # lock_namespace = "image-updater-operator" #TODO: fix this - maybe arg/maybe api call (configmap/current svc acount ns)
    # lock_name = "image-updater-operator-leader" #Could also be from a configmap/arg

    # leader = electionconfig.Config(ConfigMapLock(lock_name, lock_namespace, candidate_id), lease_duration=17,
    #                            renew_deadline=11, retry_period=5, onstarted_leading=start_controller,
    #                            onstopped_leading=stop_controller)

    # leaderelection.LeaderElection(leader).run()

    #HACK: This task just readds its self to the queue to stop the schedular getting empty
    def dummy():
        scheduler.enter( 10, 10, dummy  )
    dummy()

    sched_thread = threading.Thread(target=scheduler.run, daemon=True)
    sched_thread.start()

    start_controller()


if __name__ == '__main__':
    main()