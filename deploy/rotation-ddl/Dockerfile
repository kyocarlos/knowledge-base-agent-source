ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY src/ui_upload_tracking.py /app/src/ui_upload_tracking.py
ARG SOURCE_COMMIT
LABEL org.opencontainers.image.revision=${SOURCE_COMMIT}
