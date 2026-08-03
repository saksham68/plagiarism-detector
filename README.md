# Casefile — Near-Duplicate Submission Detector

A small full-stack tool that flags near-duplicate text submissions (essays,
code comments, short-answer responses) without doing an expensive
pairwise comparison of every document against every other document.

Built with: **Flask** (REST API) + **SQLite** (persistence) + a plain
HTML/CSS/JS dashboard. The similarity engine (MinHash + LSH) is
implemented from scratch in `algorithm.py` — no external similarity
libraries — so every step is something you can explain line by line.

---

## 1. The problem

A TA has 300 student submissions and wants to know which pairs look
suspiciously similar. Comparing every pair directly costs O(N²) document
comparisons — with 300 documents that's ~45,000 comparisons, and each one
requires comparing potentially thousands of words. That does not scale to
a real course, let alone a real company's document set.

## 2. The approach: MinHash + LSH

**Step 1 — Shingling.** Break each document into overlapping 5-word
sequences ("shingles"). A document becomes a *set* of shingles. Two
documents that share a lot of shingles are similar; this is measured by
**Jaccard similarity**: `|A ∩ B| / |A ∪ B|`.

**Step 2 — MinHash.** Computing exact Jaccard similarity still means
comparing large sets pairwise. MinHash compresses each shingle set into a
fixed-length **signature** (100 integers here) such that the fraction of
matching positions between two signatures is an unbiased *estimator* of
the true Jaccard similarity — without ever comparing the original sets
directly. This works because of a neat probabilistic fact: under a random
hash function, the probability that two sets share the same minimum
hashed element equals their Jaccard similarity.

**Step 3 — LSH (Locality Sensitive Hashing).** Even with fixed-length
signatures, comparing every pair of 100-length vectors is still O(N²).
LSH avoids this: split each signature into 20 bands of 5 values each, and
hash each band to a bucket. Two documents that land in the *same bucket
in any band* become a "candidate pair" — only these get an actual
similarity comparison. Documents that share no bucket in any band are
assumed dissimilar and are never compared. This is what turns the
algorithm from O(N²) into roughly O(N) in practice, at the cost of a
small, tunable false-negative rate.

The band/row split determines the similarity threshold above which pairs
are likely to be caught — with 20 bands of 5 rows here, that threshold is
≈ 0.55 (see `LSH_THRESHOLD` in `algorithm.py`).

## 3. What happens on each upload (`POST /api/documents`)

1. Normalize + shingle the text.
2. Compute its MinHash signature.
3. Store the document + signature in SQLite.
4. Split the signature into LSH bands, look up the `lsh_buckets` index for
   documents already sharing a bucket — these are the only candidates.
5. For each candidate, compute the estimated Jaccard similarity and store
   the result if it clears the threshold.

The dashboard's "efficiency ledger" panel shows this directly: total
possible pairs (N²) vs. pairs actually compared — the gap between those
two numbers *is* the algorithm working.

## 4. Project structure

```
app.py          Flask routes / API
algorithm.py    Shingling, MinHash, LSH — the core algorithm, from scratch
db.py           SQLite schema + query helpers
templates/      index.html (dashboard)
static/         style.css, app.js
sample_docs/    3 sample essays (A original, B near-duplicate, C unrelated)
requirements.txt, Procfile, render.yaml   deployment
```

## 5. Running locally

```bash
pip install -r requirements.txt
python app.py
# open http://localhost:5000
```

Try uploading `sample_docs/essay_a_original.txt`, then
`sample_docs/essay_b_paraphrased.txt` — it should flag them at ~80%+
similarity. Then upload `essay_c_unrelated.txt` — it should not match
either, and should show 0 candidates checked (proving LSH skipped the
comparison entirely rather than comparing and scoring it low).

## 6. Deploying

This repo is ready for **Render**:
1. Push to a GitHub repo.
2. On Render: New → Web Service → connect the repo. `render.yaml` in this
   repo configures the build/start commands automatically.
3. Render gives you a live `https://your-app.onrender.com` URL.

(Railway or Fly.io work the same way — just point them at the repo; they
read `Procfile`.)

## 7. Design decisions worth knowing for a walkthrough

- **Word-level shingles (k=5), not character-level.** Character shingles
  catch exact copy-paste better; word shingles are more robust to minor
  formatting changes but more sensitive to paraphrasing, since changing
  even one word inside a 5-word window breaks that shingle. This is a
  real, discussable tradeoff — not an accident.
- **Signatures are stored, raw shingle sets are not re-derived per
  comparison.** Comparing two 100-length integer arrays is O(1)-ish
  (constant, fixed size) regardless of document length — that's the whole
  point of compressing to a signature.
- **`lsh_buckets(band_index, bucket_key)` is indexed.** Finding candidates
  for a new document is an indexed lookup, not a table scan — this is
  what keeps insertion fast even as the corpus grows.
- **`similarity_results` only stores pairs that were actually compared.**
  It does not store all N² pairs — this table's size reflects the
  algorithm's efficiency, not the corpus size squared.
- **Known limitation:** MinHash/LSH gives an *approximate*, probabilistic
  similarity — it can produce false negatives near the threshold boundary
  (a pair is genuinely similar but happens not to share a bucket). This
  is a real, acceptable tradeoff for scale, and worth naming proactively
  if asked "does this always catch every duplicate?" — it doesn't, by
  design, and that's the right answer.
