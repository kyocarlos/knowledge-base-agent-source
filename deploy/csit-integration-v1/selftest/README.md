# CSIT worker self-test (OCR / vision / Excel semantic extraction)

Runs the real v2 ingestion pipeline on local test files, without touching any CSIT job. Chunks go to a throw-away Qdrant collection that is dropped at the end.

1. `python3 make_test_files.py` on a host with Noto Sans CJK and Pillow/openpyxl (writes /tmp/km_selftest/*).
2. `docker cp` the three files into the worker container's /tmp.
3. `docker exec -i -w /app km-csit-v1-dev-worker-1 python - < km_selftest_pipeline.py`

Expected (2026-11-20, worker km-csit-worker:9d5805d-ocr-20261120, model gpt-5.6-luna): zh PNG -> method OCR; diagram PNG -> Visual; equipment xlsx -> Text; each Completed with 1 Qdrant point.
Worker images need Tesseract (tesseract-ocr, -chi-tra, -eng): deploy/csit-integration-v1/Dockerfile.worker-ocr adds it to an existing worker image.
