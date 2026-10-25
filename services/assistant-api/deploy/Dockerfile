# Build from the repo root:
#   docker build -f services/assistant-api/deploy/Dockerfile --build-arg APP_VERSION=0.1.0 -t assistant-api:0.1.0 .
# The image keeps the repo layout the backend expects (packages/, data/corpus, eval/users.json).
# Public FDA PDFs are not baked in; mount them at /app/data/raw/public to add them to the knowledge base.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    ASSISTANT_ROOT=/app ASSISTANT_DATA_DIR=/data
WORKDIR /app

COPY services/assistant-api/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt
COPY packages/rag packages/rag
COPY packages/erpqms packages/erpqms
COPY packages/tools packages/tools
COPY data/corpus data/corpus
COPY eval/users.json eval/users.json
COPY services/assistant-api/assistant_api services/assistant-api/assistant_api

ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION}
RUN useradd --uid 10001 --create-home app && mkdir /data && chown 10001 /data
USER 10001
WORKDIR /app/services/assistant-api
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthz')"
CMD ["uvicorn", "assistant_api.main:app", "--host", "0.0.0.0", "--port", "8080"]
