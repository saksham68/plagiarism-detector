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

## 2. The Core Algorithm: MinHash + LSH

**Step 1 — Shingling (NLP).** Break each document into overlapping 5-word
sequences ("shingles"). A document becomes a *set* of shingles. Two
documents that share a lot of shingles are similar; this is measured by
**Jaccard similarity**: `|A ∩ B| / |A ∪ B|`.

**Step 2 — MinHash (Dimensionality Reduction).** Computing exact Jaccard similarity still means
comparing large sets pairwise. MinHash compresses each shingle set into a
fixed-length **signature** (100 integers here) such that the fraction of
matching positions between two signatures is an unbiased *estimator* of
the true Jaccard similarity — without ever comparing the original sets
directly. 

**Step 3 — LSH (Locality Sensitive Hashing).** Even with fixed-length
signatures, comparing every pair of 100-length vectors is still O(N²).
LSH avoids this: split each signature into 20 bands of 5 values each, and
hash each band to a bucket. Two documents that land in the *same bucket
in any band* become a "candidate pair" — only these get an actual
similarity comparison. This is what turns the
algorithm from O(N²) into roughly O(N) in practice, at the cost of a
small, tunable false-negative rate.

## 3. Advanced Features

Beyond the core algorithm, Casefile implements several advanced SaaS and DSA features:

* **Diff Highlighting (Sequence Matching):** When clicking a flagged pair in the dashboard, the system uses a variant of the Ratcliff/Obershelp algorithm (`difflib.SequenceMatcher`) to dynamically compute the longest common contiguous blocks of text, highlighting the exact plagiarized sentences in a beautiful UI modal.
* **Cheating Rings (Graph Traversal):** The system models the SQLite database as an Undirected Graph (Nodes = Documents, Edges = Flagged matches). An iterative **Depth-First Search (DFS)** algorithm traverses this graph to detect and display connected components, revealing entire rings of students who plagiarized from each other (A ⟷ B ⟷ C).
* **Multi-Tenancy (Browser Sandboxing):** Implements a lightweight `localStorage` session injection system, guaranteeing that multiple TAs/users can use the app concurrently without seeing each other's documents, completely bypassing the need for a heavyweight login system.

## 4. What happens on each upload (`POST /api/documents`)

1. Normalize + shingle the text.
2. Compute its MinHash signature.
3. Store the document + signature in SQLite.
4. Split the signature into LSH bands, look up the `lsh_buckets` index for
   documents already sharing a bucket — these are the only candidates.
5. For each candidate, compute the estimated Jaccard similarity and store
   the result if it clears the threshold.
6. The graph algorithm dynamically recalculates all connected Cheating Rings.

## 5. Project structure

```
app.py          Flask routes, API, DFS Graph logic, Diffing logic
algorithm.py    Shingling, MinHash, LSH — the core algorithm, from scratch
db.py           SQLite schema + query helpers + multi-tenancy filtering
templates/      index.html (dashboard & modal UI)
static/         style.css, app.js
tests/          pytest suite mathematically proving algorithm correctness
sample_docs/    3 sample essays (A original, B near-duplicate, C unrelated)
```

## 6. Running locally

```bash
pip install -r requirements.txt
python app.py
# open http://localhost:5000
```

Try uploading `sample_docs/essay_a_original.txt`, then
`sample_docs/essay_b_paraphrased.txt` — it should flag them at ~80%+
similarity. Click the flagged match to see the **Diff Highlight modal**.
Then upload a third document that copies from `essay_b` to see the **Graph DFS** form a cheating ring!

## 7. Testing

A complete test suite is included in `tests/test_algorithm.py` to mathematically verify the estimators and hashing logic.
```bash
pytest tests/
```

## 8. Deploying

This repo is ready for **Render**:
1. Push to a GitHub repo.
2. On Render: New → Web Service → connect the repo. `render.yaml` in this
   repo configures the build/start commands automatically.

## 9. Design decisions worth knowing for an interview

- **Word-level shingles (k=5), not character-level.** Character shingles
  catch exact copy-paste better; word shingles are more robust to minor
  formatting changes but more sensitive to paraphrasing.
- **`lsh_buckets(band_index, bucket_key)` is indexed.** Finding candidates
  for a new document is an indexed lookup, not a table scan — this is
  what keeps insertion fast even as the corpus grows.
- **`similarity_results` only stores pairs that were actually compared.**
  It does not store all N² pairs — this table's size reflects the
  algorithm's efficiency, not the corpus size squared.
