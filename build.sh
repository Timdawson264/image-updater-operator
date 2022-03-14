#!/bin/bash

podman build -t "registry.apps.nuc.k3s.tdawson.co.nz/image-updater/operator:latest" .
podman push "registry.apps.nuc.k3s.tdawson.co.nz/image-updater/operator:latest"
