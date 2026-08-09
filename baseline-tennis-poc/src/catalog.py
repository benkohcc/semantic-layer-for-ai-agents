"""Loads the semantic layer content into memory.

Everything the agent is steered by lives in YAML and Markdown under
semantic-layer/. This module reads it and exposes lookups. It contains no
business logic and no definitions of its own: if a rule is not in the content,
it does not exist.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEMANTIC_DIR = os.path.join(ROOT, "semantic-layer")
DOMAIN_DIR = os.path.join(SEMANTIC_DIR, "domains", "marketing")


def _read(path: str) -> str:
    with open(path) as f:
        return f.read()


def _load_yaml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split YAML frontmatter from markdown body."""
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not m:
        return {}, text
    return yaml.safe_load(m.group(1)) or {}, m.group(2).lstrip("\n")


class Catalog:
    """In-memory view of the semantic layer."""

    def __init__(self) -> None:
        self.spine = _load_yaml(os.path.join(SEMANTIC_DIR, "spine", "entities.yaml"))
        self.domain_md = _read(os.path.join(DOMAIN_DIR, "DOMAIN.md"))
        self.ontology = _load_yaml(
            os.path.join(DOMAIN_DIR, "ontology", "concepts.yaml"))
        self.benchmarks = _load_yaml(
            os.path.join(DOMAIN_DIR, "benchmarks", "benchmarks.yaml"))

        self.metrics: dict[str, dict] = {}
        mdir = os.path.join(DOMAIN_DIR, "metrics")
        for fn in sorted(os.listdir(mdir)):
            if fn.endswith((".yaml", ".yml")):
                spec = _load_yaml(os.path.join(mdir, fn))
                if spec.get("id"):
                    self.metrics[spec["id"]] = spec

        self.playbooks: dict[str, dict] = {}
        pdir = os.path.join(DOMAIN_DIR, "playbooks")
        for fn in sorted(os.listdir(pdir)):
            if fn.endswith(".md"):
                fm, body = parse_frontmatter(_read(os.path.join(pdir, fn)))
                key = fm.get("archetype") or fn[:-3]
                self.playbooks[key] = {"frontmatter": fm, "body": body,
                                       "file": fn}

        # Catalog descriptors, keyed by asset id. Each catalog file holds a list
        # under a key matching its own plural noun.
        self.documents: dict[str, dict] = {}
        self.tables: dict[str, dict] = {}
        self.edges: dict[str, dict] = {}
        self.access_paths: dict[str, dict] = {}
        # The document registry: the EXTERNAL record of which document is in
        # force. Documents no longer declare their own status, because real ones
        # do not, so this is the only place that knowledge exists.
        self.doc_registry: dict[str, dict] = {}
        self.precedence_rules: list[dict] = []
        cdir = os.path.join(DOMAIN_DIR, "catalog")
        for fn in sorted(os.listdir(cdir)):
            if not fn.endswith((".yaml", ".yml")):
                continue
            data = _load_yaml(os.path.join(cdir, fn))
            if data.get("registry_version"):
                self.precedence_rules = data.get("precedence_rules") or []
                for entry in data.get("documents") or []:
                    if entry.get("id"):
                        self.doc_registry[entry["id"]] = entry
                continue
            for key, target in (("documents", self.documents),
                                ("tables", self.tables),
                                ("edges", self.edges),
                                ("access_paths", self.access_paths)):
                for entry in data.get(key) or []:
                    if entry.get("id"):
                        target[entry["id"]] = entry

    # ---------------------------------------------------------------- registry

    def registry_for_file(self, filename: str) -> dict:
        """Governance record for a document file, from the registry.

        The document itself says nothing about its status. Everything here comes
        from document_registry.yaml.
        """
        for entry in self.doc_registry.values():
            if entry.get("file") == filename:
                return entry
        return {}

    def registry_for_id(self, doc_id: str) -> dict:
        return self.doc_registry.get(doc_id, {})

    def lineage_siblings(self, doc_id: str) -> list[dict]:
        """Other versions of the same document, newest first."""
        me = self.doc_registry.get(doc_id, {})
        lineage = me.get("lineage")
        if not lineage:
            return []
        sibs = [e for e in self.doc_registry.values()
                if e.get("lineage") == lineage and e.get("id") != doc_id]
        return sorted(sibs, key=lambda e: str(e.get("effective_date") or ""),
                      reverse=True)

    # ---------------------------------------------------------------- metrics

    def metric(self, metric_id: str) -> dict | None:
        return self.metrics.get(metric_id)

    def metric_ids(self) -> list[str]:
        return sorted(self.metrics)

    def list_metrics(self) -> list[dict]:
        out = []
        for mid, spec in sorted(self.metrics.items()):
            d = spec.get("definition", {})
            out.append({
                "metric_id": mid,
                "label": spec.get("label", mid),
                "description": spec.get("one_line", ""),
                "dimensions": d.get("dimensions", []),
                "filters": sorted(d.get("available_filters") or {}),
                "additive": d.get("additive"),
                "direction": spec.get("evaluation", {}).get("direction"),
                "minimum_grain": (d.get("grain") or {}).get("minimum"),
                "supports_cohort_filter": bool(d.get("cohort_filter_supported")),
            })
        return out

    def benchmark_for(self, metric_id: str) -> dict:
        return (self.benchmarks.get("metrics") or {}).get(metric_id, {})

    # -------------------------------------------------------------- playbooks

    def playbook(self, archetype: str) -> dict | None:
        if archetype in self.playbooks:
            return self.playbooks[archetype]
        # Tolerate near-misses so a slightly-off archetype name still resolves.
        norm = archetype.strip().lower().replace("_", "-")
        for key, pb in self.playbooks.items():
            if key.lower() == norm:
                return pb
        return None

    def archetypes(self) -> list[dict]:
        out = []
        for key, pb in sorted(self.playbooks.items()):
            fm = pb["frontmatter"]
            out.append({
                "archetype": key,
                "label": fm.get("label", key),
                "use_when": fm.get("use_when", []),
                "do_not_use_when": fm.get("do_not_use_when", []),
            })
        return out

    # ---------------------------------------------------------------- ontology

    def resolve_concept(self, text: str) -> list[dict]:
        """Match free text against ontology terms. Longest term wins."""
        low = f" {text.lower()} "
        hits: list[dict] = []
        for entry in self.ontology.get("concepts") or []:
            for term in entry.get("terms", []):
                if re.search(rf"(?<![a-z]){re.escape(term.lower())}(?![a-z])", low):
                    hit = {
                        "matched_term": term,
                        "resolves_to": entry.get("resolves_to"),
                        "asset_type": entry.get("asset_type"),
                        "note": entry.get("note"),
                        "routing_note": entry.get("routing_note"),
                        "disclosure_required": entry.get("disclosure_required", False),
                        "status": "available",
                    }
                    # Some concepts need explicit guidance on the SHAPE of the
                    # answer, not just which asset to use. Churn is the case that
                    # matters: without this the agent reads "no churn metric" as
                    # "cannot answer" and declines a question the layer supports
                    # through a disclosed inference.
                    for extra in ("answer_shape", "counts_note", "archetype",
                                  "sub_shape"):
                        if entry.get(extra):
                            hit[extra] = entry[extra]
                    hits.append(hit)
                    break
        return sorted(hits, key=lambda h: -len(h["matched_term"]))

    def resolve_absent_concept(self, text: str) -> list[dict]:
        """Match against DECLARED-ABSENT concepts.

        A hit here is authoritative: the answer is a decline with a reason, not a
        failed search.
        """
        low = f" {text.lower()} "
        hits = []
        for entry in self.ontology.get("absent_concepts") or []:
            for term in entry.get("terms", []):
                if re.search(rf"(?<![a-z]){re.escape(term.lower())}(?![a-z])", low):
                    hits.append({
                        "matched_term": term,
                        "status": entry.get("status"),
                        "response_rule": entry.get("response_rule"),
                        "nearest_available": entry.get("nearest_available", []),
                        "reference": entry.get("resolves_to"),
                    })
                    break
        return hits

    def combination_rules(self) -> list[dict]:
        return self.ontology.get("combination_rules") or []

    def negative_routing_rules(self) -> list[dict]:
        return self.ontology.get("negative_routing_rules") or []

    # ------------------------------------------------------------------ spine

    def shared_definition(self, name: str) -> dict:
        return (self.spine.get("shared_definitions") or {}).get(name, {})

    def absent_data(self) -> list[dict]:
        return self.spine.get("absent_data") or []

    def domain_section(self, heading_contains: str) -> str | None:
        """Pull one section out of DOMAIN.md by heading match."""
        pattern = re.compile(r"^(#{2,3})\s+(.*)$", re.MULTILINE)
        marks = [(m.start(), m.group(1), m.group(2)) for m in
                 pattern.finditer(self.domain_md)]
        for i, (start, level, title) in enumerate(marks):
            if heading_contains.lower() in title.lower():
                end = len(self.domain_md)
                for nxt_start, nxt_level, _ in marks[i + 1:]:
                    if len(nxt_level) <= len(level):
                        end = nxt_start
                        break
                return self.domain_md[start:end].strip()
        return None

    def cannot_answer_section(self) -> str:
        return (self.domain_section("What this layer cannot answer")
                or "See DOMAIN.md")

    # --------------------------------------------------------------- discovery

    def searchable_entries(self) -> list[dict]:
        """Flatten every catalog asset into text records for discover_assets."""
        recs: list[dict] = []
        for mid, spec in self.metrics.items():
            d = spec.get("definition", {})
            rel = spec.get("reliability", {})
            parts = [spec.get("label", mid), spec.get("one_line", ""),
                     d.get("description", "")]
            parts += [str(c) for c in rel.get("cannot_answer", [])]
            parts += [str(c) for c in rel.get("definition_caveats", [])]
            recs.append({
                "id": mid, "asset_type": "metric",
                "title": spec.get("label", mid),
                "summary": spec.get("one_line", ""),
                "text": "\n".join(p for p in parts if p),
                "access": "get_metric",
            })
        for did, doc in self.documents.items():
            parts = [doc.get("title", did), doc.get("summary", "")]
            for k in ("when_to_use", "when_not_to_use"):
                parts += [str(v) for v in (doc.get(k) or [])]
            for k in ("note", "authority_note", "conflict_note", "trap_note",
                      "honesty_note", "analysis_note", "seasonality_note",
                      "diagnosis_note"):
                if doc.get(k):
                    parts.append(str(doc[k]))
            recs.append({
                "id": did, "asset_type": "document",
                "title": doc.get("title", did),
                "summary": doc.get("summary", ""),
                "authority": doc.get("authority"),
                "effective_date": doc.get("effective_date"),
                "text": "\n".join(p for p in parts if p),
                "access": "search_knowledge",
            })
        for tid, tbl in self.tables.items():
            parts = [tid, tbl.get("summary", "")]
            for trap in tbl.get("traps") or []:
                parts.append(f"{trap.get('trap')}: {trap.get('detail')}")
            for gap in tbl.get("coverage_gaps") or []:
                parts.append(f"{gap.get('gap')}: {gap.get('detail')}")
            recs.append({
                "id": tid, "asset_type": "table",
                "title": tid, "summary": tbl.get("summary", ""),
                "text": "\n".join(p for p in parts if p),
                "access": tbl.get("access", "metrics_engine_only"),
            })
        for aid, ap in self.access_paths.items():
            parts = [ap.get("label", aid), ap.get("summary", "")]
            for k in ("answers", "when_not_to_use", "known_limitations"):
                parts += [str(v) for v in (ap.get(k) or [])]
            for k in ("composition_rule", "criteria"):
                if ap.get(k):
                    parts.append(str(ap[k]))
            recs.append({
                "id": aid, "asset_type": "access_path",
                "title": ap.get("label", aid),
                "summary": ap.get("summary", ""),
                "text": "\n".join(p for p in parts if p),
                "access": ap.get("tool", aid),
            })
        for eid, edge in self.edges.items():
            parts = [edge.get("label", eid), edge.get("summary", "")]
            for k in ("when_to_use", "when_not_to_use", "known_limitations"):
                parts += [str(v) for v in (edge.get(k) or [])]
            sem = edge.get("semantics") or {}
            parts += [f"{k}: {v}" for k, v in sem.items()]
            recs.append({
                "id": eid, "asset_type": "graph_edge",
                "title": edge.get("label", eid),
                "summary": edge.get("summary", ""),
                "text": "\n".join(p for p in parts if p),
                "access": "build_audience (relationship operations)",
            })
        return recs


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    return Catalog()
