"""Tool implementations. One implementation, two surfaces.

mcp_server.py wraps these for Claude Desktop and Claude Code; agent.py calls the
same functions for the eval harness. Nothing here knows which surface it is
serving, so the eval measures the same code path the demo uses.

Every tool returns plain dicts and lists, ready to serialize.
"""

from __future__ import annotations

import os

import interpretation
import knowledge_graph
import metrics_engine
import retrieval
from catalog import get_catalog
from metrics_engine import MetricError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------- orientation


def get_started() -> dict:
    """Domain overview, archetypes, and available metrics. Cheap orientation."""
    cat = get_catalog()
    return {
        "domain": "Baseline Tennis Co. marketing",
        "domain_overview": cat.domain_md,
        "archetypes": cat.archetypes(),
        "metrics": cat.list_metrics(),
        "combination_rules": [
            {"rule": r.get("rule"), "statement": r.get("statement"),
             "application": r.get("application")}
            for r in cat.combination_rules()
        ],
        "negative_routing_rules": [
            {"rule": r.get("rule"), "statement": r.get("statement")}
            for r in cat.negative_routing_rules()
        ],
        "how_to_proceed": (
            "Classify the question into an archetype, call get_playbook for it, "
            "then follow the playbook step by step. Resolve every number through "
            "get_metric. Never estimate a number the tools did not return."),
    }


def list_metrics() -> dict:
    cat = get_catalog()
    return {"metrics": cat.list_metrics(),
            "note": ("Call get_metric with a metric_id from this list. "
                     "Dimensions outside the allowed set are rejected with an "
                     "explanation.")}


def get_playbook(archetype: str) -> dict:
    cat = get_catalog()
    pb = cat.playbook(archetype)
    if not pb:
        return {
            "error": f"No playbook is registered for archetype '{archetype}'.",
            "available_archetypes": [a["archetype"] for a in cat.archetypes()],
            "guidance": ("Pick the closest archetype from the available list. If "
                         "none fits, the question may be outside this domain."),
        }
    fm = pb["frontmatter"]
    return {
        "archetype": fm.get("archetype", archetype),
        "label": fm.get("label"),
        "use_when": fm.get("use_when", []),
        "do_not_use_when": fm.get("do_not_use_when", []),
        "required_tools": fm.get("required_tools", []),
        "playbook": pb["body"],
        "instruction": ("Follow these steps in order. Do not skip steps, and do "
                        "not substitute your own procedure."),
    }


# ---------------------------------------------------------------- discovery


def discover_assets(query: str, limit: int = 6) -> dict:
    """Semantic plus keyword search over catalog entries.

    A query matching a DECLARED-ABSENT concept returns the authoritative decline
    from DOMAIN.md as the primary hit, so 'what is our NPS' resolves to "we do
    not have that, and here is why" instead of an empty result the agent is
    tempted to fill in from its own knowledge.
    """
    cat = get_catalog()
    absent = cat.resolve_absent_concept(query)
    out: dict = {"query": query}

    if absent:
        out["known_gap"] = {
            "matched": [a["matched_term"] for a in absent],
            "status": absent[0]["status"],
            "response_rule": absent[0]["response_rule"],
            "nearest_available": absent[0]["nearest_available"],
            "domain_reference": cat.cannot_answer_section(),
            "instruction": (
                "This query matches a concept the layer DECLARES IT DOES NOT "
                "HAVE. This is an authoritative answer, not a search failure. "
                "Do not keep searching for it, and do not substitute a nearby "
                "metric presented as the thing that was asked for. Follow the "
                "response_rule."),
        }

    concepts = cat.resolve_concept(query)
    if concepts:
        out["ontology_matches"] = concepts[:5]

    try:
        out["semantic_hits"] = retrieval.search_catalog(query, k=limit)
    except Exception as e:
        out["semantic_hits"] = []
        out["semantic_search_error"] = str(e)
    out["keyword_hits"] = retrieval.keyword_search_catalog(query, k=limit)
    return out


def search_knowledge(query: str, limit: int = 6) -> dict:
    """Document chunks with GOVERNANCE from the registry, not from the text.

    Ordered by status, then effective date, then similarity. The documents make no
    claim about their own currency, which is the point: that knowledge lives in
    document_registry.yaml, and supplying it is the layer's job.
    """
    cat = get_catalog()
    absent = cat.resolve_absent_concept(query)
    out: dict = {"query": query}
    if absent:
        out["known_gap"] = {
            "status": absent[0]["status"],
            "response_rule": absent[0]["response_rule"],
            "nearest_available": absent[0]["nearest_available"],
            "instruction": ("This concept is declared absent. Retrieval returning "
                            "nothing relevant is expected and is not a search "
                            "failure."),
        }
    try:
        hits = retrieval.search_documents(query, k=limit)
    except Exception as e:
        return {**out, "error": str(e),
                "hint": "Run 'python cli.py index' to build the knowledge index."}

    out["hits"] = hits

    # Relationships, always attempted, never routed to. Similarity answers what
    # the corpus SAYS; this answers how documents RELATE. They are different
    # kinds of result rather than competing strategies, so both run and the
    # payload reports what each contributed. See knowledge_graph.py for why
    # there is no classifier here.
    related = knowledge_graph.get_graph().related(query)
    out["retrieval"] = {
        "text_search": f"{len(hits)} chunk(s) by vector similarity, reranked by "
                       "the registry",
        "relationship_search": (
            f"{len(related['relationships'])} relationship(s) from the document "
            "graph" if related else
            "no relationships: the question named nothing the graph knows, or "
            "what it named has no edges"),
        "note": ("Both always run. Relationships are reported alongside the text "
                 "rather than instead of it, so nothing here depends on the "
                 "question being phrased in a relational way."),
    }
    if related:
        out["related"] = related

    statuses = {h["status"] for h in hits}
    out["governance_guidance"] = (
        "IMPORTANT: the documents themselves say NOTHING about whether they are "
        "current. Real documents do not: a policy written in 2024 was simply the "
        "policy, and nobody went back to stamp it when the replacement landed. "
        "Every 'status' and 'effective_date' here comes from the document "
        "registry, which is the external record of what is in force.\n\n"
        "Results are ordered by STATUS (in_force > draft > superseded), then by "
        "EFFECTIVE DATE with later winning, then by similarity. Answer from the "
        "in_force document. similarity_rank shows the original vector ranking so "
        "you can see where governance overrode relevance.\n\n"
        "Do NOT try to judge currency by reading the document. You cannot, and "
        "the text will often read as though it is current, because it was when "
        "it was written.")

    # A policy answer without its effective date is not verifiable, and the date
    # is right here in the payload. Naming the specific date makes citing it the
    # obvious move rather than something to remember from the playbook.
    dated = [h for h in hits
             if h["status"] == "in_force"
             and h.get("effective_date") not in (None, "", "unknown", "current")]
    if dated:
        top = dated[0]
        out["cite_this"] = {
            "document": top["title"],
            "effective_date": top["effective_date"],
            "instruction": (
                f"State that this answer comes from '{top['title']}', effective "
                f"{top['effective_date']}. A policy answer without its effective "
                "date cannot be verified by the reader."),
        }
    if {"superseded", "draft", "withdrawn"} & statuses:
        stale = [{"title": h["title"], "status": h["status"],
                  "effective_date": h["effective_date"],
                  "superseded_by": h.get("superseded_by"),
                  "why": h.get("registry_note")}
                 for h in hits
                 if h["status"] in ("superseded", "draft", "withdrawn")]
        out["stale_versions_present"] = {
            "documents": stale,
            "instruction": (
                "A superseded or draft document surfaced and it reads exactly "
                "like a current one, because nothing in its text admits "
                "otherwise. Do NOT answer from it. Say it exists, say what "
                "period it covers, and say it is not in force, so the reader "
                "knows it was considered rather than missed."),
        }
    return out


# ---------------------------------------------------------------- metrics


def _all_registered_cohorts() -> dict[str, list[int]]:
    """Every registered cohort, from any selection path (graph or audience)."""
    out: dict[str, list[int]] = {}
    for mod in ("graph_tools", "audience"):
        try:
            m = __import__(mod)
        except ImportError:
            continue
        getter = getattr(m, "registered_cohorts_full", None) or \
            getattr(m, "registered_audiences_full", None)
        if getter:
            out.update(getter())
    return out


def _resolve_cohort_arg(cohort):
    """Accept either an explicit id list or a handle from any selection path.

    Handles exist because a real cohort is thousands of ids and echoing them back
    as a tool argument is slow enough to time out. Both forms are accepted; the
    handle is the ergonomic one. Graph cohorts and built audiences share one
    namespace, so get_metric does not care which path selected the population.
    """
    if cohort is None:
        return None, None
    registry = _all_registered_cohorts()
    if isinstance(cohort, list):
        # Guard against a PARTIAL cohort. If the list is a strict subset of a
        # registered cohort, the caller almost certainly pasted an excerpt rather
        # than the whole population, and the metric would be computed on the wrong
        # denominator while looking perfectly plausible.
        given = set(int(x) for x in cohort)
        for handle, ids in registry.items():
            full = set(ids)
            if given and given < full and len(given) < len(full) * 0.9:
                return None, (
                    f"The {len(given)} ids passed are a SUBSET of the registered "
                    f"cohort '{handle}', which has {len(full)} customers. This "
                    "would compute the metric on part of the cohort and report it "
                    f"as the whole. Pass cohort=\"{handle}\" instead, which "
                    "resolves the full population server side.")
        return cohort, None
    if isinstance(cohort, str):
        ids = registry.get(cohort)
        if ids is None:
            return None, (
                f"Unknown cohort handle '{cohort}'. "
                + ("Registered handles: "
                   + ", ".join(f"{k} ({len(v)} customers)"
                               for k, v in registry.items()) + ". "
                   if registry else
                   "No cohorts have been selected yet. ")
                + "Select a population first: query_graph for relationship "
                  "cohorts, or build_audience for behavioural ones. Each returns "
                  "the handle to pass here.")
        return ids, None
    return None, (f"cohort must be a list of customer ids or a handle string, "
                  f"got {type(cohort).__name__}.")


def get_metric(metric_id: str, dimensions: list[str] | None = None,
               period: str | None = None, filters: dict | None = None,
               cohort: list[int] | str | None = None) -> dict:
    """Compute a governed metric and return it with the full semantic payload."""
    cohort_ids, cohort_err = _resolve_cohort_arg(cohort)
    if cohort_err:
        return {"error": cohort_err, "metric_id": metric_id,
                "guidance": ("Correct the cohort argument and call again. Do not "
                             "compute the cohort metric another way.")}
    cohort_label = cohort if isinstance(cohort, str) else None
    try:
        raw = metrics_engine.compute(metric_id, dimensions, period, filters,
                                     cohort_ids)
    except MetricError as e:
        cat = get_catalog()
        return {
            "error": str(e),
            "metric_id": metric_id,
            "available_metrics": cat.metric_ids(),
            "guidance": ("Read the error, correct the request, and call again. "
                         "Do not work around a rejected dimension by computing "
                         "the number another way."),
        }
    if cohort_label:
        raw["cohort_handle"] = cohort_label
    return interpretation.interpret(raw)


# ---------------------------------------------------------------- baseline mode
# These two exist ONLY in --baseline mode, to demonstrate what the agent does
# without a semantic layer. They are never registered on the semantic server.


BASELINE_SCHEMA = """
customers(id, segment, region, signup_date, acquisition_channel, referred_by)
products(id, category, name, price, recalled)
orders(id, customer_id, order_date, gross_amount, refund_amount, channel, status, campaign_id)
order_items(order_id, product_id, quantity, unit_price)
campaigns(id, name, type, start_date, end_date, channel, budget)
email_sends(id, campaign_id, customer_id, send_date, delivered, opened, machine_opened, clicked, email_type)
ad_spend(date, channel, spend, clicks, attributed_signups)
"""


def run_sql(query: str, limit: int = 200) -> dict:
    """BASELINE MODE ONLY. Raw read-only SQL against the warehouse."""
    q = query.strip().rstrip(";")
    lowered = q.lower()
    if not lowered.startswith(("select", "with")):
        return {"error": "Only SELECT and WITH queries are permitted."}
    for banned in ("attach", "pragma", "insert", "update", "delete", "drop",
                   "create", "alter"):
        if f" {banned} " in f" {lowered} ":
            return {"error": f"'{banned}' is not permitted."}
    try:
        with metrics_engine.connect() as conn:
            rows = conn.execute(q).fetchmany(limit)
            cols = [d[0] for d in conn.execute(q).description]
    except Exception as e:
        return {"error": f"SQL error: {e}", "schema": BASELINE_SCHEMA}
    return {"columns": cols,
            "rows": [dict(zip(cols, tuple(r))) for r in rows],
            "row_count": len(rows),
            "truncated": len(rows) >= limit}


def naive_search(query: str, limit: int = 6) -> dict:
    """BASELINE MODE ONLY. Vector search with no wrapper metadata at all."""
    try:
        return {"results": retrieval.naive_search(query, k=limit)}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------- registry
# Used by cli.py 'tool' subcommand and by the eval agent.

def search_campaigns(query: str | None = None, segment: str | None = None,
                     category: str | None = None, channel: str | None = None,
                     campaign_type: str | None = None,
                     period: str | None = None, limit: int = 12) -> dict:
    """Search campaign BRIEFS: why each ran, who it targeted, what was learned."""
    import campaigns
    try:
        return campaigns.search_campaigns(query, segment, category, channel,
                                          campaign_type, period, limit)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def campaign_detail(campaign_id: int) -> dict:
    """Full brief for one campaign, plus delivery context."""
    import campaigns
    try:
        return campaigns.campaign_detail(campaign_id)
    except Exception as e:
        return {"error": str(e)}


def category_affinity(category: str | None = None, segment: str | None = None,
                      period: str | None = "trailing_12m") -> dict:
    """What else do buyers of a category buy? Cross-sell affinity with lift."""
    import audience
    try:
        return audience.category_affinity(category, segment, period)
    except audience.AudienceError as e:
        return {"error": str(e),
                "guidance": "Correct the parameters and call again."}


def build_audience(**kwargs) -> dict:
    """Select WHICH customers, by attributes or by relationships.

    Attribute mode filters the customer base. Relationship mode (operation= plus
    params=) runs one of the four closed traversal operations. Both return cohort
    handles for get_metric; neither computes a number.
    """
    import audience
    operation = kwargs.pop("operation", None)
    params = kwargs.pop("params", None)
    if operation is not None:
        filters = {k: v for k, v in kwargs.items()
                   if v not in (None, False) and k not in ("handle", "period")}
        if filters:
            return {"error": (
                "Pass EITHER attribute criteria OR a relationship operation, not "
                f"both. Got operation='{operation}' alongside "
                f"{sorted(filters)}. Relationship operations define their own "
                "population; run them alone, then measure with get_metric."),
                "guidance": "Drop one of the two selection modes and call again."}
        import graph_tools
        return graph_tools.relationship_selection(operation, params)
    if params is not None:
        return {"error": (
            "'params' only accompanies 'operation' (relationship mode). For "
            "attribute selection, pass the criteria as top-level arguments."),
            "guidance": "Either add an operation or move the criteria up."}
    try:
        return audience.dispatch("build_audience", kwargs)
    except audience.AudienceError as e:
        return {"error": str(e), "available_criteria": audience.CRITERIA_DOC,
                "guidance": ("Correct the criteria and call again. Do not build "
                             "the audience by another means.")}


SEMANTIC_TOOLS = {
    "get_started": get_started,
    "list_metrics": list_metrics,
    "get_playbook": get_playbook,
    "discover_assets": discover_assets,
    "search_knowledge": search_knowledge,
    "get_metric": get_metric,
    "search_campaigns": search_campaigns,
    "category_affinity": category_affinity,
    "build_audience": build_audience,
}

BASELINE_TOOLS = {
    "run_sql": run_sql,
    "naive_search": naive_search,
}


def all_tools(enable_graph: bool = False, baseline: bool = False) -> dict:
    # Relationship operations live inside build_audience; enable_graph gates
    # whether they execute (the server wrapper declines them when disabled), so
    # the tool SET no longer changes with the flag.
    if baseline:
        return dict(BASELINE_TOOLS)
    return dict(SEMANTIC_TOOLS)
