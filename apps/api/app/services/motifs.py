"""Deterministic intra-instance motif mining for the Activity Atlas.

A motif is a repeated token subsequence of length >= 3. Mining reports
counts only: it does not decide that a pattern is a repetitive workflow.

Discovery looks for consecutive, non-overlapping tandem repeats inside one
instance signature. The primitive period of each run is kept so that
A B C A B C A B C becomes (A B C) x3 rather than (A B C A B C) x1 leftover,
while A B C D A B C D stays (A B C D) x2 instead of every substring.

After motifs are discovered, every instance is scanned for non-overlapping
occurrences of those token sequences so a single leftover copy in another
instance still contributes to total_occurrences.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from app.services.sessioniser import signature_hash

MIN_MOTIF_LENGTH = 3
# Workflow-like repeats are short; capping block size keeps mining O(n * L).
DEFAULT_MAX_MOTIF_LENGTH = 16
# Only the prefix of an oversized signature is mined. Collapsed signatures
# are typically far shorter than this.
DEFAULT_MAX_SCAN_LENGTH = 256


def motif_id_for(tokens: Sequence[str]) -> str:
    """Stable id derived only from the canonical token sequence."""
    return f"motif_{signature_hash(tokens)}"


def primitive_block(block: Sequence[str], min_len: int = MIN_MOTIF_LENGTH) -> tuple[str, ...]:
    """Smallest period of `block` whose length is at least `min_len`."""
    items = list(block)
    n = len(items)
    for period in range(min_len, n):
        if n % period == 0 and items[:period] * (n // period) == items:
            return tuple(items[:period])
    return tuple(items)


def count_nonoverlapping(sequence: Sequence[str], motif: Sequence[str]) -> int:
    """Count consecutive motif copies; matches do not overlap."""
    seq = list(sequence)
    block = list(motif)
    length = len(block)
    if length == 0 or length > len(seq):
        return 0
    count = 0
    i = 0
    while i + length <= len(seq):
        if seq[i : i + length] == block:
            count += 1
            i += length
        else:
            i += 1
    return count


def discover_tandem_motifs(
    sequence: Sequence[str],
    *,
    min_len: int = MIN_MOTIF_LENGTH,
    max_len: int = DEFAULT_MAX_MOTIF_LENGTH,
    max_scan_length: int = DEFAULT_MAX_SCAN_LENGTH,
) -> dict[tuple[str, ...], int]:
    """Find primitive tandem repeats in one sequence.

    Longer tandem runs are committed first and mark their span as covered, so
    A B C D A B C D yields (A B C D) rather than A B C / B C D / A B.
    A block that is itself a repetition is reduced to its primitive period, so
    (A B C A B C) x2 becomes (A B C) x4.
    """
    seq = list(sequence)[:max_scan_length]
    n = len(seq)
    if n < 2 * min_len:
        return {}

    covered = [False] * n
    found: dict[tuple[str, ...], int] = defaultdict(int)
    max_block = min(max_len, n // 2)

    for length in range(max_block, min_len - 1, -1):
        i = 0
        while i + 2 * length <= n:
            if covered[i]:
                i += 1
                continue
            block = seq[i : i + length]
            copies = 1
            while (
                i + (copies + 1) * length <= n
                and not covered[i + copies * length]
                and seq[i + copies * length : i + (copies + 1) * length] == block
            ):
                copies += 1
            if copies >= 2:
                primitive = primitive_block(block, min_len)
                period = len(primitive)
                if period >= min_len:
                    total = (length * copies) // period
                    if total >= 2:
                        found[primitive] += total
                        end = i + length * copies
                        covered[i:end] = [True] * (end - i)
                        i = end
                        continue
            i += 1
    return dict(found)


def has_tandem_repeat(
    sequence: Sequence[str],
    *,
    min_len: int = MIN_MOTIF_LENGTH,
    max_len: int = DEFAULT_MAX_MOTIF_LENGTH,
    max_scan_length: int = DEFAULT_MAX_SCAN_LENGTH,
) -> bool:
    return bool(
        discover_tandem_motifs(
            sequence, min_len=min_len, max_len=max_len, max_scan_length=max_scan_length
        )
    )
