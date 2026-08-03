"""
app.py
------
Flask REST API for the similarity detector.

FLOW ON UPLOAD (POST /api/documents):
  1. Normalize text and extract shingles.
  2. Compute MinHash signature (fixed-length, ~100 ints regardless of doc size).
  3. Persist document + signature.
  4. Split signature into LSH bands; for each band, look up documents
     already sharing that band's bucket key (indexed lookup).
  5. Union candidate doc_ids across all bands -> this document is only
     ever compared against these candidates, not every document in the DB.
  6. For each candidate, compute the actual MinHash-estimated Jaccard
     similarity and store the result; flag pairs above the threshold.
"""

from flask import Flask, request, jsonify, render_template
import db
import algorithm as algo

app = Flask(__name__)
db.init_db()
hasher = algo.MinHasher()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/stats")
def stats():
    return jsonify(db.get_stats())


@app.route("/api/documents", methods=["GET"])
def list_documents():
    rows = db.get_all_documents()
    return jsonify([dict(r) for r in rows])


@app.route("/api/documents", methods=["POST"])
def upload_document():
    data = request.get_json(force=True)
    filename = (data.get("filename") or "untitled.txt").strip()
    author = (data.get("author") or "").strip()
    text = data.get("text", "")

    if not text or len(text.strip()) == 0:
        return jsonify({"error": "text is required"}), 400

    shingles = algo.get_shingles(text)
    signature = hasher.signature(shingles)
    doc_id = db.insert_document(filename, author, text, len(shingles), signature)

    # --- LSH bucketing ---
    bands = algo.lsh_bands(signature)
    bucket_entries = [(band_idx, key, doc_id) for band_idx, key in bands]

    candidate_ids = set()
    for band_idx, key in bands:
        for other_id in db.find_bucket_matches(band_idx, key, doc_id):
            candidate_ids.add(other_id)

    db.insert_bucket_entries(bucket_entries)

    # --- compare only against LSH candidates, not the whole corpus ---
    new_matches = []
    for other_id in candidate_ids:
        other_doc = db.get_document(other_id)
        if other_doc is None:
            continue
        import json
        other_sig = json.loads(other_doc["signature"])
        est = algo.estimate_jaccard(signature, other_sig)
        flagged = est >= algo.LSH_THRESHOLD
        db.upsert_similarity(doc_id, other_id, est, flagged)
        new_matches.append({
            "document_id": other_id,
            "filename": other_doc["filename"],
            "similarity": round(est, 4),
            "flagged": flagged,
        })

    new_matches.sort(key=lambda m: m["similarity"], reverse=True)

    return jsonify({
        "document_id": doc_id,
        "filename": filename,
        "shingle_count": len(shingles),
        "candidates_checked": len(candidate_ids),
        "matches": new_matches,
        "threshold": round(algo.LSH_THRESHOLD, 3),
    }), 201


@app.route("/api/documents/<int:doc_id>/matches")
def document_matches(doc_id):
    rows = db.get_matches_for_document(doc_id)
    return jsonify([dict(r) for r in rows])


@app.route("/api/matches")
def all_matches():
    rows = db.get_all_flagged_matches()
    return jsonify([dict(r) for r in rows])


@app.route("/api/config")
def config():
    return jsonify({
        "shingle_size": algo.SHINGLE_SIZE,
        "num_hashes": algo.NUM_HASHES,
        "num_bands": algo.NUM_BANDS,
        "rows_per_band": algo.ROWS_PER_BAND,
        "lsh_threshold": round(algo.LSH_THRESHOLD, 4),
    })


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
