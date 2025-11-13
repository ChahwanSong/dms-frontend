# DMS Frontend

FastAPI based frontend for the Distributed Management Service (DMS). The service exposes APIs for end users and operators to submit jobs, query status and logs, and manage lifecycle events before forwarding jobs to the `dms_scheduler` microservice.

## Features

- Asynchronous FastAPI application with background event processor
- Redis backed task registry with optional in-memory mode for development/testing
- Scheduler integration using HTTP-based dispatcher
- Operator authenticated endpoints secured by `X-Operator-Token`
- CLI entrypoint (`dms-frontend serve`) for running the API server
- JSON logging tailored for Kubernetes environments

## Development

Install dependencies (preferably within a virtual environment) and run tests:

```bash
pip install -e .[dev]
pytest
```

To run the service locally with the default configuration:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Configuration is driven via environment variables prefixed with `DMS_`. See `app/core/config.py` for the complete list.
