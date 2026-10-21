"""Okapi BM25 with a tokenizer that handles English, Chinese, and identifier-like strings.

Identifiers matter in this corpus: product codes (OEB), regulation numbers (892.2050), 510(k)
numbers (K231157), SOP numbers (QMS-SOP-007), scanner models (C-320). They are kept whole and
also split into their parts, so "21 CFR 892.2050" and "§892.2050" share the token "892.2050".
Chinese text has no spaces; it is indexed as overlapping character bigrams.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

import numpy as np

STOP = set("""a an the of in on for to and or with without by from at as is are was were be been being this that
these those it its we our their which who whom whose what when where why how than then there here not no do does
did can could may might should would will shall into over under between among during after before about if any all
also such other""".split())
TOKEN = re.compile(r"([a-z0-9]+(?:[-.][a-z0-9]+)*)|([㐀-䶿一-鿿]+)")


def tokenize(text: str) -> list[str]:
    out: list[str] = []
    for latin, cjk in TOKEN.findall(text.lower()):
        if latin:
            if latin in STOP or (len(latin) == 1 and not latin.isdigit()):
                continue
            out.append(latin)
            parts = re.split(r"[-.]", latin)
            if len(parts) > 1:
                out.extend(p for p in parts if p and p not in STOP and (len(p) > 1 or p.isdigit()))
        else:
            out.extend(cjk[i:i + 2] for i in range(len(cjk) - 1)) if len(cjk) > 1 else out.append(cjk)
    return out


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.2, b: float = 0.75):
        self.n = len(docs)
        self.k1, self.b = k1, b
        self.doc_len = np.array([len(d) for d in docs], dtype=np.float64)
        self.avgdl = float(self.doc_len.mean()) if self.n else 0.0
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for i, d in enumerate(docs):
            for term, tf in Counter(d).items():
                self.postings[term].append((i, tf))
        self.idf = {t: math.log((self.n - len(p) + 0.5) / (len(p) + 0.5) + 1.0) for t, p in self.postings.items()}

    def scores(self, query: list[str]) -> np.ndarray:
        s = np.zeros(self.n)
        norm = self.k1 * (1 - self.b + self.b * self.doc_len / self.avgdl)
        for term in set(query):
            for i, tf in self.postings.get(term, ()):
                s[i] += self.idf[term] * tf * (self.k1 + 1) / (tf + norm[i])
        return s
