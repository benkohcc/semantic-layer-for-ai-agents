"""Relationships between documents and the things they govern.

WHY THIS EXISTS

Vector similarity answers "what does the corpus SAY about X". It finds passages
that sound like the question. It has no notion of one document governing another,
so it cannot answer "how do things in the corpus RELATE to X":

  - What supersedes the 2024 refund policy?
  - What else changed when the stringing SLA was updated?
  - Which policies apply to racket discounting?
  - If we change the discount rules, what else should we check?

Those are relationship questions. No amount of better embedding reaches them,
because the answer is not in any single passage: it is in how the documents sit
relative to each other.

WHY THERE IS NO CLASSIFIER

The obvious design is a router: read the question, decide similarity or
traversal, run the winner. That design was built and measured, and it does not
work. A keyword ruleset scored 6/15 on realistic phrasings, missing "what's
downstream of the refund policy" because no rule said "downstream", and missing
"what supersedes the 2024 refund policy" despite that being the literal name of
an edge. Keying on entities instead scored 9/15 and failed differently: naming an
entity does not separate "what does the refund policy say" from "what depends on
the refund policy", because both name the same entity.

Both attempts assumed the two searches are alternatives. They are not. Similarity
returns TEXT and traversal returns RELATIONSHIPS, and an answer can carry both
without conflict. Once both always run, there is nothing left to route: you
cannot miss a traversal you always perform, and an unnecessary one costs a few
hops over a few hundred in-memory nodes.

What decides whether relationships appear is therefore not the phrasing but the
graph: if the question names something the graph knows, and that node has edges,
those edges are reported. "What's downstream of the refund policy" works not
because "downstream" was anticipated but because "refund policy" resolves to a
node that has edges.

WHY GOVERNANCE LIVES HERE AND NOT IN THE DOCUMENTS

Same reason as status and effective_date. A document is not a reliable narrator
about its own scope, and nothing in a policy file states which categories it
applies to. Declaring `governs` in the document would reintroduce exactly the
self-declaration problem the registry was built to remove.

COVERAGE, STATED HONESTLY

The derived edges (supersedes, in_lineage, owned_by) come free from registry
fields that already existed. The `governs` edges are authored, and are currently
written for the DISCOUNTING slice only. A document with no `governs` edge is not
reachable by scope traversal; that is a coverage gap, not a claim that it governs
nothing. See coverage() for the live numbers.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REGISTRY = os.path.join(ROOT, "semantic-layer", "domains", "marketing",
                        "catalog", "document_registry.yaml")

# Relationships are reported in this order. Supersession first because it is the
# one that changes whether an answer is correct rather than merely fuller.
EDGE_ORDER = ["superseded_by", "supersedes", "in_lineage", "governs", "owned_by"]

EDGE_MEANING = {
    "supersedes": "replaces an earlier version",
    "superseded_by": "has been replaced by a newer version",
    "in_lineage": "belongs to the same document family",
    "governs": "has authority over this scope",
    "owned_by": "is owned by this team",
}


# ----------------------------------------------------------------- the graph


class KnowledgeGraph:
    """Documents, the scopes they govern, and the edges between them.

    Small enough to hold entirely in memory and rebuild on demand: the registry
    is a single YAML file of a few dozen entries, so there is no cache to go
    stale the way a materialised view would.
    """

    def __init__(self, registry: dict):
        self.registry = registry
        self.docs = {d["id"]: d for d in registry.get("documents", [])}
        self.edges: dict[str, list[tuple[str, str]]] = {}
        self.lexicon: dict[str, tuple[str, str]] = {}
        self._build_edges()
        self._build_lexicon()

    # -- edges ------------------------------------------------------------

    def _add(self, src: str, rel: str, dst: str) -> None:
        self.edges.setdefault(src, [])
        if (rel, dst) not in self.edges[src]:
            self.edges[src].append((rel, dst))

    def _build_edges(self) -> None:
        for did, d in self.docs.items():
            for s in d.get("supersedes") or []:
                self._add(did, "supersedes", s)
                self._add(s, "superseded_by", did)
            if d.get("superseded_by"):
                self._add(did, "superseded_by", d["superseded_by"])
                self._add(d["superseded_by"], "supersedes", did)
            if d.get("lineage"):
                self._add(did, "in_lineage", d["lineage"])
                self._add(d["lineage"], "in_lineage", did)
            if d.get("approved_by"):
                self._add(did, "owned_by", d["approved_by"])
                self._add(d["approved_by"], "owns", did)
            for scope in d.get("governs") or []:
                self._add(did, "governs", scope)
                self._add(scope, "governed_by", did)

    # -- lexicon ----------------------------------------------------------

    def _build_lexicon(self) -> None:
        """Surface forms that resolve to a node.

        This is the part that needs care, and it is deliberately a bounded list
        checked against a known vocabulary rather than an open ended attempt to
        anticipate phrasing. A missing synonym is a visible gap that a test
        catches; a missing phrasing rule is invisible.
        """
        def put(surface: str, kind: str, node: str) -> None:
            s = surface.strip().lower()
            if len(s) > 2:
                self.lexicon.setdefault(s, (kind, node))

        for did, d in self.docs.items():
            put(did.replace("-", " "), "document", did)
            # The same id without a trailing year names the family, not the file.
            base = re.sub(r"[-_ ]?(19|20)\d\d$", "", did)
            if base != did and d.get("lineage"):
                put(base.replace("-", " "), "lineage", d["lineage"])
            if d.get("lineage"):
                put(d["lineage"].replace("-", " "), "lineage", d["lineage"])
            for scope in d.get("governs") or []:
                put(scope, "scope", scope)
            if d.get("approved_by"):
                put(d["approved_by"], "team", d["approved_by"])

        # How people actually refer to these documents. Registry ids are written
        # for filesystem tidiness and nobody says "pricing and discount policy".
        for surface, node in {
            "refund policy": "refund-policy",
            "refund window": "refund-policy",
            "returns policy": "refund-policy",
            "stringing sla": "stringing-sla",
            "turnaround": "stringing-sla",
            "media plan": "media-plan",
            "pricing policy": "pricing-and-discount-policy",
            "discount policy": "pricing-and-discount-policy",
            "discount rules": "pricing-and-discount-policy",
            "discounting": "discounting",
            "loyalty terms": "loyalty-program-terms",
            "competitive landscape": "competitive-landscape",
        }.items():
            kind = ("lineage" if node in {d.get("lineage") for d in self.docs.values()}
                    else "scope" if node == "discounting" else "document")
            self.lexicon[surface] = (kind, node)

        # Singular and plural both resolve, so "racket" and "rackets" behave the
        # same. Only for single word surfaces, where it is unambiguous.
        for surface, node in list(self.lexicon.items()):
            if " " in surface:
                continue
            alt = surface[:-1] if surface.endswith("s") else surface + "s"
            self.lexicon.setdefault(alt, node)

    # -- lookup -----------------------------------------------------------

    def resolve(self, query: str) -> list[tuple[str, str, str]]:
        """Entities this question mentions, as (surface, kind, node).

        Longest match wins, so "pricing policy" is not also reported as the
        scope "pricing" and a question about the "q2 media plan" resolves to
        that document rather than to the media-plan family.
        """
        text = " " + re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", query.lower())) + " "
        found: list[tuple[str, str, str]] = []
        for surface in sorted(self.lexicon, key=len, reverse=True):
            if f" {surface} " not in text:
                continue
            if any(surface in s for s, _, _ in found):
                continue  # already covered by a longer, more specific match
            kind, node = self.lexicon[surface]
            found.append((surface, kind, node))
        return found

    def neighbours(self, node: str) -> list[tuple[str, str]]:
        out = list(self.edges.get(node, []))
        out.sort(key=lambda e: (EDGE_ORDER.index(e[0])
                                if e[0] in EDGE_ORDER else len(EDGE_ORDER), e[1]))
        return out

    def title(self, node: str) -> str:
        d = self.docs.get(node)
        if not d:
            return node
        return d.get("file", node).replace(".md", "").replace("-", " ")

    def related(self, query: str, limit: int = 8) -> dict:
        """Relationships the graph can contribute to this question.

        Returns an empty dict when the question names nothing the graph knows,
        or names something with no edges. An empty result is a normal outcome
        and not a failure: most questions are answered by the text alone.
        """
        resolved = self.resolve(query)
        if not resolved:
            return {}

        # A bare category word is weak evidence. "How long do customers have to
        # return a racket" mentions rackets, but attaching every discounting
        # policy to it is noise: the question is about returns, and the category
        # is incidental. Document and lineage nodes have no such problem, because
        # naming a document is always deliberate.
        #
        # This filters WHICH RESOLVED NODES contribute, not which strategy runs.
        # A category still contributes when the question is about the category
        # itself rather than merely mentioning one.
        scope_words = ("polic", "govern", "appl", "rule", "discount", "approv",
                       "authority", "margin", "who owns", "cover", "allowed",
                       "permitted", "sign off", "change", "audit")
        asks_about_scope = any(w in query.lower() for w in scope_words)
        if not asks_about_scope:
            resolved = [r for r in resolved if r[1] != "scope"]
            if not resolved:
                return {}

        items: list[dict] = []
        for surface, kind, node in resolved:
            for rel, other in self.neighbours(node):
                if len(items) >= limit:
                    break
                entry = {
                    "from": node,
                    "matched_on": surface,
                    "relationship": rel,
                    "to": other,
                    "meaning": EDGE_MEANING.get(rel, rel.replace("_", " ")),
                }
                if other in self.docs:
                    d = self.docs[other]
                    entry["to_status"] = d.get("status")
                    entry["to_effective_date"] = d.get("effective_date")
                    if d.get("registry_note"):
                        entry["why_it_matters"] = d["registry_note"].strip()
                if rel == "governs":
                    note = self.docs.get(node, {}).get("governs_note")
                    if note:
                        entry["scope_note"] = " ".join(note.split())
                items.append(entry)

        if not items:
            return {}

        return {
            "entities_recognised": [
                {"matched_on": s, "kind": k, "node": n} for s, k, n in resolved],
            "relationships": items,
            "source": "document_registry.yaml",
            "how_to_use": (
                "These are RELATIONSHIPS, not answers. Vector search returned the "
                "text above; this section says how those documents relate to each "
                "other and to what they govern. Use it to answer questions "
                "similarity cannot reach: what replaced this, what else is in "
                "this family, which policies apply to a category, who owns it. "
                "A 'superseded_by' edge means the text you are reading may be "
                "out of date even when it reads as current."),
        }

    # -- introspection ----------------------------------------------------

    def coverage(self) -> dict:
        total = len(self.docs)
        with_governs = [d for d in self.docs.values() if d.get("governs")]
        connected = {n for n in self.edges if n in self.docs}
        return {
            "documents": total,
            "reachable_by_any_edge": len(connected),
            "with_authored_governs_edges": len(with_governs),
            "governs_coverage_note": (
                f"`governs` edges are authored for {len(with_governs)} of {total} "
                "documents, currently the discounting slice only. A document "
                "without one is not reachable by scope traversal. That is a "
                "coverage gap, not a claim that it governs nothing."),
        }


@lru_cache(maxsize=1)
def get_graph() -> KnowledgeGraph:
    with open(REGISTRY) as fh:
        return KnowledgeGraph(yaml.safe_load(fh))
