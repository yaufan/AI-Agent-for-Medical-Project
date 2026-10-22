"""Serve a cross-encoder reranker behind the /rerank contract that rag.dense.HTTPReranker calls.

Ollama has no rerank endpoint, so this small server fills the gap on the local machine:

    pip install fastapi uvicorn sentence-transformers
    python scripts/rerank_server.py --model BAAI/bge-reranker-v2-m3 --port 8001 [--device cuda]

Request:  POST /rerank {"model": "...", "query": "...", "documents": ["...", ...]}
Response: {"model": "...", "results": [{"index": 0, "relevance_score": 0.93}, ...]}
(the same shape vLLM's /rerank returns, so either server can be used).
"""
from __future__ import annotations

import argparse

from fastapi import FastAPI
from pydantic import BaseModel


class RerankRequest(BaseModel):
    model: str | None = None
    query: str
    documents: list[str]


def create_app(model, model_name: str) -> FastAPI:
    """`model` is anything with predict(list[tuple[str, str]]) -> scores, e.g. a sentence-transformers CrossEncoder."""
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"status": "ok", "model": model_name}

    @app.post("/rerank")
    def rerank(req: RerankRequest):
        scores = model.predict([(req.query, d) for d in req.documents]) if req.documents else []
        results = sorted(({"index": i, "relevance_score": float(s)} for i, s in enumerate(scores)),
                         key=lambda r: -r["relevance_score"])
        return {"model": model_name, "results": results}

    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="BAAI/bge-reranker-v2-m3")
    ap.add_argument("--device", default=None, help="cuda / cpu (default: let sentence-transformers decide)")
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--max-length", type=int, default=1024)
    args = ap.parse_args()

    import uvicorn
    from sentence_transformers import CrossEncoder

    model = CrossEncoder(args.model, device=args.device, max_length=args.max_length)
    uvicorn.run(create_app(model, args.model), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
