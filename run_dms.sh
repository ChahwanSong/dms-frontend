#!/bin/bash

set -eux pipefail;\
    export DMS_SCHEDULER_BASE_URL="http://127.0.0.1:9000";\
    python -m cli.main serve --host 0.0.0.0 --port 8000
