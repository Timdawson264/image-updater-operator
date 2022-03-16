# Why
This operator is a super simple way to automatically keep deployments up to date with software releases. this is intended to be a watchtower replacement for kubernetes.

The goal is to eventually have an annotation to link a deployment to a `Imagebuilder` CRD (from the simple-image-builder operator)  to allow new builds to trigger image updates. This will efectivly allow for a primative replacement of `imagestreams` without the massive ammount of integration normally required.

## Annotations
An example to check regsitery every two hours, for new image version

```
image-updater.k8s.tdawson.co.nz/enable: "true"
image-updater.k8s.tdawson.co.nz/period: "3600"
```


This annotations is set by operator when first run  red_name is from the image propertie of each container this must not be a short name!
This can also be set by the user to hardcode which image version is used to keep update to date.

```
image-updater.k8s.tdawson.co.nz/watch-ref: {
     "Container-Name": "ref_name", 
     "Container2-name": "ref_name" 
    }
```

### TODO:

- Add helm chart to deploy, with service account + role bindings
- replace `sched.scheduler` with a custom implimentation that allows easier removal by key, and also adding a new earlier class while waiting for next.
- implement removing class from scheduler on delete/removal or disalbe of annotation.
- add support for daemonset
- rewrite the maze..... of functions
- add support from namespacing this controller to manage a single namespace.