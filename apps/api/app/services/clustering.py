"""F2 step 3 — two-stage cross-employee clustering of task signatures.

Stage 1 is an exact signature-hash bucket: cheap, and it resolves the large
majority of instances because most repetitive work really is identical.

Stage 2 is fuzzy agglomerative clustering over the surviving bucket
representatives, blending three complementary signals:

1. Normalised Levenshtein similarity on the step sequence — order-sensitive.
2. Jaccard overlap on the *set* of step tokens — order-invariant.
3. Cosine similarity on an embedding of the signature text — vocabulary-aware.

All three are necessary. Sequence distance alone cannot tell that
`sheets:create:row` and `erp:create:record` are near-synonyms. Embeddings alone
happily merge two workflows that share vocabulary but differ in structure.

The set-overlap term earns its place for a specific and important reason: a
genuinely high-variance workflow performs the same handful of steps in a
different order every time. Under order-sensitive similarity alone, such a
workflow shatters into singleton clusters and is never surfaced at all — so the
system would stay silent about exactly the workflows a human most needs warning
about. Set overlap holds those instances together long enough for F3 to measure
their step-order entropy and flag them DO NOT AUTOMATE. Detecting that a task
should *not* be automated is a first-class result, and it depends on this term.

Embeddings come from sentence-transformers when it is installed, and from a
character-n-gram TF-IDF projection otherwise. The fallback keeps a clean clone
installable without a 2GB torch download, and on strings this short and this
templated it performs comparably.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
from rapidfuzz.distance import Levenshtein
from sklearn.cluster import AgglomerativeClustering
from sklearn.feature_extraction.text import TfidfVectorizer

from app.config import settings
from app.services.sessioniser import Instance, signature_hash, signature_text

logger = logging.getLogger("loop.clustering")

_st_model = None
_st_unavailable = False


@dataclass
class ClusterResult:
    """A group of task instances judged to be the same workflow."""

    instances: list[Instance]
    representative: list[str]
    members_by_hash: dict[str, int] = field(default_factory=dict)

    @property
    def size(self) -> int:
        return len(self.instances)


def _get_sentence_model():
    """Load sentence-transformers lazily; return None if it is not installed."""
    global _st_model, _st_unavailable
    if _st_unavailable:
        return None
    if _st_model is None:
        try:
            from sentence_transformers import SentenceTransformer

            _st_model = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("clustering: using sentence-transformers embeddings")
        except Exception as exc:  # noqa: BLE001 — optional dependency
            logger.info("clustering: sentence-transformers unavailable (%s); using TF-IDF", exc)
            _st_unavailable = True
            return None
    return _st_model


def embed(texts: Sequence[str]) -> np.ndarray:
    """Embed signature strings into L2-normalised vectors."""
    if not texts:
        return np.zeros((0, 1))
    model = _get_sentence_model()
    if model is not None:
        vectors = np.asarray(model.encode(list(texts), normalize_embeddings=True))
        return vectors
    if len(texts) == 1:
        return np.ones((1, 1))
    # Character n-grams capture the token structure of `app:action:object`
    # strings better than word tokens, which would split on the colons.
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1)
    matrix = vectorizer.fit_transform(list(texts)).toarray()
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def sequence_similarity(a: Sequence[str], b: Sequence[str]) -> float:
    """Normalised Levenshtein similarity over step sequences.

    Operates on the sequences as lists of tokens, not as concatenated strings,
    so one substituted step costs exactly one edit rather than a number of edits
    proportional to how long the step's name happens to be.
    """
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    vocabulary: dict[str, int] = {}
    for token in list(a) + list(b):
        vocabulary.setdefault(token, len(vocabulary))
    left = [vocabulary[t] for t in a]
    right = [vocabulary[t] for t in b]
    return float(Levenshtein.normalized_similarity(left, right))


def set_similarity(a: Sequence[str], b: Sequence[str]) -> float:
    """Jaccard overlap on step tokens, ignoring order and repetition."""
    left, right = set(a), set(b)
    if not left and not right:
        return 1.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def combined_similarity(
    a: Sequence[str],
    b: Sequence[str],
    embedding_a: np.ndarray,
    embedding_b: np.ndarray,
    sequence_weight: float | None = None,
    set_weight: float | None = None,
) -> float:
    """Blend the three similarity signals into one score in [0, 1].

    The embedding term takes whatever weight the other two leave, so the three
    weights always sum to exactly 1 and the score stays in [0, 1].
    """
    w_seq = settings.sequence_weight if sequence_weight is None else sequence_weight
    w_set = settings.set_weight if set_weight is None else set_weight
    w_emb = max(0.0, 1.0 - w_seq - w_set)

    sequence = sequence_similarity(a, b)
    overlap = set_similarity(a, b)
    embedding = max(0.0, min(1.0, float(np.dot(embedding_a, embedding_b))))
    return w_seq * sequence + w_set * overlap + w_emb * embedding


def cluster_instances(
    instances: Sequence[Instance],
    threshold: float | None = None,
    sequence_weight: float | None = None,
    set_weight: float | None = None,
) -> list[ClusterResult]:
    """Cluster task instances into workflows. Returns groups sorted by size."""
    if not instances:
        return []

    accept = settings.cluster_threshold if threshold is None else threshold

    # ── Stage 1: exact signature hash ──────────────────────────────────────
    buckets: dict[str, list[Instance]] = {}
    for instance in instances:
        buckets.setdefault(signature_hash(instance.signature), []).append(instance)

    hashes = list(buckets.keys())
    if len(hashes) == 1:
        only = buckets[hashes[0]]
        return [
            ClusterResult(
                instances=only,
                representative=_medoid(only),
                members_by_hash={hashes[0]: len(only)},
            )
        ]

    # ── Stage 2: fuzzy merge of bucket representatives ─────────────────────
    representatives = [buckets[h][0].signature for h in hashes]
    texts = [signature_text(s) for s in representatives]
    embeddings = embed(texts)

    n = len(hashes)
    distance = np.zeros((n, n), dtype=float)
    for i in range(n):
        for j in range(i + 1, n):
            similarity = combined_similarity(
                representatives[i],
                representatives[j],
                embeddings[i],
                embeddings[j],
                sequence_weight=sequence_weight,
                set_weight=set_weight,
            )
            distance[i, j] = distance[j, i] = 1.0 - similarity

    model = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=1.0 - accept,
        metric="precomputed",
        linkage="average",
    )
    labels = model.fit_predict(distance)

    grouped: dict[int, list[str]] = {}
    for label, bucket_hash in zip(labels, hashes, strict=True):
        grouped.setdefault(int(label), []).append(bucket_hash)

    results: list[ClusterResult] = []
    for bucket_hashes in grouped.values():
        members: list[Instance] = []
        counts: dict[str, int] = {}
        for bucket_hash in bucket_hashes:
            members.extend(buckets[bucket_hash])
            counts[bucket_hash] = len(buckets[bucket_hash])
        results.append(
            ClusterResult(
                instances=members,
                representative=_medoid(members),
                members_by_hash=counts,
            )
        )

    results.sort(key=lambda r: r.size, reverse=True)
    return results


def _medoid(instances: Sequence[Instance]) -> list[str]:
    """The member signature with the highest total similarity to all others.

    Preferred over the most frequent signature because it degrades gracefully
    when a cluster has no dominant variant.
    """
    signatures = [i.signature for i in instances]
    if len(signatures) == 1:
        return list(signatures[0])
    # Cap the comparison set: medoid selection is O(n^2) and precision beyond a
    # sample of this size does not change the chosen representative.
    sample = signatures[:200]
    best_index, best_total = 0, -1.0
    for i, candidate in enumerate(sample):
        total = sum(sequence_similarity(candidate, other) for other in sample)
        if total > best_total:
            best_index, best_total = i, total
    return list(sample[best_index])
