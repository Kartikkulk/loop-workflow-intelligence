"""Readable, prefixed identifiers. Demo transcripts are easier to follow than UUIDs."""

import secrets

# 6 bytes, not 4. A single seed run creates ~8,500 events; at 4 bytes the
# birthday probability of a primary-key collision is roughly 1 in 120, which is
# frequent enough to break a seed at the worst possible moment.
_ENTROPY_BYTES = 6


def new_id(prefix: str) -> str:
    """Generate a short prefixed id, e.g. `clu_9f2a1c4b3d7e`."""
    return f"{prefix}_{secrets.token_hex(_ENTROPY_BYTES)}"


class SequentialIds:
    """Deterministic id source for the seed generator.

    The seed generator promises byte-identical output for a given seed. Random
    ids would break that promise, and they also collide: sequential ids do
    neither.
    """

    def __init__(self, salt: int = 0) -> None:
        self._counters: dict[str, int] = {}
        self._salt = salt

    def __call__(self, prefix: str) -> str:
        index = self._counters.get(prefix, 0)
        self._counters[prefix] = index + 1
        return f"{prefix}_{self._salt:04x}{index:07x}"
