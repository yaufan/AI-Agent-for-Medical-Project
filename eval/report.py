"""Render results/m1/*.json into results/m1/summary.md (tables only; the analysis lives in README.md)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TYPES = ["fact", "table", "code", "cross_lingual"]


def main(out_dir: Path = ROOT / "results/m1"):
    results = {p.stem: json.loads(p.read_text()) for p in sorted(out_dir.glob("*.json"))}
    qs = {json.loads(l)["id"]: json.loads(l) for l in open(ROOT / "eval/questions.jsonl", encoding="utf-8")}
    lines = ["# M1 檢索結果（自動產生，請勿手改）", "", "由 `python eval/report.py` 從 `results/m1/*.json` 產生。", ""]
    lines += ["## 可回答的題目（權限模式 pre）", "",
              "| 設定 | 段落數 | Recall@1 | Recall@5 | Recall@10 | MRR | nDCG@10 |", "|---|---|---|---|---|---|---|"]
    for name, r in results.items():
        a = r["acl"]["pre"]["answerable"]
        lines.append(f"| {name} | {r['config']['chunks']} | {a['recall@1']:.3f} | {a['recall@5']:.3f} | "
                     f"{a['recall@10']:.3f} | {a['mrr']:.3f} | {a['ndcg@10']:.3f} |")
    lines += ["", f"題數：{next(iter(results.values()))['acl']['pre']['answerable']['n']}（事實、表格數值、代碼與條號、跨語）", ""]
    lines += ["## 依題型（Recall@10／MRR，權限模式 pre）", "", "| 設定 | " + " | ".join(TYPES) + " | 跨語：無共同詞彙 |",
              "|---" * (len(TYPES) + 2) + "|"]
    for name, r in results.items():
        bt = r["acl"]["pre"]["by_type"]
        cells = [f"{bt[t]['recall@10']:.2f}／{bt[t]['mrr']:.2f}（{bt[t]['n']}）" for t in TYPES]
        runs = [json.loads(l) for l in open(out_dir / "runs" / f"{name}-pre.jsonl", encoding="utf-8")]
        nt = [x for x in runs if x["type"] == "cross_lingual" and qs[x["id"]]["note"].startswith("no terms")]
        cells.append(f"{sum(x['recall@10'] for x in nt) / len(nt):.2f}／{sum(x['mrr'] for x in nt) / len(nt):.2f}（{len(nt)}）")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += ["", "括號內是題數。", "", "## 權限控管", "",
              "| 設定 | 模式 | 出現越權段落的題數 | 越權段落總數 | 越權題中答案段落外洩 | 越權題平均回傳筆數 | 一般題平均回傳筆數 |",
              "|---|---|---|---|---|---|---|"]
    for name, r in results.items():
        for acl in ("pre", "post", "none"):
            s = r["acl"][acl]
            u = s["by_type"]["unauthorized"]
            normal = [s["by_type"][t] for t in TYPES]
            avg = sum(t["mean_returned"] * t["n"] for t in normal) / sum(t["n"] for t in normal)
            lines.append(f"| {name} | {acl} | {s['leaks']['questions_with_leak']} | {s['leaks']['leaked_chunks']} | "
                         f"{u['answer_chunk_leaked']}／{u['n']} | {u['mean_returned']:.1f} | {avg:.2f} |")
    lines += ["", "## 撤銷權限", "", "| 設定 | 使用者 | 撤銷群組 | 撤銷前該群組段落數 | 撤銷後 | 下一次查詢即生效 | 需要重建索引 |",
              "|---|---|---|---|---|---|---|"]
    for name, r in results.items():
        v = r["revocation"]
        lines.append(f"| {name} | {v['user']} | {v['revoked_group']} | {v['chunks_from_group_before']} | "
                     f"{v['chunks_from_group_after']} | {'是' if v['effective_on_next_query'] else '否'} | "
                     f"{'是' if v['reindex_needed'] else '否'} |")
    lines += ["", "## 延遲（毫秒，權限模式 pre，單執行緒 CPU）", "", "| 設定 | 階段 | P50 | P95 |", "|---|---|---|---|"]
    for name, r in results.items():
        for stage, v in r["acl"]["pre"]["latency_ms"].items():
            lines.append(f"| {name} | {stage} | {v['p50']:.3f} | {v['p95']:.3f} |")
    lines += ["", "## 第一名分數中位數（用來觀察能否設定拒答門檻）", "", "| 設定 | 不可回答 | " + " | ".join(TYPES) + " |",
              "|---" * (len(TYPES) + 2) + "|"]
    for name, r in results.items():
        m = r["acl"]["pre"]["top1_score_median"]
        lines.append(f"| {name} | {m['unanswerable']} | " + " | ".join(str(m[t]) for t in TYPES) + " |")
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "results/m1")
