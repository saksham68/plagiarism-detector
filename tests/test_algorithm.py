# pyrefly: ignore [missing-import]
import pytest
import sys
import os

# Add the parent directory to sys.path to import algorithm.py
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import algorithm as algo

def test_normalize_text():
    """Test that text is normalized correctly."""
    raw = "Hello, World! This is a TEST.\n\nIt should collapse   spaces."
    expected = "hello world this is a test it should collapse spaces"
    assert algo.normalize_text(raw) == expected

def test_get_shingles():
    """Test that n-gram shingles are correctly extracted and hashed."""
    # "the quick brown fox" -> k=3 -> ["the quick brown", "quick brown fox"]
    text = "The quick brown fox."
    shingles = algo.get_shingles(text, k=3)
    
    # Check that it generated exactly 2 shingles
    assert len(shingles) == 2
    
    # Check that they are stable integers
    assert all(isinstance(s, int) for s in shingles)
    
    # If text is smaller than k, it should just return the whole text as 1 shingle
    short_text = "Hello world"
    short_shingles = algo.get_shingles(short_text, k=3)
    assert len(short_shingles) == 1

def test_minhash_determinism():
    """Test that MinHash signatures are deterministic for the same input."""
    hasher = algo.MinHasher(num_hashes=100, seed=42)
    
    text = "This is a long test document to prove determinism."
    shingles = algo.get_shingles(text)
    
    sig1 = hasher.signature(shingles)
    sig2 = hasher.signature(shingles)
    
    # The signature must be identical for the same input
    assert sig1 == sig2
    assert len(sig1) == 100

def test_jaccard_estimator():
    """Test that the Jaccard estimator works correctly on MinHash signatures."""
    hasher = algo.MinHasher()
    
    doc1 = "The quick brown fox jumps over the lazy dog"
    doc2 = "The quick brown fox jumps over the lazy dog" # identical
    doc3 = "A completely different document about distributed systems" # totally disjoint
    doc4 = "The quick brown fox jumps over the sleeping cat" # slightly different
    
    sig1 = hasher.signature(algo.get_shingles(doc1, k=2))
    sig2 = hasher.signature(algo.get_shingles(doc2, k=2))
    sig3 = hasher.signature(algo.get_shingles(doc3, k=2))
    sig4 = hasher.signature(algo.get_shingles(doc4, k=2))
    
    # Identical documents should have ~1.0 similarity
    assert algo.estimate_jaccard(sig1, sig2) == 1.0
    
    # Disjoint documents should have ~0.0 similarity
    assert algo.estimate_jaccard(sig1, sig3) < 0.1
    
    # Slightly different documents should be high, but < 1.0
    sim_similar = algo.estimate_jaccard(sig1, sig4)
    assert 0.4 < sim_similar < 1.0

def test_lsh_bucketing():
    """Test that a signature is split into the correct number of LSH bands."""
    hasher = algo.MinHasher(num_hashes=100)
    sig = hasher.signature(algo.get_shingles("Test document"))
    
    # With 100 hashes and 20 bands, each band has 5 rows
    bands = algo.lsh_bands(sig, bands=20, rows=5)
    
    assert len(bands) == 20
    # Each entry should be a tuple (band_index, bucket_hash)
    assert isinstance(bands[0], tuple)
    assert len(bands[0]) == 2
    assert isinstance(bands[0][1], str) # the hash should be a string
