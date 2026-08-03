"""
db.py
-----
SQLite persistence layer.

SCHEMA NOTES (interview talking points):
- `documents`: one row per submission.
- `lsh_buckets`: (band_index, bucket_key) -> document_id, with a composite
  INDEX on (band_index, bucket_key). This is the index that makes
  candidate lookup fast -- finding "who else is in my bucket" is an
  indexed lookup, not a table scan.
- `similarity_results`: only candidate pairs that were actually compared
  get a row here (not all N^2 pairs) -- this table stays small even as
  the document count grows, which is the whole point of LSH.
- `doc_a_id < doc_b_id` is enforced at write time so each pair is stored
  once, not twice.
"""

import sqlite3
import json
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "plagiarism.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    author TEXT,
    raw_text TEXT NOT NULL,
    shingle_count INTEGER NOT NULL,
    signature TEXT NOT NULL,      -- JSON-encoded MinHash signature
    uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS lsh_buckets (
    band_index INTEGER NOT NULL,
    bucket_key TEXT NOT NULL,
    document_id INTEGER NOT NULL,
    FOREIGN KEY (document_id) REFERENCES documents(id)
);
CREATE INDEX IF NOT EXISTS idx_bucket_lookup
    ON lsh_buckets (band_index, bucket_key);

CREATE TABLE IF NOT EXISTS similarity_results (
    doc_a_id INTEGER NOT NULL,
    doc_b_id INTEGER NOT NULL,
    jaccard_estimate REAL NOT NULL,
    flagged INTEGER NOT NULL,
    computed_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (doc_a_id, doc_b_id)
);
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    try:
        conn.execute("ALTER TABLE documents ADD COLUMN session_id TEXT DEFAULT 'anonymous'")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()


def insert_document(filename, author, raw_text, shingle_count, signature, session_id="anonymous"):
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO documents (filename, author, raw_text, shingle_count, signature, session_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (filename, author, raw_text, shingle_count, json.dumps(signature), session_id),
    )
    doc_id = cur.lastrowid
    conn.commit()
    conn.close()
    return doc_id


def insert_bucket_entries(entries):
    """entries: list of (band_index, bucket_key, document_id)"""
    conn = get_conn()
    conn.executemany(
        "INSERT INTO lsh_buckets (band_index, bucket_key, document_id) VALUES (?, ?, ?)",
        entries,
    )
    conn.commit()
    conn.close()


def find_bucket_matches(band_index, bucket_key, exclude_doc_id, session_id="anonymous"):
    conn = get_conn()
    rows = conn.execute(
        """SELECT DISTINCT l.document_id FROM lsh_buckets l
           JOIN documents d ON l.document_id = d.id
           WHERE l.band_index = ? AND l.bucket_key = ? AND l.document_id != ? AND d.session_id = ?""",
        (band_index, bucket_key, exclude_doc_id, session_id),
    ).fetchall()
    conn.close()
    return [r["document_id"] for r in rows]


def get_document(doc_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    conn.close()
    return row


def get_all_documents(session_id="anonymous"):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, filename, author, shingle_count, uploaded_at FROM documents WHERE session_id = ? ORDER BY id DESC",
        (session_id,)
    ).fetchall()
    conn.close()
    return rows


def upsert_similarity(doc_a_id, doc_b_id, jaccard_estimate, flagged):
    a, b = sorted((doc_a_id, doc_b_id))
    conn = get_conn()
    conn.execute(
        """INSERT INTO similarity_results (doc_a_id, doc_b_id, jaccard_estimate, flagged)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(doc_a_id, doc_b_id) DO UPDATE SET
               jaccard_estimate = excluded.jaccard_estimate,
               flagged = excluded.flagged,
               computed_at = CURRENT_TIMESTAMP""",
        (a, b, jaccard_estimate, int(flagged)),
    )
    conn.commit()
    conn.close()


def get_matches_for_document(doc_id):
    conn = get_conn()
    rows = conn.execute(
        """SELECT sr.*, d.filename AS other_filename, d.author AS other_author
           FROM similarity_results sr
           JOIN documents d ON d.id = CASE WHEN sr.doc_a_id = ? THEN sr.doc_b_id ELSE sr.doc_a_id END
           WHERE sr.doc_a_id = ? OR sr.doc_b_id = ?
           ORDER BY sr.jaccard_estimate DESC""",
        (doc_id, doc_id, doc_id),
    ).fetchall()
    conn.close()
    return rows


def get_all_flagged_matches(session_id="anonymous"):
    conn = get_conn()
    rows = conn.execute(
        """SELECT sr.*, da.filename AS a_filename, db.filename AS b_filename
           FROM similarity_results sr
           JOIN documents da ON da.id = sr.doc_a_id
           JOIN documents db ON db.id = sr.doc_b_id
           WHERE sr.flagged = 1 AND da.session_id = ?
           ORDER BY sr.jaccard_estimate DESC""",
        (session_id,)
    ).fetchall()
    conn.close()
    return rows


def get_stats(session_id="anonymous"):
    conn = get_conn()
    doc_count = conn.execute("SELECT COUNT(*) c FROM documents WHERE session_id = ?", (session_id,)).fetchone()["c"]
    comparisons_done = conn.execute("""
        SELECT COUNT(*) c FROM similarity_results sr
        JOIN documents d ON sr.doc_a_id = d.id
        WHERE d.session_id = ?
    """, (session_id,)).fetchone()["c"]
    flagged_count = conn.execute("""
        SELECT COUNT(*) c FROM similarity_results sr
        JOIN documents d ON sr.doc_a_id = d.id
        WHERE sr.flagged = 1 AND d.session_id = ?
    """, (session_id,)).fetchone()["c"]
    conn.close()
    max_possible = doc_count * (doc_count - 1) // 2
    return {
        "documents": doc_count,
        "comparisons_done": comparisons_done,
        "max_possible_pairs": max_possible,
        "flagged_pairs": flagged_count,
    }


def delete_document(doc_id):
    conn = get_conn()
    # 1. Delete associated similarity results
    conn.execute("DELETE FROM similarity_results WHERE doc_a_id = ? OR doc_b_id = ?", (doc_id, doc_id))
    # 2. Delete LSH bucket entries
    conn.execute("DELETE FROM lsh_buckets WHERE document_id = ?", (doc_id,))
    # 3. Delete the document itself
    conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    conn.commit()
    conn.close()
