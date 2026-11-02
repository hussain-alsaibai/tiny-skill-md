---
name: deploy-service
description: Deploy a service to staging and verify the health endpoint responds.
version: 0.1.0
author: OpenClaw <hussain.alsaibai@gmail.com>
license: MIT
triggers:
  - deploy
  - release
tags:
  - devops
---

# Deploy Service

Push the current build to the staging cluster, then confirm the service
is healthy before announcing it.

## Steps

1. Build the image and tag it with the current commit SHA.
2. Apply the deployment manifest to the staging namespace.
3. Wait for the rollout to report ready.

## Verify

Check the health endpoint returns 200 and the version in the response
matches the commit SHA that was deployed. If it does not, roll back.
