#!/bin/bash

set -eux pipefail;\
    export DMS_REDIS_WRITE_URL="redis://127.0.0.1:6379";\
    export DMS_REDIS_READ_URL="redis://127.0.0.1:6379";\
    export DMS_SCHEDULER_BASE_URL="http://127.0.0.1:9000";\
    dms-frontend serve --host 0.0.0.0 --port 8000
