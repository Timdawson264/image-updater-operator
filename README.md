## Annotations

//Check regsitery every hour, for new image version

image-updater.k8s.tdawson.co.nz/enable: true
image-updater.k8s.tdawson.co.nz/watch-cron: "0 * * * *"

#Will be set by operator on the first check will be copied from the image: fields.
image-updater.k8s.tdawson.co.nz/watch-ref: { "Container-Name": "ref_name", "Container2-name": "ref_name" }




