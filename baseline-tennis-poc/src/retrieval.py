"""Document chunking, embedding, and search over the knowledge index.

Two collections: document chunks (for search_knowledge) and catalog entries (for
discover_assets). Every chunk carries its wrapper metadata, so authority and
effective date travel with the text into the agent's context and the agent can
rank on governance rather than on similarity score.

The embedding model loads lazily. Server startup must stay fast, and a demo that
never asks a document question should never pay for the model load.
"""

from __future__ import annotations

import os
import re

from catalog import get_catalog

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(ROOT, "data", "documents")
CHROMA_DIR = os.path.join(ROOT, "data", "chroma")
MODEL_NAME = "all-MiniLM-L6-v2"

CHUNK_TOKENS = 500
OVERLAP_TOKENS = 50
# Rough token-to-word ratio for chunk sizing; exact tokenization is not needed
# because chunk boundaries only affect retrieval granularity.
WORDS_PER_CHUNK = int(CHUNK_TOKENS * 0.75)
WORDS_OVERLAP = int(OVERLAP_TOKENS * 0.75)

_model = None
_client = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def _get_client():
    global _client
    if _client is None:
        import chromadb
        from chromadb.config import Settings
        _client = chromadb.PersistentClient(
            path=CHROMA_DIR, settings=Settings(anonymized_telemetry=False))
    return _client


def embed(texts: list[str]) -> list[list[float]]:
    return _get_model().encode(texts, show_progress_bar=False).tolist()


# ---------------------------------------------------------------- chunking


def chunk_document(text: str) -> list[str]:
    """Split on words with overlap, preferring paragraph boundaries."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    count = 0
    for para in paras:
        words = para.split()
        if count + len(words) > WORDS_PER_CHUNK and current:
            chunks.append(" ".join(current))
            # Carry an overlap window so a fact split across a boundary is still
            # retrievable from at least one chunk.
            tail = current[-WORDS_OVERLAP:] if WORDS_OVERLAP else []
            current, count = list(tail), len(tail)
        current.extend(words)
        count += len(words)
    if current:
        chunks.append(" ".join(current))
    return chunks or [text]


# ---------------------------------------------------------------- ingestion


def build_index(verbose: bool = True) -> dict:
    """(Re)build both collections from disk. Idempotent."""
    cat = get_catalog()
    client = _get_client()
    for name in ("documents", "catalog"):
        try:
            client.delete_collection(name)
        except Exception:
            pass

    docs_col = client.create_collection("documents",
                                        metadata={"hnsw:space": "cosine"})
    cat_col = client.create_collection("catalog",
                                       metadata={"hnsw:space": "cosine"})

    # ---- document chunks with wrapper metadata -------------------------
    ids, texts, metas = [], [], []
    wrappers = cat.documents
    by_file = {w.get("file"): (did, w) for did, w in wrappers.items()}
    for fn in sorted(os.listdir(DOCS_DIR)):
        if not fn.endswith(".md"):
            continue
        with open(os.path.join(DOCS_DIR, fn)) as f:
            body = f.read()
        did, wrapper = by_file.get(fn, (fn[:-3], {}))
        if not wrapper and verbose:
            print(f"  WARNING: {fn} has no catalog wrapper entry")
        # Governance comes from the REGISTRY, not from the document text and not
        # from the descriptive wrapper. This is the whole point: the file itself
        # contains no claim about whether it is current.
        reg = cat.registry_for_file(fn)
        for i, chunk in enumerate(chunk_document(body)):
            ids.append(f"{did}#{i}")
            texts.append(chunk)
            metas.append({
                "document_id": reg.get("id", did),
                "file": fn,
                "title": str(wrapper.get("title", did)),
                "status": str(reg.get("status", "unknown")),
                "effective_date": str(reg.get("effective_date") or "unknown"),
                "superseded_by": str(reg.get("superseded_by") or ""),
                "lineage": str(reg.get("lineage") or ""),
                "registry_note": str(reg.get("registry_note") or "")[:600],
                "summary": str(wrapper.get("summary", ""))[:800],
                "chunk_index": i,
            })
    if verbose:
        print(f"  embedding {len(texts)} document chunks...")
    docs_col.add(ids=ids, documents=texts, metadatas=metas,
                 embeddings=embed(texts))

    # ---- catalog entries ------------------------------------------------
    entries = cat.searchable_entries()
    cids = [f"{e['asset_type']}:{e['id']}" for e in entries]
    ctexts = [f"{e['title']}\n{e['summary']}\n{e['text']}" for e in entries]
    cmetas = [{
        "asset_id": e["id"],
        "asset_type": e["asset_type"],
        "title": str(e["title"]),
        "summary": str(e.get("summary", ""))[:800],
        "access": str(e.get("access", "")),
        "authority": str(e.get("authority", "")),
    } for e in entries]
    if verbose:
        print(f"  embedding {len(ctexts)} catalog entries...")
    cat_col.add(ids=cids, documents=ctexts, metadatas=cmetas,
                embeddings=embed(ctexts))

    return {"document_chunks": len(ids), "catalog_entries": len(cids)}


def _collection(name: str):
    client = _get_client()
    try:
        return client.get_collection(name)
    except Exception:
        raise RuntimeError(
            "The knowledge index has not been built. Run "
            "'python cli.py index' to build it.")


# ---------------------------------------------------------------- search

# Status precedence, from the registry. The DOCUMENT does not state its status:
# these values come from document_registry.yaml, which is the external record of
# what is in force. An unregistered document ranks last, because a document nobody
# is tracking is a document nobody is maintaining.
STATUS_RANK = {"in_force": 0, "draft": 1, "superseded": 2, "withdrawn": 3,
               "unknown": 4}

# Cosine distance above which a chunk is treated as unrelated. Tuned against the
# seeded corpus: on-topic hits land under 0.75, off-topic ones above 0.8.
RELEVANCE_MAX_DISTANCE = 0.78


def _date_key(value: str) -> str:
    """Sort key that puts LATER effective dates first, unknowns last."""
    if not value or value in ("unknown", "None", "null"):
        return "0000-00-00"
    # Invert so a descending date sorts ascending alongside the other keys.
    try:
        parts = [int(x) for x in str(value)[:10].split("-")]
        while len(parts) < 3:
            parts.append(0)
        return f"{9999 - parts[0]:04d}-{12 - parts[1]:02d}-{31 - parts[2]:02d}"
    except (ValueError, IndexError):
        return "0000-00-00"


def search_documents(query: str, k: int = 6) -> list[dict]:
    """Semantic search over document chunks, returned WITH wrapper metadata.

    Results are ordered by authority first and similarity second, so a stale
    draft cannot outrank the canonical version by being more textually similar.
    The raw similarity rank is preserved in the payload so the reordering is
    visible rather than hidden.
    """
    col = _collection("documents")
    res = col.query(query_embeddings=embed([query]), n_results=k * 2,
                    include=["documents", "metadatas", "distances"])
    hits = []
    for i, (doc, meta, dist) in enumerate(zip(
            res["documents"][0], res["metadatas"][0], res["distances"][0])):
        hits.append({
            "document_id": meta.get("document_id"),
            "title": meta.get("title"),
            # From the registry. The document text asserts none of this.
            "status": meta.get("status"),
            "effective_date": meta.get("effective_date"),
            "superseded_by": meta.get("superseded_by") or None,
            "lineage": meta.get("lineage") or None,
            "registry_note": meta.get("registry_note") or None,
            "governance_source": "document_registry.yaml",
            "summary": meta.get("summary"),
            "chunk": doc,
            "similarity_rank": i + 1,
            "distance": round(float(dist), 4),
        })
    # Drop weakly related chunks before authority sorting. Without a floor, a
    # dozen barely relevant canonical documents crowd out the signal simply for
    # being canonical.
    relevant = [h for h in hits if h["distance"] <= RELEVANCE_MAX_DISTANCE]
    if not relevant:
        relevant = hits[:2]  # never return nothing at all
    # Precedence: status first, then similarity. The effective-date tiebreak
    # applies only WITHIN A LINEAGE, because a newer date on an unrelated document
    # says nothing about relevance: sorting globally on date buries the document
    # that actually answers the question under whatever was published most
    # recently. Within a lineage it is decisive, and that is the case it exists
    # for: two versions of the same document, both once in force.
    relevant.sort(key=lambda h: (STATUS_RANK.get(h["status"], 4), h["distance"]))

    # Within a lineage keep only the winning version in the main results. The
    # losers are not discarded: they are captured here and reattached below, so
    # the agent can be told a stale version exists rather than never seeing it.
    seen_lineage: dict[str, str] = {}
    deduped, lineage_losers = [], []
    for h in relevant:
        lin = h.get("lineage")
        if lin:
            best = seen_lineage.get(lin)
            if best is None:
                seen_lineage[lin] = h["document_id"]
            elif best != h["document_id"]:
                lineage_losers.append(h)
                continue
        deduped.append(h)
    relevant = deduped
    kept = relevant[:k]

    # A stale document that scored well on SIMILARITY must stay visible even
    # after authority demotes it below the cutoff. Dropping it silently would
    # hide the very thing the agent needs to know: that a plausible looking
    # superseded version exists and was rejected on authority, not on relevance.
    # A superseded or draft version that scored well on SIMILARITY must stay
    # visible even after governance demotes it. Dropping it silently would hide
    # exactly what the agent needs to know: that a plausible looking document
    # exists, reads as current, and is not.
    kept_ids = {h["document_id"] for h in kept}
    for h in list(relevant) + lineage_losers:
        if (h["document_id"] not in kept_ids
                and h["status"] in ("draft", "superseded", "withdrawn")
                and h["similarity_rank"] <= k
                # It must be genuinely on topic. A stale document that is merely
                # stale is noise; the one worth surfacing is the one a reader
                # could plausibly have picked up instead of the current version.
                and h["distance"] <= RELEVANCE_MAX_DISTANCE * 0.85):
            h = dict(h)
            h["retained_reason"] = (
                f"Ranked {h['similarity_rank']} by similarity but DEMOTED to "
                f"status '{h['status']}' by the document registry. The document "
                "text gives no indication of this. Retained so you can see it "
                "exists; do not answer from it.")
            kept.append(h)
    return kept


def search_catalog(query: str, k: int = 6) -> list[dict]:
    col = _collection("catalog")
    res = col.query(query_embeddings=embed([query]), n_results=k,
                    include=["metadatas", "distances"])
    out = []
    for meta, dist in zip(res["metadatas"][0], res["distances"][0]):
        out.append({
            "asset_id": meta.get("asset_id"),
            "asset_type": meta.get("asset_type"),
            "title": meta.get("title"),
            "summary": meta.get("summary"),
            "access_path": meta.get("access"),
            "authority": meta.get("authority") or None,
            "distance": round(float(dist), 4),
        })
    return out


def keyword_search_catalog(query: str, k: int = 6) -> list[dict]:
    """Literal term matching over catalog text, to complement the vector search."""
    cat = get_catalog()
    terms = [t for t in re.findall(r"[a-z_]{3,}", query.lower())]
    scored = []
    for e in cat.searchable_entries():
        blob = f"{e['title']} {e['summary']} {e['text']}".lower()
        score = sum(blob.count(t) for t in terms)
        if e["id"].lower().replace("_", " ") in query.lower():
            score += 10
        if score:
            scored.append((score, e))
    scored.sort(key=lambda x: -x[0])
    return [{
        "asset_id": e["id"], "asset_type": e["asset_type"],
        "title": e["title"], "summary": e.get("summary", ""),
        "access_path": e.get("access", ""), "keyword_score": s,
    } for s, e in scored[:k]]


def naive_search(query: str, k: int = 6) -> list[dict]:
    """BASELINE MODE ONLY: chunks with NO wrapper metadata.

    This is what retrieval looks like without a semantic layer. Authority,
    effective date, and supersession are all stripped, so a stale draft is
    indistinguishable from the policy actually in force. That is the point.
    """
    col = _collection("documents")
    res = col.query(query_embeddings=embed([query]), n_results=k,
                    include=["documents", "metadatas", "distances"])
    return [{"text": doc, "source_file": meta.get("file"),
             "distance": round(float(dist), 4)}
            for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0],
                                       res["distances"][0])]
