"""Load test for an OpenAI-compatible inference server: latency under concurrent users.

For each concurrency level, `--requests` streaming chat requests are sent with that many in flight.
Per request: TTFT (time to the first streamed token) and TPOT (mean time per output token after
the first). Per level: p50 and p99 of both, output tokens per second across the level, errors.
Prompts are fixed (an agent-sized prompt of about 2,000 tokens and a short one), the output length
is capped, and the temperature is 0, so engines see the same work.

Each level is saved as soon as it finishes; rerunning skips finished levels. Run it only when the
machine is otherwise idle: the numbers include whatever else is using the GPU.

    python eval/load/run_load.py --engine llama.cpp --model qwen3.8-27b-q8 --base-url http://127.0.0.1:8000/v1
    python eval/load/run_load.py --engine vllm --model qwen3-8b --base-url http://127.0.0.1:8100/v1 --levels 1 2 4 8
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = (ROOT / "packages/erpqms/erpqms/schema.sql").read_text(encoding="utf-8")
PROMPTS = [
    ("long", [{"role": "system", "content": "Answer with one SQLite query.\n" + SCHEMA},
              {"role": "user", "content": "各區域各有幾家站點？"}]),
    ("short", [{"role": "user", "content": "用一句話說明 CAPA 是什麼。"}]),
]


def pct(values, q):
    if not values:
        return None
    values = sorted(values)
    return round(values[min(len(values) - 1, int(q * len(values)))], 3)


async def one(client, model, messages, max_tokens, extra):
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0, "stream": True,
            "stream_options": {"include_usage": True}, **extra}
    t0 = time.perf_counter()
    first = None
    tokens = 0
    async with client.stream("POST", "/chat/completions", json=body) as r:
        r.raise_for_status()
        async for line in r.aiter_lines():
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            data = json.loads(line[6:])
            if data.get("usage"):
                tokens = data["usage"].get("completion_tokens", tokens)
            for ch in data.get("choices", []):
                delta = ch.get("delta", {})
                if (delta.get("content") or delta.get("reasoning_content")) and first is None:
                    first = time.perf_counter()
    end = time.perf_counter()
    ttft = (first or end) - t0
    tpot = (end - first) / (tokens - 1) if first and tokens > 1 else None
    return {"ttft": ttft, "tpot": tpot, "tokens": tokens, "seconds": end - t0}


async def level(base_url, model, concurrency, n, max_tokens, extra, timeout):
    sem = asyncio.Semaphore(concurrency)
    results, errors = [], []
    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout) as client:
        async def task(i):
            name, msgs = PROMPTS[i % len(PROMPTS)]
            async with sem:
                try:
                    res = await one(client, model, msgs, max_tokens, extra)
                    results.append({"prompt": name, **res})
                except (httpx.HTTPError, json.JSONDecodeError) as e:
                    errors.append(f"{type(e).__name__}: {e}"[:200])
        t0 = time.perf_counter()
        await asyncio.gather(*(task(i) for i in range(n)))
        wall = time.perf_counter() - t0
    ttft = [r["ttft"] for r in results]
    tpot = [r["tpot"] for r in results if r["tpot"]]
    return {"concurrency": concurrency, "requests": n, "ok": len(results), "errors": len(errors),
            "error_samples": errors[:3], "wall_s": round(wall, 1),
            "ttft_p50": pct(ttft, 0.5), "ttft_p99": pct(ttft, 0.99),
            "tpot_p50": pct(tpot, 0.5), "tpot_p99": pct(tpot, 0.99),
            "output_tok_per_s": round(sum(r["tokens"] for r in results) / wall, 2) if wall else None,
            "mean_ttft": round(statistics.mean(ttft), 3) if ttft else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True, help="label only, e.g. llama.cpp / vllm / ollama")
    ap.add_argument("--model", required=True)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--levels", type=int, nargs="+", default=[1, 2, 4, 8])
    ap.add_argument("--requests", type=int, default=16, help="requests per level")
    ap.add_argument("--max-tokens", type=int, default=128)
    ap.add_argument("--timeout", type=float, default=900.0)
    ap.add_argument("--no-think", action="store_true")
    ap.add_argument("--out", type=Path, default=ROOT / "results/m3")
    args = ap.parse_args()

    extra = {"chat_template_kwargs": {"enable_thinking": False}} if args.no_think else {}
    path = args.out / f"load-{args.engine}-{args.model.replace(':', '-').replace('/', '-')}.json"
    report = json.loads(path.read_text()) if path.exists() else {
        "engine": args.engine, "model": args.model, "max_tokens": args.max_tokens, "no_think": args.no_think,
        "levels": []}
    done = {lv["concurrency"] for lv in report["levels"] if not lv["errors"]}
    for c in args.levels:
        if c in done:
            continue
        res = asyncio.run(level(args.base_url, args.model, c, args.requests, args.max_tokens, extra, args.timeout))
        report["levels"] = [lv for lv in report["levels"] if lv["concurrency"] != c] + [res]
        report["levels"].sort(key=lambda lv: lv["concurrency"])
        args.out.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(res, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
