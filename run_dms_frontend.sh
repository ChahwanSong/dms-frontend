#!/bin/bash

# master node (ion2410) 에서 실행


kubectl run frontend-test \
  --rm -it \
  --restart=Never \
  --image=rts2411:5000/dms-dsync:latest \
  --overrides='
{
  "apiVersion": "v1",
  "spec": {
    "terminationGracePeriodSeconds": 3,
    "dnsPolicy": "ClusterFirstWithHostNet",
    "nodeSelector": {
      "kubernetes.io/hostname": "ion2407"
    },
    "volumes": [
      {
        "name": "hostdir",
        "hostPath": {
          "path": "/home/gpu1/cocoa.song/workspace/dms",
          "type": "Directory"
        }
      }
    ],
    "containers": [
      {
        "name": "frontend-test",
        "image": "rts2411:5000/dms-dsync:latest",
        "stdin": true,
        "tty": true,
        "command": [
          "sh",
          "-c",
          "printf \"[global]\\ntrusted-host = 202.20.187.241\\nfind-links = http://202.20.187.241/pypi/simple/\\nindex-url = http://202.20.187.241:9001/artifactory/api/pypi-remote/simple/\\n\" > /etc/pip.conf && exec bash"
        ],
        "volumeMounts": [
          {
            "name": "hostdir",
            "mountPath": "/dms"
          }
        ]
      }
    ]
  }
}'

kubectl expose pod frontend-test \
  --name=frontend-test-svc \
  --port=8000 \
  --target-port=8000 \
  --type=ClusterIP

pip install -e .[dev] --no-build-isolation

set -eux pipefail;\
    export DMS_SCHEDULER_BASE_URL="http://0.0.0.0:9000";\
    cd /dms/dms-frontend; python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000




