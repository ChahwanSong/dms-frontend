#!/bin/bash

set -eux pipefail;\
    python3 -m uvicorn cli.local_scheduler:app --host 0.0.0.0 --port 9000


