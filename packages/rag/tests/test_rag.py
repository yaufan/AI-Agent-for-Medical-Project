"""Unit tests for the retrieval package. They use the synthetic Markdown corpus only, so they run
without the public PDFs; checks that need the PDFs are skipped when the files are absent."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/rag"))
from rag import evaluate  # noqa: E402
from rag.acl import GroupStore  # noqa: E402
from rag.bm25 import BM25, tokenize  # noqa: E402
from rag.chunking import Chunk, _split_table, chunk_corpus  # noqa: E402
from rag.dense import DenseIndex, HashingEmbedder  # noqa: E402
from rag.documents import Document, Section, load_corpus, load_markdown, mask_pii  # noqa: E402
from rag.metrics import evidence_sets, norm, score_ranking  # noqa: E402
from rag.retriever import Retriever, rrf  # noqa: E402

CORPUS = ROOT / "data/corpus"
RAW = ROOT / "data/raw/public"
QUESTIONS = [json.loads(line) for line in open(ROOT / "eval/questions.jsonl", encoding="utf-8")]
STORE = GroupStore.from_json(ROOT / "eval/users.json")


@pytest.fixture(scope="module")
def md_docs():
    return [load_markdown(p) for p in sorted(CORPUS.glob("*/*.md"))]


@pytest.fixture(scope="module")
def retriever(md_docs):
    return Retriever(chunk_corpus(md_docs, "structured"))


# ---------- tokenizer and BM25 ----------

def test_tokenize_keeps_identifiers_whole_and_split():
    toks = tokenize("Per 21 CFR §892.2050, see QMS-SOP-007 and model C-320.")
    for t in ["892.2050", "892", "2050", "qms-sop-007", "sop", "007", "c-320", "320"]:
        assert t in toks
    assert "the" not in tokenize("the device")


def test_tokenize_chinese_bigrams():
    assert tokenize("切片厚度") == ["切片", "片厚", "厚度"]
    assert tokenize("片") == ["片"]


def test_bm25_ranks_matching_document_first():
    bm = BM25([tokenize("GPU 停產 替代"), tokenize("客訴 處理 時限"), tokenize("GPU 驅動 版本")])
    s = bm.scores(tokenize("GPU 停產"))
    assert int(np.argmax(s)) == 0 and s[1] == 0


# ---------- fusion ----------

def test_rrf_rewards_agreement():
    fused = dict(rrf([[1, 2, 3], [2, 1, 4]]))
    assert fused[1] == fused[2] > fused[3]
    assert fused[2] == pytest.approx(1 / 61 + 1 / 62)


# ---------- documents and chunking ----------

def test_markdown_front_matter_and_tables(md_docs):
    doc = next(d for d in md_docs if d.doc_id == "QMS-SOP-004")
    assert (doc.group, doc.classification) == ("internal", "internal")
    tables = [s for s in doc.sections if s.is_table]
    assert tables and tables[0].text.startswith("| 嚴重度")
    assert all(s.heading for s in doc.sections)


def test_every_markdown_doc_has_valid_access_metadata(md_docs):
    assert {d.group for d in md_docs} == {"internal", "proj-a", "proj-b"}
    assert all(d.classification == "confidential" for d in md_docs if d.group == "proj-b")


def test_split_table_repeats_header():
    rows = ["| a | b |", "|---|---|"] + [f"| {i} | {'x' * 40} |" for i in range(30)]
    parts = _split_table("\n".join(rows), max_chars=300)
    assert len(parts) > 1
    assert all(p.startswith("| a | b |\n|---|---|") for p in parts)
    data_rows = [row for p in parts for row in p.splitlines()[2:]]
    assert data_rows == rows[2:]  # every data row kept exactly once, in order


def test_structured_chunks_carry_heading_prefix(md_docs):
    chunks = chunk_corpus(md_docs, "structured")
    assert all(c.text.startswith("[") for c in chunks)
    assert {c.group for c in chunks} == {"internal", "proj-a", "proj-b"}


def test_mask_pii():
    text, n = mask_pii("E-mail: someone@example.com Telephone: +1 (484) 555-0123")
    assert "[EMAIL]" in text and "[PHONE]" in text and n == 2
    assert mask_pii("21 CFR 892.2050 and K231157")[1] == 0  # identifiers are not phone numbers


# ---------- access control ----------

def test_pre_filter_never_returns_forbidden_groups(retriever):
    groups = STORE.groups("qa_lin")
    for q in QUESTIONS:
        hits, _ = retriever.search(q["question"], groups, acl="pre")
        assert all(h.chunk.group in groups for h in hits)


def test_no_filter_leaks_and_post_filter_shrinks_results(retriever):
    q = "NoduleAssist 2.0 的切片厚度上限會放寬到多少？"
    groups = STORE.groups("qa_lin")
    leaked, _ = retriever.search(q, groups, acl="none")
    assert any(h.chunk.group == "proj-b" for h in leaked)
    post, _ = retriever.search(q, groups, acl="post")
    pre, _ = retriever.search(q, groups, acl="pre")
    assert all(h.chunk.group in groups for h in post)
    assert len(post) < len(pre)


def test_revocation_takes_effect_on_next_query(retriever):
    result = evaluate.revocation_check(retriever, QUESTIONS, STORE, "ra_huang", "proj-b")
    assert result["chunks_from_group_before"] > 0
    assert result["chunks_from_group_after"] == 0 and result["effective_on_next_query"]


def test_contractor_sees_public_only():
    assert STORE.groups("contractor_lee") == {"public"}


# ---------- dense / hybrid code paths (test double, not a real model) ----------

def test_hybrid_and_dense_paths_run(md_docs):
    chunks = chunk_corpus(md_docs, "structured")
    r = Retriever(chunks, dense=DenseIndex(HashingEmbedder(), [c.text for c in chunks]))
    for method in ("dense", "hybrid"):
        hits, timings = r.search("GPU G1 最後採購日", STORE.groups("svc_wang"), method=method)
        assert hits and f"{'dense' if method == 'dense' else 'bm25'}_ms" in timings
        assert all(h.chunk.group in STORE.groups("svc_wang") for h in hits)


# ---------- metrics ----------

def test_score_ranking():
    ev = [{0, 5}]
    m = score_ranking([3, 5, 7], ev, ks=(1, 5, 10))
    assert m["recall@1"] == 0 and m["recall@5"] == 1 and m["mrr"] == 0.5
    assert score_ranking([], ev)["recall@10"] == 0


def test_evidence_matching_ignores_markdown_and_whitespace():
    c = Chunk("d#0", "d", "internal", "internal", "h", "收到通知後 **10 個工作天內**\n建立 ECR", None, False)
    assert evidence_sets([c], [{"doc_id": "d", "quote": "收到通知後 10 個工作天內 建立 ECR"}]) == [{0}]
    assert evidence_sets([c], [{"doc_id": "other", "quote": "建立 ECR"}]) == [set()]


# ---------- question bank ----------

def test_question_bank_is_well_formed():
    ids = [q["id"] for q in QUESTIONS]
    assert len(ids) == len(set(ids))
    users = set(json.loads((ROOT / "eval/users.json").read_text())["users"])
    for q in QUESTIONS:
        assert q["user"] in users
        assert q["type"] in {"fact", "table", "cross_lingual", "code", "unanswerable", "unauthorized"}
        assert bool(q["evidence"]) == (q["type"] != "unanswerable")


def test_unauthorized_questions_target_groups_the_user_lacks(md_docs):
    group_of = {d.doc_id: d.group for d in md_docs}
    for q in QUESTIONS:
        if q["type"] == "unauthorized":
            assert all(group_of[e["doc_id"]] not in STORE.groups(q["user"]) for e in q["evidence"])
        elif q["type"] != "unanswerable":
            assert all(group_of.get(e["doc_id"], "public") in STORE.groups(q["user"]) for e in q["evidence"])


def test_markdown_evidence_quotes_exist(md_docs):
    text = {d.doc_id: norm(d.text) for d in md_docs}
    for q in QUESTIONS:
        for e in q["evidence"]:
            if e["doc_id"] in text:
                assert norm(e["quote"]) in text[e["doc_id"]], (q["id"], e["quote"])


@pytest.mark.skipif(not (RAW / "fda-guidance-77635.pdf").exists(), reason="public PDFs not downloaded")
def test_pdf_evidence_quotes_exist_and_survive_chunking():
    docs, stats = load_corpus(CORPUS, RAW)
    assert not stats["pdf_missing"]
    text = {d.doc_id: norm(d.text) for d in docs}
    items = [e for q in QUESTIONS for e in q["evidence"]]
    for e in items:
        assert norm(e["quote"]) in text[e["doc_id"]], e
    for strategy in ("structured", "fixed"):
        chunks = chunk_corpus(docs, strategy)
        normed = [norm(c.text) for c in chunks]
        assert all(s for s in evidence_sets(chunks, items, normed)), strategy


# ---------- rerank server contract ----------

def test_rerank_server_matches_client_contract():
    pytest.importorskip("fastapi")
    import httpx
    from fastapi.testclient import TestClient

    sys.path.insert(0, str(ROOT / "scripts"))
    from rerank_server import create_app
    from rag.dense import HTTPReranker

    class FakeCrossEncoder:  # longer document = more relevant; enough to check the plumbing
        def predict(self, pairs):
            return [len(doc) for _, doc in pairs]

    client = TestClient(create_app(FakeCrossEncoder(), "fake"))
    docs = ["a", "ccc", "bb"]
    out = client.post("/rerank", json={"query": "q", "documents": docs}).json()
    assert [r["index"] for r in out["results"]] == [1, 2, 0]

    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=client.post(
        "/rerank", content=req.content, headers={"content-type": "application/json"}).json()))
    assert HTTPReranker("http://rerank", "fake", transport=transport).scores("q", docs) == [1.0, 3.0, 2.0]
