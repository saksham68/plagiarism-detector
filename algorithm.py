"""
algorithm.py
------------
Implements text similarity detection using MinHash + Locality Sensitive
Hashing (LSH), built from scratch (no external similarity libraries).

WHY THIS APPROACH (the interview pitch):
Comparing every pair of N documents directly (pairwise Jaccard similarity)
costs O(N^2 * D) where D is document size -- infeasible once you have
thousands of submissions. MinHash compresses each document into a small,
fixed-size "signature" that approximates its Jaccard similarity to any
other document. LSH then buckets documents so that only signatures likely
to be similar ever get compared, turning an O(N^2) problem into roughly
O(N) in practice.

PIPELINE:
  raw text -> shingles (k-word n-grams) -> MinHash signature -> LSH buckets
            -> candidate pairs -> estimated Jaccard similarity
"""

import hashlib
import random
import re
from collections import defaultdict

# ---------------------------------------------------------------------------
# Tunable parameters
# ---------------------------------------------------------------------------
SHINGLE_SIZE = 5          # k-word shingles
NUM_HASHES = 100          # length of the MinHash signature
NUM_BANDS = 20             # LSH bands
ROWS_PER_BAND = NUM_HASHES // NUM_BANDS   # 5 rows per band

# LSH similarity threshold this configuration is tuned for:
#   threshold ~= (1 / bands) ^ (1 / rows_per_band)
# With bands=20, rows=5 -> ~0.55. Pairs with true Jaccard similarity above
# this tend to land in at least one shared bucket with high probability;
# pairs well below it are unlikely to collide, which is *the* trick that
# keeps this sub-quadratic.
LSH_THRESHOLD = (1 / NUM_BANDS) ** (1 / ROWS_PER_BAND)

_LARGE_PRIME = 4294967311  # smallest prime > 2^32, used for hash universe


def normalize_text(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def get_shingles(text: str, k: int = SHINGLE_SIZE) -> set:
    """
    Break normalized text into overlapping k-word shingles.
    e.g. "the quick brown fox jumps" with k=3 ->
         {"the quick brown", "quick brown fox", "brown fox jumps"}
    Each shingle is hashed to a stable 32-bit integer so we never have to
    store or compare raw strings downstream.
    """
    words = normalize_text(text).split()
    if len(words) < k:
        return {_stable_hash(" ".join(words))} if words else set()
    return {
        _stable_hash(" ".join(words[i:i + k]))
        for i in range(len(words) - k + 1)
    }


def _stable_hash(s: str) -> int:
    """Deterministic hash (md5-based) -- unlike Python's hash(), this is
    stable across runs and processes, which matters since signatures are
    persisted to disk and compared later."""
    return int(hashlib.md5(s.encode("utf-8")).hexdigest(), 16) % _LARGE_PRIME


class MinHasher:
    """
    Generates MinHash signatures using NUM_HASHES independent
    universal hash functions of the form: h(x) = (a*x + b) mod p.

    The seed is fixed so the SAME hash functions are reused for every
    document -- this is essential: signatures are only comparable to each
    other if they were built with the same hash family.
    """

    def __init__(self, num_hashes: int = NUM_HASHES, seed: int = 42):
        rng = random.Random(seed)
        self.num_hashes = num_hashes
        self.coeffs = [
            (rng.randint(1, _LARGE_PRIME - 1), rng.randint(0, _LARGE_PRIME - 1))
            for _ in range(num_hashes)
        ]

    def signature(self, shingles: set) -> list:
        """
        For each of the NUM_HASHES hash functions, find the MINIMUM hashed
        value across all shingles in the document. This is the core
        MinHash trick: the probability that two documents share the same
        minimum hash under a random permutation equals their Jaccard
        similarity. Doing this NUM_HASHES times and comparing how many
        positions match gives an unbiased *estimator* of Jaccard similarity
        using fixed-size vectors instead of full shingle sets.
        """
        if not shingles:
            return [0] * self.num_hashes
        sig = []
        for a, b in self.coeffs:
            min_val = min((a * s + b) % _LARGE_PRIME for s in shingles)
            sig.append(min_val)
        return sig


def estimate_jaccard(sig_a: list, sig_b: list) -> float:
    """Fraction of matching positions between two MinHash signatures --
    an unbiased estimator of true Jaccard similarity of the shingle sets."""
    if not sig_a or not sig_b:
        return 0.0
    matches = sum(1 for x, y in zip(sig_a, sig_b) if x == y)
    return matches / len(sig_a)


def lsh_bands(signature: list, bands: int = NUM_BANDS, rows: int = ROWS_PER_BAND):
    """
    Split a signature into `bands` chunks of `rows` values each, and hash
    each chunk to a single bucket key. Two documents that share a bucket
    key IN ANY BAND become "candidate pairs" worth comparing directly.

    This is what makes LSH sub-quadratic: instead of comparing every
    document to every other document, we only compare documents that
    landed in the same bucket at least once -- and the band/row split is
    tuned (see LSH_THRESHOLD) so that only genuinely similar documents are
    likely to collide.
    """
    out = []
    for band_idx in range(bands):
        chunk = tuple(signature[band_idx * rows:(band_idx + 1) * rows])
        bucket_key = hashlib.md5(str(chunk).encode()).hexdigest()
        out.append((band_idx, bucket_key))
    return out
