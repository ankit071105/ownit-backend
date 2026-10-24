"""MinHash from scratch — estimates how similar two texts are.

Idea (simple version):
1. Break text into "shingles" = overlapping groups of k words.
   "built with create react app" -> {"built with create", "with create react", ...}
2. Jaccard similarity = |A ∩ B| / |A ∪ B|  (shared shingles / all shingles)
3. Comparing big sets is slow, so MinHash keeps only a small "signature":
   for each of N hash functions, store the smallest hash value in the set.
   The fraction of signature slots that match ≈ Jaccard similarity.

We use it to check if a README is basically a starter-template README.
"""
import hashlib
import re

_WORD = re.compile(r"[a-z0-9]+")
_MAX_HASH = (1 << 32) - 1
_PRIME = 4294967311  # a prime > 2^32


def shingles(text: str, k: int = 3) -> set[str]:
    words = _WORD.findall(text.lower())
    if len(words) < k:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + k]) for i in range(len(words) - k + 1)}


def _base_hash(s: str) -> int:
    return int.from_bytes(hashlib.md5(s.encode()).digest()[:4], "little")


class MinHasher:
    """N random linear hash functions h(x) = (a*x + b) mod p."""

    def __init__(self, num_perm: int = 128, seed: int = 7):
        import random

        rng = random.Random(seed)
        self.params = [
            (rng.randint(1, _PRIME - 1), rng.randint(0, _PRIME - 1))
            for _ in range(num_perm)
        ]

    def signature(self, items: set[str]) -> list[int]:
        if not items:
            return [_MAX_HASH] * len(self.params)
        base = [_base_hash(i) for i in items]
        return [min(((a * x + b) % _PRIME) & _MAX_HASH for x in base) for a, b in self.params]

    @staticmethod
    def similarity(sig_a: list[int], sig_b: list[int]) -> float:
        same = sum(1 for x, y in zip(sig_a, sig_b) if x == y)
        return same / len(sig_a)


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)
