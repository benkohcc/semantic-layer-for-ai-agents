"""Relationship selection: traversal operations wrapped with edge semantics.

Reached through build_audience(operation=..., params=...). A separate
query_graph tool existed until the traversal engine moved into recursive SQL;
after that, "select by relationships" and "select by attributes" were the same
kind of act against the same store, so the two tools merged.

Kept separate from graph.py so the traversal code stays free of presentation
concerns, and separate from tools.py so milestone 1 never imports either.

Like every other tool here, the result carries its meaning: what an edge is, what
the ABSENCE of an edge implies, the known limitations of the relationship data,
and the composition rule that sends cohorts to the metrics engine rather than
letting a number be computed here.
"""

from __future__ import annotations

import graph
from catalog import get_catalog
from graph import GraphError

# Which edge descriptors are relevant to which operation.
OPERATION_EDGES = {
    "referral_chain": ["referred_by"],
    "chain_stats": ["referred_by"],
    "exposed_cohort": ["referred_by"],
    "trace_cohort": ["purchased"],
}

COMPOSITION_RULE = (
    "COMPOSITION RULE: this tool SELECTS COHORTS. It does NOT compute metrics. To "
    "get a rate, a revenue figure, or any measured quantity for a cohort, pass the "
    "cohort's HANDLE to get_metric as the `cohort` parameter, for example "
    "cohort=\"exposed\". The handles for this result are listed under "
    "cohort_handles. A number computed from the id list by any other means is NOT "
    "the governed metric and is not an acceptable answer, even if the arithmetic "
    "is correct.")

# Cohorts here run to thousands of customers. Requiring the agent to echo every
# id back as a tool argument was the original design and it does not survive
# contact with a real cohort: a 3,876 id comparison group is tens of thousands of
# tokens of integers, per call, which is slow enough to time out and invites
# transcription errors. Each cohort is registered under a short handle that
# get_metric resolves server side instead.
_COHORT_REGISTRY: dict[str, list[int]] = {}

# Cohort-bearing result keys, mapped to the handle each one gets.
COHORT_KEYS = {
    "exposed_customer_ids": "exposed",
    "comparison_customer_ids": "comparison",
    "traced_customer_ids": "traced",
    "control_customer_ids": "control",
    "cohort_customer_ids": "cohort",
}

# Above this size the id list is replaced by a sample plus its handle. The full
# list is still reachable through the handle; it just does not belong in the
# transcript.
ID_LIST_INLINE_LIMIT = 60


def resolve_cohort(handle: str) -> list[int] | None:
    """Resolve a registered cohort handle to its customer ids. Used by get_metric."""
    return _COHORT_REGISTRY.get(handle)


def registered_cohorts() -> dict[str, int]:
    """Handle to cohort size, for error messages and debugging."""
    return {k: len(v) for k, v in _COHORT_REGISTRY.items()}


def registered_cohorts_full() -> dict[str, list[int]]:
    """Handle to full id list, so get_metric can detect a partial cohort."""
    return dict(_COHORT_REGISTRY)


def _register_cohorts(result: dict) -> dict:
    """Register every cohort in a result under a handle, and trim long id lists."""
    handles = {}
    for key, handle in COHORT_KEYS.items():
        ids = result.get(key)
        if not isinstance(ids, list):
            continue
        _COHORT_REGISTRY[handle] = list(ids)
        handles[handle] = {
            "size": len(ids),
            "source_field": key,
            "use": f'get_metric(..., cohort="{handle}")',
        }
        if len(ids) > ID_LIST_INLINE_LIMIT:
            # No sample of ids is included, deliberately. An earlier version
            # returned the first 20 as "sample_ids" and the agent passed THOSE to
            # get_metric as if they were the cohort, producing a confident answer
            # off a 20 customer slice. A partial id list is worse than none: it
            # looks like the cohort and is not. The handle is the only affordance.
            result[key] = {
                "cohort_handle": handle,
                "size": len(ids),
                "ids_withheld": True,
                "note": (f"{len(ids)} customer ids are held server side under the "
                         f"handle '{handle}'. Pass cohort=\"{handle}\" to "
                         "get_metric. The ids are deliberately not listed here: "
                         "there is no need to see them, and passing a partial "
                         "list would silently compute the metric on the wrong "
                         "population."),
            }
    if handles:
        result["cohort_handles"] = handles
    return result


def _edge_semantics(operation: str) -> list[dict]:
    """Pull the edge descriptors from the catalog for this operation."""
    cat = get_catalog()
    out = []
    for edge_id in OPERATION_EDGES.get(operation, []):
        desc = cat.edges.get(edge_id)
        if not desc:
            continue
        out.append({
            "edge": edge_id,
            "label": desc.get("label"),
            "directionality": desc.get("directionality"),
            "semantics": desc.get("semantics", {}),
            "known_limitations": desc.get("known_limitations", []),
            "when_to_use": desc.get("when_to_use", []),
            "when_not_to_use": desc.get("when_not_to_use", []),
        })
    return out


def relationship_selection(operation: str, params: dict | None = None) -> dict:
    """Traverse the referral and purchase relationships. Closed operation set."""
    try:
        result = graph.dispatch(operation, params)
    except GraphError as e:
        return {
            "error": str(e),
            "registered_operations": sorted(graph.OPERATIONS),
            "guidance": ("Read the error and correct the call. Do NOT work around "
                         "a rejected operation by computing the answer another "
                         "way; if the operation is not registered, the traversal "
                         "is not available."),
        }

    result = _register_cohorts(result)
    result["interpretation"] = {
        "edge_descriptors": _edge_semantics(operation),
        "composition_rule": COMPOSITION_RULE,
        "framing": [
            "Findings from traversal are CORRELATIONAL. This is observational "
            "data with no experiment behind it, so describe associations, never "
            "causes. 'Referees of churned referrers repeat less often' is "
            "supportable; 'referrer churn causes referee churn' is not.",
            "Compare a cohort only against the matched or non exposed cohort "
            "returned alongside it, never against the overall benchmark band. The "
            "band is computed on the whole population and any narrow cohort will "
            "differ from it for structural reasons.",
        ],
        "access": ("build_audience relationship operations (closed set, "
                   "milestone 2 access path)"),
    }
    return result
