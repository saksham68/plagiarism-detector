const API = "/api";

async function refreshStats() {
  const res = await fetch(`${API}/stats`);
  const s = await res.json();
  document.getElementById("stat-docs").textContent = s.documents;
  document.getElementById("stat-possible").textContent = s.max_possible_pairs;
  document.getElementById("stat-done").textContent = s.comparisons_done;
  document.getElementById("stat-flagged").textContent = s.flagged_pairs;
}

async function refreshConfig() {
  const res = await fetch(`${API}/config`);
  const c = await res.json();
  document.getElementById("stat-threshold").textContent = c.lsh_threshold;
}

async function refreshDocuments() {
  const res = await fetch(`${API}/documents`);
  const docs = await res.json();
  const el = document.getElementById("documents-list");
  if (docs.length === 0) {
    el.innerHTML = `<p class="empty">Nothing submitted yet.</p>`;
    return;
  }
  el.innerHTML = docs.map(d => `
    <div class="doc-row">
      <div>
        <div class="doc-name">${escapeHtml(d.filename)}</div>
        <div class="doc-meta">${d.author ? escapeHtml(d.author) + " · " : ""}${d.shingle_count} shingles</div>
      </div>
      <div class="doc-meta">#${d.id}</div>
    </div>
  `).join("");
}

async function refreshMatches() {
  const res = await fetch(`${API}/matches`);
  const matches = await res.json();
  const el = document.getElementById("matches-list");
  if (matches.length === 0) {
    el.innerHTML = `<p class="empty">No flagged pairs yet — submit at least two overlapping documents.</p>`;
    return;
  }
  el.innerHTML = matches.map(m => `
    <div class="match-card">
      <div class="match-pair">
        <div class="names">${escapeHtml(m.a_filename)} ⟷ ${escapeHtml(m.b_filename)}</div>
        <div class="sub">docs #${m.doc_a_id} / #${m.doc_b_id}</div>
      </div>
      <div class="similarity-badge">${Math.round(m.jaccard_estimate * 100)}%</div>
    </div>
  `).join("");
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

document.getElementById("upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const filename = document.getElementById("f-filename").value.trim();
  const author = document.getElementById("f-author").value.trim();
  const text = document.getElementById("f-text").value;
  const resultLine = document.getElementById("upload-result");

  resultLine.textContent = "Running MinHash + LSH…";

  const res = await fetch(`${API}/documents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename, author, text }),
  });

  if (!res.ok) {
    resultLine.textContent = "Error: " + (await res.json()).error;
    return;
  }

  const data = await res.json();
  resultLine.textContent =
    `Checked against ${data.candidates_checked} LSH candidate(s), ` +
    `not the full corpus — ${data.matches.filter(m => m.flagged).length} flagged.`;

  document.getElementById("f-text").value = "";
  document.getElementById("f-filename").value = "";
  document.getElementById("f-author").value = "";

  await Promise.all([refreshStats(), refreshDocuments(), refreshMatches()]);
});

(async function init() {
  await Promise.all([refreshStats(), refreshConfig(), refreshDocuments(), refreshMatches()]);
})();
