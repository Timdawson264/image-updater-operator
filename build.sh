#!/bin/bash

podman build -t "quay.io/tidawson/image-updater" .
podman push "quay.io/tidawson/image-updater"
