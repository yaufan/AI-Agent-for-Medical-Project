# 建置（在 repo 根目錄執行，因為要一起打包 P1 的 lungnod 套件）：
#   docker build -f services/cad-service/deploy/Dockerfile -t nodule-service:0.1.0 .
# 推論只需要 onnxruntime，不裝 torch，映像小很多。
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY packages/lungnod/pyproject.toml /src/p1/
COPY packages/lungnod/lungnod /src/p1/lungnod
RUN pip install /src/p1

COPY services/cad-service/requirements.txt .
RUN pip install -r requirements.txt
COPY services/cad-service/service ./service

# 不用 root 執行；模型由外部掛載到 /app/models（版本和程式分開管理）
RUN useradd --uid 10001 --create-home app
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"
CMD ["uvicorn", "service.main:app", "--host", "0.0.0.0", "--port", "8000"]
