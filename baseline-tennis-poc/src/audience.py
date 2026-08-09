"""Affinity and audience selection: the two access paths targeting questions need.

A marketer asks two shapes of question the metrics engine cannot serve:

  "What do racket buyers also buy?"        -> co-purchase affinity
  "Who should I send this promotion to?"   -> audience selection

Neither is an aggregation over a dimension, which is why they fell through before.
Affinity is a co-occurrence rate across baskets; audience selection is a set of
customers matching behavioural criteria.

Like the graph path, this is a CLOSED operation set and it NEVER computes a
governed metric. Audiences are returned as cohort handles so their value can be
measured through get_metric, and so a 900 customer list never has to be pasted
back as a tool argument.
"""

from __future__ import annotations

import metrics_engine

MARKETING = "o.status = 'completed' AND o.channel != 'wholesale'"


class AudienceError(Exception):
    """Raised with an explanation the agent can act on."""


VALID_CATEGORIES = {"rackets", "strings", "shoes", "apparel", "services"}
VALID_SEGMENTS = {"competitive", "recreational"}
VALID_REGIONS = {"northeast", "southeast", "midwest", "west"}
VALID_RACKET_TYPES = {"power", "control", "balanced"}
VALID_TIERS = {"entry", "mid", "premium"}

# Audiences above this size are returned as a handle plus a count rather than a
# list, for the same reason graph cohorts are: the ids are not useful in the
# transcript and pasting a partial list silently measures the wrong population.
INLINE_LIMIT = 60


def _validate(name: str, value, allowed: set, label: str) -> None:
    if value is not None and value not in allowed:
        raise AudienceError(
            f"'{value}' is not a valid {label}. Valid values: "
            f"{', '.join(sorted(allowed))}.")


# ---------------------------------------------------------------- affinity


def category_affinity(category: str | None = None, segment: str | None = None,
                      period: str | None = "trailing_12m") -> dict:
    """What else do buyers of a category buy? Co-purchase rates across customers.

    Measured at the CUSTOMER level, not the basket level: "racket buyers also buy
    apparel" means the same person bought both at some point, which is what a
    cross-sell decision actually rests on. Basket level co-occurrence would be a
    different and much smaller number.
    """
    _validate("category", category, VALID_CATEGORIES, "category")
    _validate("segment", segment, VALID_SEGMENTS, "segment")
    if not category:
        raise AudienceError(
            "category_affinity requires 'category'. Valid values: "
            f"{', '.join(sorted(VALID_CATEGORIES))}.")

    pi = metrics_engine.resolve_period(period)
    seg_clause = " AND c.segment = ?" if segment else ""
    seg_params = [segment] if segment else []

    with metrics_engine.connect() as conn:
        base = conn.execute(f"""
            SELECT COUNT(DISTINCT o.customer_id) n FROM orders o
            JOIN customers c ON c.id = o.customer_id
            JOIN order_items i ON i.order_id = o.id
            JOIN products p ON p.id = i.product_id
            WHERE {MARKETING} AND p.category = ?
              AND o.order_date BETWEEN ? AND ?{seg_clause}""",
            (category, pi["start"], pi["end"], *seg_params)).fetchone()["n"]
        if not base:
            raise AudienceError(
                f"No buyers of '{category}' found in {pi['label']}"
                + (f" for the {segment} segment." if segment else "."))

        rows = conn.execute(f"""
            WITH buyers AS (
              SELECT DISTINCT o.customer_id cid FROM orders o
              JOIN customers c ON c.id = o.customer_id
              JOIN order_items i ON i.order_id = o.id
              JOIN products p ON p.id = i.product_id
              WHERE {MARKETING} AND p.category = ?
                AND o.order_date BETWEEN ? AND ?{seg_clause})
            SELECT p.category cat, COUNT(DISTINCT o.customer_id) n
            FROM orders o JOIN order_items i ON i.order_id = o.id
            JOIN products p ON p.id = i.product_id
            WHERE {MARKETING} AND o.customer_id IN (SELECT cid FROM buyers)
              AND p.category != ? AND o.order_date BETWEEN ? AND ?
            GROUP BY 1 ORDER BY 2 DESC""",
            (category, pi["start"], pi["end"], *seg_params,
             category, pi["start"], pi["end"])).fetchall()

        # Base rate for lift: what share of ALL buyers buy each category anyway.
        overall = {r["cat"]: r["n"] for r in conn.execute(f"""
            SELECT p.category cat, COUNT(DISTINCT o.customer_id) n
            FROM orders o JOIN order_items i ON i.order_id = o.id
            JOIN products p ON p.id = i.product_id
            WHERE {MARKETING} AND o.order_date BETWEEN ? AND ?
            GROUP BY 1""", (pi["start"], pi["end"])).fetchall()}
        all_buyers = conn.execute(f"""
            SELECT COUNT(DISTINCT o.customer_id) n FROM orders o
            WHERE {MARKETING} AND o.order_date BETWEEN ? AND ?""",
            (pi["start"], pi["end"])).fetchone()["n"] or 1

    affinities = []
    for r in rows:
        share = r["n"] / base
        base_rate = overall.get(r["cat"], 0) / all_buyers
        affinities.append({
            "category": r["cat"],
            "buyers_also_buying": r["n"],
            "share_of_cohort": round(share, 4),
            "population_base_rate": round(base_rate, 4),
            # Lift above 1 means this pairing is stronger than chance.
            "lift": round(share / base_rate, 3) if base_rate else None,
        })

    return {
        "operation": "category_affinity",
        "anchor_category": category,
        "segment": segment or "all",
        "period": pi["label"],
        "anchor_buyers": base,
        "affinities": affinities,
        "interpretation": {
            "how_to_read": (
                "share_of_cohort is the share of anchor category buyers who also "
                "bought that category. LIFT compares it to the rate among all "
                "buyers: lift above 1 means the pairing is stronger than chance, "
                "and lift near 1 means the category is simply popular with "
                "everyone and is not a real affinity."),
            "caveats": [
                "CUSTOMER level co-purchase, not basket level. These customers "
                "bought both at some point, not necessarily in the same order, so "
                "this supports a cross-sell CAMPAIGN rather than a bundle.",
                "Correlational. A high pairing does not mean promoting one causes "
                "the other to sell.",
                "Popular categories look affine to everything. Read lift, not "
                "share, before acting.",
            ],
            "composition_rule": (
                "This operation returns rates, not a governed metric. To measure "
                "what a product or category cohort is WORTH, build an audience "
                "with build_audience and pass its handle to get_metric."),
        },
    }


# ---------------------------------------------------------------- audiences

_REGISTRY: dict[str, list[int]] = {}

CRITERIA_DOC = {
    "bought_category": "customers who bought this category in the window",
    "not_bought_category": "customers who did NOT buy this category in the window",
    "bought_racket_type": "customers who bought a power, control or balanced racket",
    "segment": "restrict to competitive or recreational",
    "region": "restrict to one region",
    "price_tier": "customers who bought at this price tier",
    "lapsed_category_months": (
        "customers whose most recent purchase in the anchor category is older "
        "than N months, the 'due for a replacement' shape"),
    "active_only": (
        "restrict to customers with a completed order in the trailing 12 months, "
        "i.e. not inferred churned"),
    "inferred_churned_only": (
        "restrict to customers with NO completed order in the trailing 12 months. "
        "Churn here is INFERRED from purchase silence, never observed"),
    "min_orders": "customers with at least N completed orders in the window",
}


def build_audience(bought_category: str | None = None,
                   not_bought_category: str | None = None,
                   bought_racket_type: str | None = None,
                   segment: str | None = None, region: str | None = None,
                   price_tier: str | None = None,
                   lapsed_category_months: int | None = None,
                   active_only: bool = False,
                   inferred_churned_only: bool = False,
                   min_orders: int | None = None,
                   handle: str = "audience",
                   period: str | None = "all_time") -> dict:
    """Select a customer audience by behaviour. Returns a cohort HANDLE and a count.

    This is the "who should I send this to" path. It selects people; it never
    computes what they are worth. Pass the returned handle to get_metric for that.
    """
    _validate("bought_category", bought_category, VALID_CATEGORIES, "category")
    _validate("not_bought_category", not_bought_category, VALID_CATEGORIES,
              "category")
    _validate("bought_racket_type", bought_racket_type, VALID_RACKET_TYPES,
              "racket type")
    _validate("segment", segment, VALID_SEGMENTS, "segment")
    _validate("region", region, VALID_REGIONS, "region")
    _validate("price_tier", price_tier, VALID_TIERS, "price tier")
    if active_only and inferred_churned_only:
        raise AudienceError(
            "active_only and inferred_churned_only are mutually exclusive: a "
            "customer cannot be both active and inferred churned.")
    if not any([bought_category, not_bought_category, bought_racket_type, segment,
                region, price_tier, lapsed_category_months, active_only,
                inferred_churned_only, min_orders]):
        raise AudienceError(
            "build_audience needs at least one criterion, otherwise it would "
            "select the entire customer base. Available criteria: "
            + "; ".join(f"{k} ({v})" for k, v in CRITERIA_DOC.items()))

    pi = metrics_engine.resolve_period(period)
    end = pi["end"]
    where = ["1=1"]
    params: list = []
    applied: list[str] = []

    if segment:
        where.append("cu.segment = ?")
        params.append(segment)
        applied.append(f"segment = {segment}")
    if region:
        where.append("cu.region = ?")
        params.append(region)
        applied.append(f"region = {region}")

    def bought_clause(cat=None, rtype=None, tier=None) -> tuple[str, list]:
        conds, ps = [f"{MARKETING}"], []
        if cat:
            conds.append("p.category = ?")
            ps.append(cat)
        if rtype:
            conds.append("p.racket_type = ?")
            ps.append(rtype)
        if tier:
            conds.append("p.price_tier = ?")
            ps.append(tier)
        conds.append("o.order_date BETWEEN ? AND ?")
        ps += [pi["start"], end]
        return (" SELECT DISTINCT o.customer_id FROM orders o"
                " JOIN order_items i ON i.order_id = o.id"
                " JOIN products p ON p.id = i.product_id"
                f" WHERE {' AND '.join(conds)}"), ps

    if bought_category or bought_racket_type or price_tier:
        sub, ps = bought_clause(bought_category, bought_racket_type, price_tier)
        where.append(f"cu.id IN ({sub})")
        params += ps
        bits = [b for b in (bought_category, bought_racket_type, price_tier) if b]
        applied.append("bought " + " / ".join(bits))
    if not_bought_category:
        sub, ps = bought_clause(not_bought_category)
        where.append(f"cu.id NOT IN ({sub})")
        params += ps
        applied.append(f"never bought {not_bought_category}")
    if lapsed_category_months:
        cat = bought_category or "rackets"
        sub, ps = bought_clause(cat)
        where.append(
            f"cu.id NOT IN (SELECT o.customer_id FROM orders o"
            f" JOIN order_items i ON i.order_id = o.id"
            f" JOIN products p ON p.id = i.product_id"
            f" WHERE {MARKETING} AND p.category = ?"
            f" AND o.order_date > date(?, '-{int(lapsed_category_months)} months'))")
        params += [cat, end]
        applied.append(f"no {cat} purchase in {lapsed_category_months} months")
    if active_only:
        where.append(
            f"cu.id IN (SELECT o.customer_id FROM orders o WHERE {MARKETING}"
            f" AND o.order_date >= date(?, '-12 months')"
            f" AND o.order_date <= ?)")
        params += [end, end]
        applied.append("active in the trailing 12 months")
    if inferred_churned_only:
        where.append(
            f"cu.id NOT IN (SELECT o.customer_id FROM orders o WHERE {MARKETING}"
            f" AND o.order_date >= date(?, '-12 months')"
            f" AND o.order_date <= ?)")
        params += [end, end]
        applied.append("inferred churned (no order in trailing 12 months)")
    if min_orders:
        where.append(
            f"(SELECT COUNT(*) FROM orders o WHERE o.customer_id = cu.id"
            f" AND {MARKETING} AND o.order_date BETWEEN ? AND ?) >= ?")
        params += [pi["start"], end, int(min_orders)]
        applied.append(f"at least {min_orders} orders")

    sql = (f"SELECT cu.id FROM customers cu WHERE {' AND '.join(where)}"
           f" ORDER BY cu.id")
    with metrics_engine.connect() as conn:
        ids = [r[0] for r in conn.execute(sql, params).fetchall()]

    _REGISTRY[handle] = ids
    out = {
        "operation": "build_audience",
        "audience_handle": handle,
        "size": len(ids),
        "criteria_applied": applied,
        "period": pi["label"],
        "use": f'get_metric(..., cohort="{handle}") to measure this audience',
    }
    if len(ids) <= INLINE_LIMIT:
        out["customer_ids"] = ids
    else:
        out["ids_withheld"] = True
        out["note"] = (
            f"{len(ids)} customer ids are held server side under the handle "
            f"'{handle}'. Pass cohort=\"{handle}\" to get_metric. The ids are "
            "deliberately not listed: passing a partial list would silently "
            "measure the wrong population.")

    out["interpretation"] = {
        "no_pii": (
            "NO CONTACT DETAILS EXIST in this warehouse, by design. This returns "
            "customer ids and a count. It cannot return email addresses, names, or "
            "phone numbers, and there is no export path. Hand the audience "
            "definition to the ESP; do not attempt to assemble a contact list "
            "here."),
        "next_step": (
            "Measure the audience before acting on it: pass the handle to "
            "get_metric with segment_ltv or repeat_purchase_rate to see whether "
            "it is worth targeting, and compare against a sensible baseline "
            "audience rather than the overall benchmark band."),
        "caveats": [
            "Selection is based on RECORDED PURCHASES only. A customer who bought "
            "elsewhere looks like a non buyer here.",
            "An audience is a description of past behaviour, NOT a propensity "
            "score. This layer does not predict who will buy; it says who did "
            "what. Do not present an audience as a likelihood to purchase.",
        ],
    }
    if inferred_churned_only or lapsed_category_months:
        out["interpretation"]["inferred_churn_disclosure"] = (
            "Churn and lapse here are INFERRED from purchase silence, not "
            "observed. There is no cancellation event in retail. A customer who "
            "simply had no need is indistinguishable from one who left, and any "
            "answer built on this audience must say so.")
    return out


def resolve_audience(handle: str) -> list[int] | None:
    return _REGISTRY.get(handle)


def registered_audiences() -> dict[str, int]:
    return {k: len(v) for k, v in _REGISTRY.items()}


def registered_audiences_full() -> dict[str, list[int]]:
    return dict(_REGISTRY)


# ---------------------------------------------------------------- dispatch

OPERATIONS = {
    "category_affinity": category_affinity,
    "build_audience": build_audience,
}


def dispatch(operation: str, params: dict | None = None) -> dict:
    fn = OPERATIONS.get(operation)
    if not fn:
        raise AudienceError(
            f"'{operation}' is not a registered operation. Registered: "
            f"{', '.join(sorted(OPERATIONS))}. This is a closed set.")
    import inspect
    allowed = set(inspect.signature(fn).parameters)
    unknown = set(params or {}) - allowed
    if unknown:
        raise AudienceError(
            f"Operation '{operation}' does not accept parameter(s) "
            f"{', '.join(sorted(unknown))}. Accepted: "
            f"{', '.join(sorted(allowed))}.")
    try:
        return fn(**(params or {}))
    except AudienceError:
        raise
    except Exception as e:
        raise AudienceError(
            f"Operation '{operation}' failed on {params}: {type(e).__name__}: "
            f"{e}. Accepted parameters: {', '.join(sorted(allowed))}.") from e
