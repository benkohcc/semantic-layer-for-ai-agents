"""The relationship-traversal access path: a CLOSED SET of four operations.

There is no query language here on purpose: an open traversal interface would let
the agent compute whatever it liked, and the whole claim of this access path is
that it can exist without giving up governance.

WHAT EXECUTES THE WALK

Recursive SQL over the warehouse, in place. An earlier version loaded the referral
structure into an in-memory networkx graph at startup; that bought nothing but
convenience and cost a second copy of the data that went stale for the life of the
process and would not survive a warehouse that outgrew memory. The referral
structure is one nullable column (customers.referred_by), single-parent, so every
"chain" is a tree that WITH RECURSIVE walks directly. One store, no snapshot, and
every call reads the warehouse as it is now.

The tool contract is unchanged by that swap, which is the point of an access path:
the same four operations, the same result shapes, the same cohort handles. Nothing
upstream knows the engine changed.

What this module does NOT do, ever: compute a metric. It selects cohorts and
returns customer ids. Turning ids into numbers is the metrics engine's job, and
routing them there is what the playbook enforces.
"""

from __future__ import annotations

import os
from collections import defaultdict

import metrics_engine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MAX_DEPTH_LIMIT = 8

VALID_CHANNELS = "organic, paid_search, paid_social, email, referral"


class GraphError(Exception):
    """Raised with an explanation the agent can act on."""


# ------------------------------------------------------------------ recursion
#
# The shared walk. Chain roots are customers nobody referred who referred at
# least one person; the recursion follows referred_by downward, carrying the
# root and the depth. referred_by is single-parent so the structure is a forest:
# no cycle is possible without a row being its own ancestor, and the depth cap
# bounds the recursion regardless.

_WALK_FROM_ROOTS = """
WITH RECURSIVE walk(root, id, depth) AS (
    SELECT id, id, 0 FROM customers
    WHERE {root_filter}
      AND referred_by IS NULL
      AND EXISTS (SELECT 1 FROM customers r WHERE r.referred_by = customers.id)
    UNION ALL
    SELECT w.root, c.id, w.depth + 1
    FROM customers c JOIN walk w ON c.referred_by = w.id
    WHERE w.depth < :max_depth
)
SELECT root, id, depth FROM walk
"""

_WALK_FROM_ONE = """
WITH RECURSIVE walk(id, depth) AS (
    SELECT :root, 0
    UNION ALL
    SELECT c.id, w.depth + 1
    FROM customers c JOIN walk w ON c.referred_by = w.id
    WHERE w.depth < :max_depth
)
SELECT id, depth FROM walk
"""


# ---------------------------------------------------------------- operations


def referral_chain(root: int | None = None, channel: str | None = None,
                   max_depth: int = 5) -> dict:
    """Walk referral chains from one root, or from every root in a channel."""
    if root is None and channel is None:
        raise GraphError(
            "referral_chain requires either 'root' (a customer id) or 'channel' "
            "(an acquisition channel). Pass one of them in params.")
    max_depth = max(1, min(int(max_depth), MAX_DEPTH_LIMIT))

    with metrics_engine.connect() as conn:
        if root is not None:
            try:
                root = int(root)
            except (TypeError, ValueError):
                raise GraphError(
                    f"'root' must be a numeric customer id, got '{root}'. To ask "
                    "about a whole channel, pass 'channel' instead.")
            if not conn.execute("SELECT 1 FROM customers WHERE id = ?",
                                (root,)).fetchone():
                raise GraphError(f"Customer {root} does not exist.")
            rows = conn.execute(_WALK_FROM_ONE,
                                {"root": root, "max_depth": max_depth}).fetchall()
            walks = [(root, r["id"], r["depth"]) for r in rows]
        else:
            rows = conn.execute(
                _WALK_FROM_ROOTS.format(root_filter="acquisition_channel = :ch"),
                {"ch": channel, "max_depth": max_depth}).fetchall()
            if not rows:
                raise GraphError(
                    f"No chain roots found for channel '{channel}'. Valid "
                    f"channels: {VALID_CHANNELS}.")
            walks = [(r["root"], r["id"], r["depth"]) for r in rows]

        root_ids = {w[0] for w in walks}
        root_channel = {r["id"]: r["acquisition_channel"] for r in conn.execute(
            "SELECT id, acquisition_channel FROM customers WHERE id IN "
            f"({','.join(str(i) for i in root_ids) or 'NULL'})")}

    per_root: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    all_members: set[int] = set()
    for rt, node, depth in walks:
        per_root[rt][depth] += 1
        all_members.add(node)

    chains = []
    for rt, by_depth in per_root.items():
        size = sum(n for d, n in by_depth.items()) - 1  # excludes the root itself
        chains.append({
            "root": rt,
            "root_channel": root_channel.get(rt),
            "chain_size": size,
            "max_depth_reached": max(by_depth),
            "members_by_depth": dict(sorted(by_depth.items())),
        })

    chains.sort(key=lambda c: (-c["max_depth_reached"], -c["chain_size"]))
    return {
        "operation": "referral_chain",
        "roots_examined": len(per_root),
        "max_depth_requested": max_depth,
        "chains": chains[:50],
        "chains_truncated": len(chains) > 50,
        "cohort_customer_ids": sorted(all_members),
        "cohort_size": len(all_members),
    }


def chain_stats(group_by: str = "acquisition_channel") -> dict:
    """Chain depth and size statistics, rolled up by a grouping attribute.

    Depth is measured per CHAIN ROOT and attributed to the root's own attribute,
    which is what makes "which channel produced the best chains" answerable: a
    referred customer's own channel is always 'referral', so grouping on the
    member's channel would be meaningless.
    """
    allowed = {"acquisition_channel", "region", "segment"}
    if group_by not in allowed:
        raise GraphError(
            f"chain_stats cannot group by '{group_by}'. Allowed: "
            f"{', '.join(sorted(allowed))}.")

    # One recursive pass from every chain root, aggregated per root in SQL.
    sql = f"""
    WITH RECURSIVE walk(root, id, depth) AS (
        SELECT id, id, 0 FROM customers
        WHERE referred_by IS NULL
          AND EXISTS (SELECT 1 FROM customers r WHERE r.referred_by = customers.id)
        UNION ALL
        SELECT w.root, c.id, w.depth + 1
        FROM customers c JOIN walk w ON c.referred_by = w.id
        WHERE w.depth < :max_depth
    )
    SELECT cu.{group_by} AS grp,
           w.root        AS root,
           MAX(w.depth)  AS max_depth,
           COUNT(*) - 1  AS size
    FROM walk w JOIN customers cu ON cu.id = w.root
    GROUP BY w.root
    """
    with metrics_engine.connect() as conn:
        rows = conn.execute(sql, {"max_depth": MAX_DEPTH_LIMIT}).fetchall()

    groups: dict[str, dict] = defaultdict(
        lambda: {"roots": 0, "depths": [], "sizes": []})
    for r in rows:
        g = groups[str(r["grp"])]
        g["roots"] += 1
        g["depths"].append(r["max_depth"])
        g["sizes"].append(r["size"])

    out = []
    for key, v in groups.items():
        n = len(v["depths"])
        out.append({
            group_by: key,
            "chain_roots": v["roots"],
            "avg_chain_depth": round(sum(v["depths"]) / n, 3) if n else 0,
            "max_chain_depth": max(v["depths"]) if v["depths"] else 0,
            "avg_chain_size": round(sum(v["sizes"]) / n, 3) if n else 0,
            "total_referred_downstream": sum(v["sizes"]),
        })
    out.sort(key=lambda x: -x["avg_chain_depth"])

    return {
        "operation": "chain_stats",
        "group_by": group_by,
        "stats": out,
        "measurement_note": (
            "Depth is measured per chain ROOT and attributed to the root's own "
            f"{group_by}. A referred customer's own acquisition_channel is always "
            "'referral', so grouping on the member's channel would say nothing "
            "about which channel SEEDED the chain. Depth 1 means the root "
            "referred someone who referred nobody."),
        "ranking_note": (
            "Ranked by average chain depth. Consider avg_chain_size and "
            "total_referred_downstream too: a channel can seed deep but narrow "
            "chains, or shallow but wide ones. 'Best' depends on which you mean."),
    }


def exposed_cohort(edge_type: str = "referred_by",
                   condition: str = "referrer_churned") -> dict:
    """Select customers exposed to a condition THROUGH a relationship.

    Returns the exposed cohort and a comparison cohort, both as id lists, plus
    the temporal-ordering evidence needed to check that the exposure actually
    precedes the outcome.
    """
    if edge_type != "referred_by":
        raise GraphError(
            f"edge_type '{edge_type}' is not registered. Registered edge types: "
            "referred_by.")
    if condition != "referrer_churned":
        raise GraphError(
            f"condition '{condition}' is not registered for edge_type "
            "'referred_by'. Registered conditions: referrer_churned.")

    end = metrics_engine.data_end()
    # Churn mirrors the spine's definition: no completed order in the trailing 12
    # months. It is an INFERENCE from purchase silence, not an observed event,
    # and every answer built on it has to say so.
    sql = """
    WITH active AS (
        SELECT DISTINCT customer_id FROM orders
        WHERE status = 'completed' AND channel != 'wholesale'
          AND order_date >= date(:end, '-12 months') AND order_date <= :end
    )
    SELECT c.id            AS referee,
           c.signup_date   AS referred_on,
           (c.referred_by NOT IN (SELECT customer_id FROM active)) AS exposed
    FROM customers c
    WHERE c.referred_by IS NOT NULL
    """
    with metrics_engine.connect() as conn:
        window_open = conn.execute(
            "SELECT date(?, '-12 months')", (end,)).fetchone()[0]
        rows = conn.execute(sql, {"end": end}).fetchall()

    exposed, comparison = [], []
    ordering_ok = 0
    ordering_violations = 0
    for r in rows:
        if r["exposed"]:
            exposed.append(r["referee"])
            # The churn window opens 12 months before the data end; a referral
            # must predate it for "referred, then the referrer churned" to be
            # the real order of events.
            if r["referred_on"] and r["referred_on"] <= window_open:
                ordering_ok += 1
            else:
                ordering_violations += 1
        else:
            comparison.append(r["referee"])

    return {
        "operation": "exposed_cohort",
        "edge_type": edge_type,
        "condition": condition,
        "exposed_customer_ids": sorted(exposed),
        "exposed_size": len(exposed),
        "comparison_customer_ids": sorted(comparison),
        "comparison_size": len(comparison),
        "comparison_definition": (
            "Customers referred by someone who is NOT inferred-churned. This is "
            "the correct baseline: it holds 'was referred' constant and varies "
            "only the referrer's churn status."),
        "temporal_ordering": {
            "churn_window_opens": window_open,
            "referrals_before_window": ordering_ok,
            "referrals_inside_window": ordering_violations,
            "verdict": (
                "Ordering holds: the referral precedes the churn window for "
                f"{ordering_ok} of {ordering_ok + ordering_violations} exposed "
                "customers, so the referrer churned AFTER referring."
                if ordering_violations * 4 < ordering_ok else
                "Ordering is NOT clean: a material share of referrals fall inside "
                "the churn window, so the direction of the relationship cannot be "
                "asserted from this data."),
        },
        "definition_disclosure": (
            "CHURN HERE IS INFERRED, NOT OBSERVED: a customer with no completed "
            "order in the trailing 12 months is treated as churned. There is no "
            "cancellation event in this business. Any answer built on this cohort "
            "MUST disclose that churn is an inference from purchase silence."),
    }


def trace_cohort(campaign_id: int | None = None, product_id: int | None = None,
                 recalled: bool = False) -> dict:
    """Trace customers from a campaign through to a product purchase.

    Walks campaign -> send -> order -> product, which is the multi hop path a
    single aggregation cannot express, and returns the traced cohort plus a
    matched control that bought a DIFFERENT product in the same category through
    the same campaign.
    """
    if campaign_id is None:
        raise GraphError(
            "trace_cohort requires 'campaign_id'. Optionally pass 'product_id', "
            "or 'recalled': true to trace the recalled product.")

    with metrics_engine.connect() as conn:
        # Accept a campaign NAME as well as an id. Callers naturally pass the name
        # they read in a document ("Spring League Kickoff"), and an int() crash
        # there sent the agent into a long retry loop guessing at parameters.
        camp = None
        try:
            campaign_id = int(campaign_id)
            camp = conn.execute("SELECT * FROM campaigns WHERE id = ?",
                                (campaign_id,)).fetchone()
        except (TypeError, ValueError):
            rows = conn.execute(
                "SELECT * FROM campaigns WHERE name LIKE ?",
                (f"%{campaign_id}%",)).fetchall()
            if len(rows) == 1:
                camp = rows[0]
                campaign_id = camp["id"]
            elif len(rows) > 1:
                names = ", ".join(f"{r['id']}={r['name']}" for r in rows[:8])
                raise GraphError(
                    f"'{campaign_id}' matches {len(rows)} campaigns: {names}. "
                    "Pass the numeric campaign_id of the one you mean.")
            else:
                raise GraphError(
                    f"No campaign matches '{campaign_id}'. Pass a numeric "
                    "campaign_id, or search_knowledge for the campaign to find "
                    "its name, then use the id shown in the campaign reference.")
        if not camp:
            raise GraphError(
                f"Campaign {campaign_id} does not exist. Campaign ids are "
                "integers; use search_knowledge to identify the campaign you "
                "want and pass its id.")

        if recalled and product_id is None:
            row = conn.execute(
                "SELECT id, name, category FROM products WHERE recalled = 1"
            ).fetchone()
            if not row:
                raise GraphError("No recalled product exists in the catalog.")
            product_id, pname, pcat = row["id"], row["name"], row["category"]
        else:
            row = conn.execute(
                "SELECT id, name, category FROM products WHERE id = ?",
                (product_id,)).fetchone()
            if not row:
                raise GraphError(f"Product {product_id} does not exist.")
            product_id, pname, pcat = row["id"], row["name"], row["category"]

        # Hop 1-3: campaign attributed order -> line item -> the product.
        traced = [r[0] for r in conn.execute(
            "SELECT DISTINCT o.customer_id FROM orders o "
            "JOIN order_items i ON i.order_id = o.id "
            "WHERE o.campaign_id = ? AND i.product_id = ? "
            "AND o.status = 'completed' AND o.channel != 'wholesale'",
            (campaign_id, product_id))]

        # Matched control: same campaign, same category, different product, and
        # never bought the traced product through this campaign.
        control = [r[0] for r in conn.execute(
            "SELECT DISTINCT o.customer_id FROM orders o "
            "JOIN order_items i ON i.order_id = o.id "
            "JOIN products p ON p.id = i.product_id "
            "WHERE o.campaign_id = ? AND p.category = ? AND p.id != ? "
            "AND o.status = 'completed' AND o.channel != 'wholesale' "
            "AND o.customer_id NOT IN ("
            "  SELECT DISTINCT o2.customer_id FROM orders o2 "
            "  JOIN order_items i2 ON i2.order_id = o2.id "
            "  WHERE o2.campaign_id = ? AND i2.product_id = ?)",
            (campaign_id, pcat, product_id, campaign_id, product_id))]

        first_purchase = conn.execute(
            "SELECT MIN(o.order_date), MAX(o.order_date) FROM orders o "
            "JOIN order_items i ON i.order_id = o.id "
            "WHERE o.campaign_id = ? AND i.product_id = ? "
            "AND o.status = 'completed'", (campaign_id, product_id)).fetchone()

    out = {
        "operation": "trace_cohort",
        "path": "campaign -> email send / attributed order -> order_items -> product",
        "campaign": {"id": campaign_id, "name": camp["name"],
                     "start": camp["start_date"], "end": camp["end_date"]},
        "product": {"id": product_id, "name": pname, "category": pcat,
                    "recalled": bool(recalled) or None},
        "traced_customer_ids": sorted(traced),
        "traced_size": len(traced),
        "control_customer_ids": sorted(control),
        "control_size": len(control),
        "control_definition": (
            f"Customers who bought a DIFFERENT {pcat} product through the same "
            "campaign and never bought the traced product through it. This holds "
            "campaign exposure and category constant, so the product is the only "
            "thing that varies."),
        "purchase_window": {"first": first_purchase[0], "last": first_purchase[1]},
    }

    if recalled:
        out["recall_boundary_note"] = (
            "Purchases made BEFORE the recall date carry no exposure to the "
            "recall. Any divergence claim must be restricted to behavior AFTER "
            "the recall date, and the recall notice document states that date. "
            "Retrieve it with search_knowledge before asserting a divergence.")
    return out


# ---------------------------------------------------------------- dispatch

OPERATIONS = {
    "referral_chain": referral_chain,
    "chain_stats": chain_stats,
    "exposed_cohort": exposed_cohort,
    "trace_cohort": trace_cohort,
}


def dispatch(operation: str, params: dict | None = None) -> dict:
    fn = OPERATIONS.get(operation)
    if not fn:
        raise GraphError(
            f"'{operation}' is not a registered graph operation. Registered "
            f"operations: {', '.join(sorted(OPERATIONS))}. This is a closed set; "
            "arbitrary traversal is not available.")
    params = dict(params or {})
    import inspect
    allowed = set(inspect.signature(fn).parameters)
    unknown = set(params) - allowed
    if unknown:
        raise GraphError(
            f"Operation '{operation}' does not accept parameter(s) "
            f"{', '.join(sorted(unknown))}. Accepted: {', '.join(sorted(allowed))}.")
    try:
        return fn(**params)
    except GraphError:
        raise
    except Exception as e:
        # Any other failure becomes actionable guidance. A raw traceback tells the
        # caller nothing about what to fix, and an agent facing one retries with
        # random parameter variations instead of correcting the actual problem.
        raise GraphError(
            f"Operation '{operation}' failed on the parameters given "
            f"({params}): {type(e).__name__}: {e}. Accepted parameters: "
            f"{', '.join(sorted(allowed))}. Check the types: campaign_id and "
            "product_id are integers, max_depth is an integer, recalled is a "
            "boolean.") from e


def graph_summary() -> dict:
    sql = """
    WITH RECURSIVE walk(id, depth) AS (
        SELECT id, 0 FROM customers
        WHERE referred_by IS NULL
          AND EXISTS (SELECT 1 FROM customers r WHERE r.referred_by = customers.id)
        UNION ALL
        SELECT c.id, w.depth + 1
        FROM customers c JOIN walk w ON c.referred_by = w.id
        WHERE w.depth < :max_depth
    )
    SELECT MAX(depth) FROM walk
    """
    with metrics_engine.connect() as conn:
        nodes = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        edges = conn.execute(
            "SELECT COUNT(*) FROM customers WHERE referred_by IS NOT NULL"
        ).fetchone()[0]
        max_depth = conn.execute(
            sql, {"max_depth": MAX_DEPTH_LIMIT}).fetchone()[0] or 0
    return {
        "nodes": nodes,
        "referral_edges": edges,
        "customers_in_a_chain": edges,
        "max_depth": max_depth,
    }
