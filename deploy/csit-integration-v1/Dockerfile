FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS api
WORKDIR /app
ARG SOURCE_COMMIT=unknown
LABEL org.opencontainers.image.revision=$SOURCE_COMMIT
COPY deploy/csit-integration-v1/requirements.txt deploy/csit-integration-v1/requirements.lock.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.lock.txt
COPY src /app/src
COPY contracts/csit-km-integration-v1 /app/contracts/csit-km-integration-v1
COPY tests/csit_v1/fixtures/canonical-ingestion-request.json /app/fixtures/canonical-ingestion-request.json
COPY app /app/app
COPY config/csit-integration-v1.numeric-rules.json /app/config/csit-integration-v1.numeric-rules.json
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
CMD ["uvicorn","src.csit_integration_v1.runtime:application","--factory","--host","0.0.0.0","--port","8000","--no-access-log"]

FROM api AS control
CMD ["uvicorn","app.control_main:app","--host","0.0.0.0","--port","8000","--no-access-log"]

FROM api AS test
COPY tests /app/tests
COPY migrations /app/migrations
ENV PYTHONPATH=/app:/app/tests/control_v1
CMD ["python","-m","pytest","-q","tests/csit_v1","tests/control_v1"]

FROM api AS worker
COPY deploy/csit-integration-v1/requirements-worker.txt deploy/csit-integration-v1/requirements-worker.lock.txt /tmp/
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.13.0 && pip install --no-cache-dir -r /tmp/requirements-worker.lock.txt
CMD ["python","-m","src.csit_integration_v1.runtime"]
