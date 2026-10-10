"""Stdlib BM25 ranking used when local embeddings are not available."""

from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def bm25_scores(
    query: str,
    documents: list[str],
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[float]:
    """Score each document against ``query``. Higher is a closer match."""
    if not documents:
        return []
    query_terms = tokenize(query)
    if not query_terms:
        return [0.0] * len(documents)
    tokenized = [tokenize(document) for document in documents]
    lengths = [len(tokens) for tokens in tokenized]
    average = sum(lengths) / len(lengths) if lengths else 0.0
    doc_count = len(tokenized)
    document_frequency: Counter[str] = Counter()
    for tokens in tokenized:
        document_frequency.update(set(tokens))
    scores: list[float] = []
    for tokens, length in zip(tokenized, lengths):
        frequency = Counter(tokens)
        score = 0.0
        for term in query_terms:
            seen = document_frequency.get(term, 0)
            if seen == 0 or term not in frequency:
                continue
            idf = math.log(1.0 + (doc_count - seen + 0.5) / (seen + 0.5))
            term_frequency = frequency[term]
            denominator = term_frequency + k1 * (1.0 - b + b * (length / average if average else 0.0))
            score += idf * (term_frequency * (k1 + 1.0)) / denominator
        scores.append(score)
    return scores
