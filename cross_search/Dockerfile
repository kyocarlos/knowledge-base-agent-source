FROM python:3.12-slim
WORKDIR /app
COPY cross_search/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY km_credentials /app/km_credentials
COPY cross_search /app/cross_search
ENV PYTHONPATH=/app
CMD ["uvicorn", "cross_search.service:app", "--host", "0.0.0.0", "--port", "8000"]
