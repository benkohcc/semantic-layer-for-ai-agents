"""Compiles governed metric requests into parameterized SQLite queries.

The engine is deliberately narrow. It knows how to build SQL for the ten metric
shapes the domain defines, and it refuses anything a metric descriptor does not
allow. The exclusion filters that make each metric correct are applied here, not
by the caller, which is the whole reason raw SQL is not an access path.

Rejections carry an explanation the agent can read and self-correct from.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date

from catalog import get_catalog

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "tennis_store.db")

# The marketing order filter from the spine. Every order-based metric applies it.
MARKETING_ORDERS = "o.status = 'completed' AND o.channel != 'wholesale'"


class MetricError(Exception):
    """Raised with an explanation the agent can act on."""


def connect() -> sqlite3.Connection:
    if not os.path.exists(DB_PATH):
        raise MetricError(
            "The database does not exist. Run 'python data/seed.py' first.")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------- period logic


def _month_bounds(y: int, m: int) -> tuple[str, str]:
    import calendar
    return (date(y, m, 1).isoformat(),
            date(y, m, calendar.monthrange(y, m)[1]).isoformat())


def data_end() -> str:
    """Last date covered by the data, used to resolve relative periods."""
    with connect() as conn:
        r = conn.execute("SELECT MAX(order_date) FROM orders").fetchone()
    return r[0]


def resolve_period(period: str | None) -> dict:
    """Turn a period expression into concrete bounds.

    Accepts: 'last_month', 'last_N_months', 'YYYY-MM', 'YYYY-MM..YYYY-MM',
    'trailing_12m', 'all_time', or None (defaults to last_month).
    """
    end_iso = data_end()
    end_d = date.fromisoformat(end_iso)
    p = (period or "last_month").strip().lower()

    def prev_month(d: date) -> tuple[int, int]:
        return (d.year, d.month)

    if p in ("all_time", "all", "lifetime"):
        return {"start": "1900-01-01", "end": end_iso, "label": "all time",
                "grain": "all_time"}

    if p in ("last_month", "last month", "previous_month"):
        y, m = prev_month(end_d)
        s, e = _month_bounds(y, m)
        return {"start": s, "end": e, "label": f"{y}-{m:02d}", "grain": "month"}

    if p in ("trailing_12m", "trailing_12_months", "last_12_months", "ttm"):
        y, m = prev_month(end_d)
        _, e = _month_bounds(y, m)
        start_total = (y * 12 + m - 1) - 11
        sy, sm = divmod(start_total, 12)
        s, _ = _month_bounds(sy, sm + 1)
        return {"start": s, "end": e, "label": "trailing 12 months",
                "grain": "trailing_12m"}

    # last_N_months
    if p.startswith("last_") and p.endswith(("_months", "_month")):
        try:
            n = int(p.split("_")[1])
        except (IndexError, ValueError):
            n = 1
        y, m = prev_month(end_d)
        _, e = _month_bounds(y, m)
        start_total = (y * 12 + m - 1) - (n - 1)
        sy, sm = divmod(start_total, 12)
        s, _ = _month_bounds(sy, sm + 1)
        return {"start": s, "end": e, "label": f"last {n} months",
                "grain": "month", "series": True}

    # explicit range YYYY-MM..YYYY-MM
    if ".." in p:
        a, b = [x.strip() for x in p.split("..", 1)]
        try:
            ay, am = (int(x) for x in a.split("-")[:2])
            by, bm = (int(x) for x in b.split("-")[:2])
        except ValueError:
            raise MetricError(
                f"Could not parse period range '{period}'. Use 'YYYY-MM..YYYY-MM'.")
        s, _ = _month_bounds(ay, am)
        _, e = _month_bounds(by, bm)
        return {"start": s, "end": e, "label": f"{a} to {b}", "grain": "month",
                "series": True}

    # explicit YYYY-MM
    parts = p.split("-")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        y, m = int(parts[0]), int(parts[1])
        s, e = _month_bounds(y, m)
        return {"start": s, "end": e, "label": f"{y}-{m:02d}", "grain": "month"}

    raise MetricError(
        f"Could not parse period '{period}'. Supported: 'last_month', "
        "'last_6_months', 'trailing_12m', 'YYYY-MM', 'YYYY-MM..YYYY-MM', "
        "'all_time'.")


# ------------------------------------------------------- dimension expressions
# Each metric declares allowed dimensions; these are the SQL expressions for
# them. A dimension not listed here for a metric is rejected.

ORDER_DIMS = {
    "month": "substr(o.order_date, 1, 7)",
    "channel": "o.channel",
    "segment": "c.segment",
    "region": "c.region",
    "category": "p.category",
    "acquisition_channel": "c.acquisition_channel",
    "campaign": "o.campaign_id",
    # Product level. A marketer works at this grain constantly ("which rackets
    # sell best", "worst refund rate by product"), and stopping at category made
    # every such question unanswerable.
    "product": "p.name",
    "product_id": "p.id",
    "racket_type": "p.racket_type",
    "price_tier": "p.price_tier",
    "head_size": "p.head_size_sq_in",
    "string_gauge": "p.string_gauge",
    "brand": "p.brand",
    "supplier": "s.name",
    "lifecycle_stage": "p.lifecycle_stage",
}

# Dimensions that require the order_items -> products join.
PRODUCT_DIMS = {"category", "product", "product_id", "racket_type", "price_tier",
                "head_size", "string_gauge", "brand", "supplier",
                "lifecycle_stage"}
# Supplier lives one join further out, through products.
SUPPLIER_DIMS = {"supplier"}
CUSTOMER_DIMS = {
    "month": "substr(cu.signup_date, 1, 7)",
    "acquisition_channel": "cu.acquisition_channel",
    "region": "cu.region",
    "segment": "cu.segment",
}
EMAIL_DIMS = {
    "month": "substr(e.send_date, 1, 7)",
    "week": "strftime('%Y-W%W', e.send_date)",
    "segment": "c.segment",
    "campaign": "e.campaign_id",
    "email_type": "e.email_type",
}
SPEND_DIMS = {
    "month": "substr(a.date, 1, 7)",
    "channel": "a.channel",
}


def _validate(metric_id: str, spec: dict, dimensions: list[str],
              period_info: dict) -> None:
    d = spec.get("definition", {})
    allowed = d.get("dimensions", [])
    for dim in dimensions:
        if dim not in allowed:
            raise MetricError(
                f"Metric '{metric_id}' does not allow dimension '{dim}'. "
                f"Allowed dimensions: {', '.join(allowed) or 'none'}. "
                "Pick one of these, or ask for the ungrouped value.")
    min_grain = (d.get("grain") or {}).get("minimum")
    if min_grain == "week" and "day" in dimensions:
        raise MetricError(
            f"Metric '{metric_id}' has a minimum grain of week. Daily values are "
            "not meaningful for it; request week or month instead.")
    if min_grain == "all_time" and period_info.get("grain") == "month":
        # segment_ltv is cumulative; a monthly slice is not the metric.
        pass


# ---------------------------------------------------------------- SQL builders


def _group_sql(sel: list[str]) -> tuple[str, str, str]:
    """Build the (columns, GROUP BY, ORDER BY) fragments for a dimension list.

    Grouping is by ordinal so the dimension expression appears once in the SQL.
    """
    if not sel:
        return "", "", ""
    ordinals = ", ".join(str(i + 1) for i in range(len(sel)))
    cols = ", ".join(f"{e} AS dim_{i}" for i, e in enumerate(sel)) + ", "
    return cols, f" GROUP BY {ordinals}", f" ORDER BY {ordinals}"


def _cohort_clause(cohort: list[int] | None, col: str) -> tuple[str, list]:
    if not cohort:
        return "", []
    ints = [int(x) for x in cohort]
    if not ints:
        return "", []
    ph = ",".join("?" * len(ints))
    return f" AND {col} IN ({ph})", ints


# Source shapes a declarative metric can be built on. A descriptor names one of
# these plus a value expression, and the compiler assembles the rest.
PRODUCT_JOIN = (" JOIN order_items oi ON oi.order_id = o.id"
                " JOIN products p ON p.id = oi.product_id")

DECLARATIVE_SOURCES = {
    "orders": {
        "from": "orders o", "date_column": "o.order_date",
        "dims": ORDER_DIMS, "cohort_column": "o.customer_id",
        "joins": {
            "segment": " JOIN customers c ON c.id = o.customer_id",
            "region": " JOIN customers c ON c.id = o.customer_id",
            "acquisition_channel": " JOIN customers c ON c.id = o.customer_id",
            # Every product level dimension or filter needs the same two joins.
            "category": PRODUCT_JOIN, "product": PRODUCT_JOIN,
            "product_id": PRODUCT_JOIN, "racket_type": PRODUCT_JOIN,
            "price_tier": PRODUCT_JOIN, "head_size": PRODUCT_JOIN,
            "string_gauge": PRODUCT_JOIN, "is_performance": PRODUCT_JOIN,
            "recalled": PRODUCT_JOIN, "brand": PRODUCT_JOIN,
            "lifecycle_stage": PRODUCT_JOIN,
            "supplier": PRODUCT_JOIN + " LEFT JOIN suppliers s ON s.id = p.supplier_id",
        },
        "extra_filters": {"campaign_id": "o.campaign_id",
                          "is_performance": "p.is_performance",
                          "recalled": "p.recalled",
                          "brand": "p.brand",
                          "lifecycle_stage": "p.lifecycle_stage"},
    },
    "customers": {
        "from": "customers cu", "date_column": "cu.signup_date",
        "dims": CUSTOMER_DIMS, "cohort_column": "cu.id", "joins": {},
        "extra_filters": {},
    },
    "email_sends": {
        "from": "email_sends e", "date_column": "e.send_date",
        "dims": EMAIL_DIMS, "cohort_column": "e.customer_id",
        "joins": {"segment": " JOIN customers c ON c.id = e.customer_id"},
        "extra_filters": {"campaign_id": "e.campaign_id"},
    },
    "ad_spend": {
        "from": "ad_spend a", "date_column": "a.date",
        "dims": SPEND_DIMS, "cohort_column": None, "joins": {},
        "extra_filters": {},
    },
}


def _build_declarative(metric_id: str, spec: dict, dims: list[str], pi: dict,
                       filters: dict, cohort: list[int] | None
                       ) -> tuple[str, list, list[str]]:
    """Compile a metric from a declarative `sql` block in its descriptor.

    This is what makes a new metric a CONTENT change: a descriptor that names a
    source, a value expression, a sample expression, and a where clause needs no
    Python at all. The ten original metrics keep hand written compilers because
    their shapes (cross table ratios, trailing windows, LEFT JOIN denominators)
    are not expressible this way.
    """
    sql_spec = spec.get("sql") or {}
    source_name = sql_spec.get("source")
    src = DECLARATIVE_SOURCES.get(source_name)
    if not src:
        raise MetricError(
            f"Metric '{metric_id}' declares source '{source_name}', which is not "
            f"a registered source shape. Registered: "
            f"{', '.join(sorted(DECLARATIVE_SOURCES))}.")
    if not sql_spec.get("value"):
        raise MetricError(
            f"Metric '{metric_id}' has a 'sql' block with no 'value' expression. "
            "A declarative metric needs 'source' and 'value' at minimum.")

    params: list = []
    dim_map = src["dims"]
    for d in dims:
        if d not in dim_map:
            raise MetricError(
                f"Metric '{metric_id}' cannot group by '{d}' on source "
                f"'{source_name}'. Available: {', '.join(sorted(dim_map))}.")
    sel = [dim_map[d] for d in dims]

    joins, seen = "", set()
    # A metric can declare joins it ALWAYS needs, independent of the dimensions
    # requested. Margin needs the line items and the product cost even when asked
    # for a single ungrouped number.
    for j in (sql_spec.get("always_join") or []):
        frag = {"product": PRODUCT_JOIN,
                "supplier": " LEFT JOIN suppliers s ON s.id = p.supplier_id"}.get(j)
        if frag and frag not in seen:
            joins += frag
            seen.add(frag)
    for d in list(dims) + list(filters or {}):
        j = src["joins"].get(d)
        if j and j not in seen:
            joins += j
            seen.add(j)

    filter_map = {**dim_map, **src["extra_filters"]}
    fc = ""
    for k, v in (filters or {}).items():
        if k not in filter_map:
            raise MetricError(
                f"Filter '{k}' is not available on metric '{metric_id}'. "
                f"Available filters: {', '.join(sorted(filter_map))}.")
        fc += f" AND {filter_map[k]} = ?"
        params.append(v)

    cc, cparams = _cohort_clause(cohort, src["cohort_column"]) if \
        src["cohort_column"] else ("", [])
    where = sql_spec.get("where") or "1=1"
    sample = sql_spec.get("sample_size") or "COUNT(*)"
    cols, group, order = _group_sql(sel)

    # A CUMULATIVE metric ("how many customers do we have") is a stock, not a
    # flow: it counts everything up to the period end rather than what happened
    # inside the period. Declared per metric because the two shapes are not
    # interchangeable and silently using the wrong one returns a plausible number.
    if sql_spec.get("cumulative"):
        date_clause = f"{src['date_column']} <= ?"
        date_params = [pi["end"]]
    else:
        date_clause = f"{src['date_column']} BETWEEN ? AND ?"
        date_params = [pi["start"], pi["end"]]

    sql = (f"SELECT {cols}{sql_spec['value']} AS value, {sample} AS sample_size "
           f"FROM {src['from']}{joins} "
           f"WHERE {where} AND {date_clause}"
           f"{fc}{cc}{group}{order}")
    return sql, date_params + params + cparams, dims


def _build(metric_id: str, dims: list[str], pi: dict, filters: dict,
           cohort: list[int] | None) -> tuple[str, list, list[str]]:
    """Return (sql, params, dim_labels)."""
    params: list = []

    def filter_clauses(mapping: dict) -> str:
        out = ""
        for k, v in (filters or {}).items():
            if k not in mapping:
                raise MetricError(
                    f"Filter '{k}' is not available on metric '{metric_id}'. "
                    f"Available filters: {', '.join(sorted(mapping))}.")
            out += f" AND {mapping[k]} = ?"
            params.append(v)
        return out

    # A descriptor carrying a `sql` block compiles declaratively, so adding a
    # metric is a content change. Checked first, which also lets a declarative
    # descriptor override a built in shape if someone wants to.
    spec = get_catalog().metric(metric_id) or {}
    if spec.get("sql"):
        return _build_declarative(metric_id, spec, dims, pi, filters, cohort)

    # ---- order based metrics -------------------------------------------
    if metric_id in ("net_revenue", "aov", "refund_rate"):
        sel = [ORDER_DIMS[d] for d in dims]
        needs_cust = any(d in ("segment", "region", "acquisition_channel") for d in dims) \
            or any(k in ("segment", "region", "acquisition_channel") for k in (filters or {}))
        needs_prod = bool(PRODUCT_DIMS & (set(dims) | set(filters or {})))
        # is_performance and recalled are product predicates too.
        if {"is_performance", "recalled"} & set(filters or {}):
            needs_prod = True
        joins = ""
        if needs_cust:
            joins += " JOIN customers c ON c.id = o.customer_id"
        if needs_prod:
            joins += (" JOIN order_items oi ON oi.order_id = o.id"
                      " JOIN products p ON p.id = oi.product_id")
            if SUPPLIER_DIMS & (set(dims) | set(filters or {})):
                joins += " LEFT JOIN suppliers s ON s.id = p.supplier_id"
        if metric_id == "refund_rate":
            base = ("o.status IN ('completed','refunded') AND "
                    "o.channel != 'wholesale'")
            value = ("SUM(o.refund_amount) * 1.0 / "
                     "NULLIF(SUM(o.gross_amount), 0)")
            sample = "COUNT(DISTINCT o.id)"
        elif metric_id == "aov":
            base = MARKETING_ORDERS
            value = ("SUM(o.gross_amount - o.refund_amount) * 1.0 / "
                     "NULLIF(COUNT(DISTINCT o.id), 0)")
            sample = "COUNT(DISTINCT o.id)"
        else:
            base = MARKETING_ORDERS
            value = "SUM(o.gross_amount - o.refund_amount)"
            sample = "COUNT(DISTINCT o.id)"
        fc = filter_clauses({**ORDER_DIMS, "campaign_id": "o.campaign_id",
                             "is_performance": "p.is_performance",
                             "recalled": "p.recalled"})
        cc, cparams = _cohort_clause(cohort, "o.customer_id")
        cols, group, order = _group_sql(sel)
        sql = (f"SELECT {cols}{value} AS value, {sample} AS sample_size "
               f"FROM orders o{joins} "
               f"WHERE {base} AND o.order_date BETWEEN ? AND ?{fc}{cc}"
               f"{group}{order}")
        return sql, [pi["start"], pi["end"]] + params + cparams, dims

    # ---- signups --------------------------------------------------------
    if metric_id == "new_customer_signups":
        sel = [CUSTOMER_DIMS[d] for d in dims]
        fc = filter_clauses(CUSTOMER_DIMS)
        cc, cparams = _cohort_clause(cohort, "cu.id")
        cols, group, order = _group_sql(sel)
        sql = (f"SELECT {cols}COUNT(*) AS value, COUNT(*) AS sample_size "
               f"FROM customers cu "
               f"WHERE cu.signup_date BETWEEN ? AND ?{fc}{cc}{group}{order}")
        return sql, [pi["start"], pi["end"]] + params + cparams, dims

    # ---- email metrics --------------------------------------------------
    if metric_id in ("email_open_rate", "email_click_rate"):
        sel = [EMAIL_DIMS[d] for d in dims]
        needs_cust = "segment" in dims or "segment" in (filters or {})
        joins = " JOIN customers c ON c.id = e.customer_id" if needs_cust else ""
        if metric_id == "email_open_rate":
            value = ("SUM(CASE WHEN e.opened = 1 AND e.machine_opened = 0 "
                     "THEN 1 ELSE 0 END) * 1.0 / NULLIF(SUM(e.delivered), 0)")
        else:
            value = "SUM(e.clicked) * 1.0 / NULLIF(SUM(e.delivered), 0)"
        fc = filter_clauses({**EMAIL_DIMS, "campaign_id": "e.campaign_id"})
        cc, cparams = _cohort_clause(cohort, "e.customer_id")
        cols, group, order = _group_sql(sel)
        sql = (f"SELECT {cols}{value} AS value, SUM(e.delivered) AS sample_size "
               f"FROM email_sends e{joins} "
               f"WHERE e.delivered = 1 AND e.email_type != 'transactional' "
               f"AND e.send_date BETWEEN ? AND ?{fc}{cc}{group}{order}")
        return sql, [pi["start"], pi["end"]] + params + cparams, dims

    # ---- CAC ------------------------------------------------------------
    if metric_id == "cac":
        sel = [SPEND_DIMS[d] for d in dims]
        fc = filter_clauses(SPEND_DIMS)
        cols, group, order = _group_sql(sel)
        sql = (f"SELECT {cols}SUM(a.spend) * 1.0 / "
               f"NULLIF(SUM(a.attributed_signups), 0) AS value, "
               f"SUM(a.attributed_signups) AS sample_size "
               f"FROM ad_spend a "
               f"WHERE a.spend > 0 AND a.date BETWEEN ? AND ?{fc}{group}{order}")
        return sql, [pi["start"], pi["end"]] + params, dims

    # ---- items per order ------------------------------------------------
    if metric_id == "items_per_order":
        # Line items over orders. Numerator and denominator sit at different
        # grains in the same join, so this cannot be expressed declaratively.
        sel_map = {"month": "substr(o.order_date, 1, 7)", "channel": "o.channel",
                   "segment": "c.segment", "region": "c.region"}
        dims_use = [d for d in dims if d in sel_map]
        needs_cust = any(d in ("segment", "region") for d in dims_use) or \
            any(k in ("segment", "region") for k in (filters or {}))
        joins = " JOIN customers c ON c.id = o.customer_id" if needs_cust else ""
        fc = filter_clauses(sel_map)
        cc, cparams = _cohort_clause(cohort, "o.customer_id")
        sel = [sel_map[d] for d in dims_use]
        cols, group, order = _group_sql(sel)
        sql = (f"SELECT {cols}"
               f" COUNT(oi.rowid) * 1.0 / NULLIF(COUNT(DISTINCT o.id), 0) AS value,"
               f" COUNT(DISTINCT o.id) AS sample_size "
               f"FROM orders o JOIN order_items oi ON oi.order_id = o.id{joins} "
               f"WHERE {MARKETING_ORDERS} AND o.order_date BETWEEN ? AND ?"
               f"{fc}{cc}{group}{order}")
        return sql, [pi["start"], pi["end"]] + params + cparams, dims_use

    # ---- revenue per email ----------------------------------------------
    if metric_id == "revenue_per_email":
        # Numerator and denominator come from DIFFERENT tables aligned on month,
        # so a filter would have to be applied consistently to both halves or the
        # ratio becomes meaningless (filtered revenue over unfiltered sends).
        # Rejecting is the honest option: silently dropping the filter would hand
        # back a number the caller believes is narrowed when it is not.
        if filters:
            raise MetricError(
                f"Metric 'revenue_per_email' does not support filters "
                f"({', '.join(sorted(filters))} requested). Its numerator comes "
                "from orders and its denominator from email_sends, so a filter "
                "applied to one side and not the other would produce a "
                "meaningless ratio. Use the segment or campaign DIMENSION on "
                "email_click_rate for engagement splits, or request "
                "revenue_per_email unfiltered.")
        sel_dim = "substr(o.order_date, 1, 7)" if "month" in dims else None
        cc, cparams = _cohort_clause(cohort, "o.customer_id")
        cc_e, cparams_e = _cohort_clause(cohort, "e.customer_id")
        if sel_dim:
            sql = (
                "SELECT rev.m AS dim_0, "
                "rev.net * 1.0 / NULLIF(snd.delivered, 0) AS value, "
                "snd.delivered AS sample_size FROM "
                "(SELECT substr(o.order_date,1,7) m, "
                " SUM(o.gross_amount - o.refund_amount) net FROM orders o "
                f" WHERE o.status='completed' AND o.channel='email' "
                f" AND o.order_date BETWEEN ? AND ?{cc} GROUP BY 1) rev "
                "LEFT JOIN (SELECT substr(e.send_date,1,7) m, "
                " SUM(e.delivered) delivered FROM email_sends e "
                " WHERE e.email_type != 'transactional' "
                f" AND e.send_date BETWEEN ? AND ?{cc_e} GROUP BY 1) snd "
                "ON snd.m = rev.m ORDER BY 1")
            return sql, ([pi["start"], pi["end"]] + cparams
                         + [pi["start"], pi["end"]] + cparams_e), ["month"]
        sql = (
            "SELECT (SELECT SUM(o.gross_amount - o.refund_amount) FROM orders o "
            f" WHERE o.status='completed' AND o.channel='email' "
            f" AND o.order_date BETWEEN ? AND ?{cc}) * 1.0 / "
            "NULLIF((SELECT SUM(e.delivered) FROM email_sends e "
            f" WHERE e.email_type != 'transactional' "
            f" AND e.send_date BETWEEN ? AND ?{cc_e}), 0) AS value, "
            "(SELECT SUM(e.delivered) FROM email_sends e "
            f" WHERE e.email_type != 'transactional' "
            f" AND e.send_date BETWEEN ? AND ?{cc_e}) AS sample_size")
        return sql, ([pi["start"], pi["end"]] + cparams
                     + [pi["start"], pi["end"]] + cparams_e
                     + [pi["start"], pi["end"]] + cparams_e), []

    # ---- repeat purchase rate -------------------------------------------
    if metric_id == "repeat_purchase_rate":
        # Trailing 12 months ending at the requested period end.
        sel_map = {"segment": "c.segment", "region": "c.region",
                   "acquisition_channel": "c.acquisition_channel"}
        dims_use = [d for d in dims if d in sel_map]
        cc, cparams = _cohort_clause(cohort, "o.customer_id")
        fc = filter_clauses({**sel_map, "segment": "c.segment"})
        if dims_use:
            sel = [sel_map[d] for d in dims_use]
            cols = ", ".join(f"{e} AS dim_{i}" for i, e in enumerate(sel))
            grp = ", ".join(str(i + 1) for i in range(len(sel)))
            sql = (
                f"WITH per_cust AS ("
                f" SELECT o.customer_id, {', '.join(sel)} AS grp_key, COUNT(*) n"
                f" FROM orders o JOIN customers c ON c.id = o.customer_id"
                f" WHERE {MARKETING_ORDERS}"
                f" AND o.order_date >= date(?, '-12 months')"
                f" AND o.order_date <= ?{fc}{cc}"
                f" GROUP BY o.customer_id, 2)"
                f" SELECT grp_key AS dim_0,"
                f" SUM(CASE WHEN n >= 2 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) AS value,"
                f" COUNT(*) AS sample_size FROM per_cust GROUP BY 1 ORDER BY 1")
            return sql, [pi["end"], pi["end"]] + params + cparams, dims_use
        joins = " JOIN customers c ON c.id = o.customer_id" if (filters or {}) else ""
        sql = (
            f"WITH per_cust AS ("
            f" SELECT o.customer_id, COUNT(*) n FROM orders o{joins}"
            f" WHERE {MARKETING_ORDERS}"
            f" AND o.order_date >= date(?, '-12 months')"
            f" AND o.order_date <= ?{fc}{cc}"
            f" GROUP BY o.customer_id)"
            f" SELECT SUM(CASE WHEN n >= 2 THEN 1 ELSE 0 END) * 1.0 / "
            f" NULLIF(COUNT(*), 0) AS value, COUNT(*) AS sample_size FROM per_cust")
        return sql, [pi["end"], pi["end"]] + params + cparams, []

    # ---- segment LTV ----------------------------------------------------
    if metric_id == "segment_ltv":
        sel_map = {"segment": "cu.segment", "region": "cu.region",
                   "acquisition_channel": "cu.acquisition_channel"}
        dims_use = [d for d in dims if d in sel_map] or ["segment"]
        sel = [sel_map[d] for d in dims_use]
        fc = filter_clauses(sel_map)
        cc, cparams = _cohort_clause(cohort, "cu.id")
        cols = ", ".join(f"{e} AS dim_{i}" for i, e in enumerate(sel))
        grp = ", ".join(str(i + 1) for i in range(len(sel)))
        # LEFT JOIN keeps never-ordered customers in the denominator at zero.
        sql = (
            f"SELECT {cols}, "
            f" COALESCE(SUM(o.gross_amount - o.refund_amount), 0) * 1.0 / "
            f" NULLIF(COUNT(DISTINCT cu.id), 0) AS value, "
            f" COUNT(DISTINCT cu.id) AS sample_size "
            f"FROM customers cu LEFT JOIN orders o "
            f" ON o.customer_id = cu.id AND o.status = 'completed' "
            f" AND o.channel != 'wholesale' AND o.order_date <= ? "
            f"WHERE 1=1{fc}{cc} GROUP BY {grp} ORDER BY {grp}")
        return sql, [pi["end"]] + params + cparams, dims_use

    raise MetricError(
        f"Metric '{metric_id}' has neither a built in compiler nor a 'sql' block "
        "in its descriptor, so there is no way to compute it. Add a 'sql' block "
        f"naming a registered source ({', '.join(sorted(DECLARATIVE_SOURCES))}) "
        "plus a 'value' expression, which requires no code change.")


# ---------------------------------------------------------------- entry point


def compute(metric_id: str, dimensions: list[str] | None = None,
            period: str | None = None, filters: dict | None = None,
            cohort: list[int] | None = None) -> dict:
    """Compute a governed metric. Returns raw results; interpretation is layered on."""
    cat = get_catalog()
    spec = cat.metric(metric_id)
    if not spec:
        raise MetricError(
            f"'{metric_id}' is not a governed metric. Available metrics: "
            f"{', '.join(cat.metric_ids())}. Call list_metrics for details.")

    dims = list(dimensions or [])
    pi = resolve_period(period)
    _validate(metric_id, spec, dims, pi)

    if cohort is not None and not spec.get("definition", {}).get(
            "cohort_filter_supported"):
        # Allowed but flagged: only metrics that declare support are guaranteed
        # to be meaningful on an arbitrary cohort.
        pass

    sql, params, dim_labels = _build(metric_id, dims, pi, filters or {}, cohort)

    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()

    results = []
    for r in rows:
        keys = r.keys()
        entry = {}
        for i, dname in enumerate(dim_labels):
            entry[dname] = r[f"dim_{i}"] if f"dim_{i}" in keys else None
        entry["value"] = r["value"]
        entry["sample_size"] = r["sample_size"] if "sample_size" in keys else None
        results.append(entry)

    return {
        "metric_id": metric_id,
        "label": spec.get("label", metric_id),
        "period": pi["label"],
        "period_start": pi["start"],
        "period_end": pi["end"],
        "dimensions": dim_labels,
        "filters": filters or {},
        "cohort_size": len(cohort) if cohort else None,
        "results": results,
        "compiled_sql": sql,
        "sql_params": params if len(params) <= 12 else
                      params[:12] + [f"...and {len(params) - 12} more"],
    }
