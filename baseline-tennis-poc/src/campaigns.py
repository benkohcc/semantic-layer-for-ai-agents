"""Campaign registry: search the brief metadata, then pull governed numbers.

A campaign row with only dates, a channel and a budget cannot answer "why did we
run this", "who did it target", or "what did we learn". Those are the questions a
marketer asks before reusing or repeating a campaign, and without them past
performance is a number with no interpretation attached.

This module searches the campaign BRIEFS and hands back the campaign_id needed to
pull the governed revenue through get_metric. It deliberately does not compute
performance itself: the numbers still come from the metrics engine.
"""

from __future__ import annotations

import metrics_engine

SEARCHABLE = ("name", "objective", "offer", "target_segment", "target_category",
              "channel", "type", "owner", "learnings")


def conn_delivery(campaign_id: int) -> dict:
    """Send volume and attributed orders for a campaign. Context, not a metric."""
    with metrics_engine.connect() as conn:
        s = conn.execute("SELECT COUNT(*) n, SUM(delivered) d FROM email_sends "
                         "WHERE campaign_id = ?", (campaign_id,)).fetchone()
        o = conn.execute(
            "SELECT COUNT(DISTINCT id) n FROM orders WHERE campaign_id = ? "
            "AND status = 'completed' AND channel != 'wholesale'",
            (campaign_id,)).fetchone()
    return {"sends": s["n"] or 0, "delivered": s["d"] or 0,
            "attributed_orders": o["n"] or 0,
            "note": ("Delivery context, NOT governed metrics. Revenue and "
                     "engagement come from get_metric.")}


def search_campaigns(query: str | None = None, segment: str | None = None,
                     category: str | None = None, channel: str | None = None,
                     campaign_type: str | None = None,
                     period: str | None = None, limit: int = 12) -> dict:
    """Find campaigns by brief content, audience, or timing.

    Returns each campaign's brief plus the campaign_id and the exact get_metric
    call needed for its governed performance, so the two halves (what it was for,
    what it produced) can be put together.
    """
    where, params = ["1=1"], []
    if query:
        like = f"%{query.lower()}%"
        clauses = " OR ".join(f"LOWER(COALESCE({c},'')) LIKE ?" for c in SEARCHABLE)
        where.append(f"({clauses})")
        params += [like] * len(SEARCHABLE)
    if segment:
        # 'all' targeted campaigns also reach a specific segment, so they match.
        where.append("(target_segment = ? OR target_segment = 'all')")
        params.append(segment)
    if category:
        where.append("target_category = ?")
        params.append(category)
    if channel:
        where.append("channel = ?")
        params.append(channel)
    if campaign_type:
        where.append("type = ?")
        params.append(campaign_type)
    if period:
        pi = metrics_engine.resolve_period(period)
        where.append("start_date <= ? AND end_date >= ?")
        params += [pi["end"], pi["start"]]

    sql = (f"SELECT * FROM campaigns WHERE {' AND '.join(where)} "
           f"ORDER BY start_date DESC LIMIT ?")
    with metrics_engine.connect() as conn:
        rows = conn.execute(sql, params + [int(limit)]).fetchall()

    out = []
    for r in rows:
        # Delivery context, previously behind a separate campaign_detail tool.
        # It was one extra field on one extra call, so the tool was pure
        # navigation cost: another name to learn, another decision to get wrong.
        d = conn_delivery(r["id"])
        out.append({
            "campaign_id": r["id"],
            "delivery": d,
            "name": r["name"],
            "why_it_ran": r["objective"],
            "who_it_targeted": {"segment": r["target_segment"],
                                "category_promoted": r["target_category"]},
            "offer": r["offer"],
            "channel": r["channel"],
            "type": r["type"],
            "ran": f"{r['start_date']} to {r['end_date']}",
            "budget": r["budget"],
            "owner": r["owner"],
            "status": r["status"],
            "learnings": r["learnings"],
            "get_performance": {
                "tool": "get_metric",
                "args": {"metric_id": "net_revenue",
                         "filters": {"campaign_id": r["id"]},
                         "period": f"{r['start_date'][:7]}..{r['end_date'][:7]}"},
                "note": ("Use the campaign's OWN run dates as the period. The "
                         "default last_month returns nothing for a campaign that "
                         "ran earlier, which reads as missing data."),
            },
            # A campaign may also have a human written recap in the document
            # corpus, and those decks routinely quote a DIFFERENT figure (gross,
            # unfiltered, never restated). Point at it explicitly: a governed
            # number that silently disagrees with the deck on someone's desk is
            # how the layer loses an argument it should win.
            "check_for_recap": {
                "tool": "search_knowledge",
                "args": {"query": f"{r['name']} recap"},
                "note": ("Campaign recap decks often quote GROSS revenue over "
                         "all rows. If one exists, report the governed net "
                         "figure AND name the discrepancy with its reason "
                         "rather than quietly ignoring the deck."),
            },
        })

    return {
        "query": query, "matches": len(out), "campaigns": out,
        "interpretation": {
            "check_the_deck": (
                "A campaign with a written recap has a THIRD source of numbers: "
                "the deck. Decks quote gross over all rows and are rarely "
                "restated, so they will disagree with the governed metric. Follow "
                "check_for_recap, and if a deck exists, report the governed "
                "figure and explain the difference."),
            "two_halves": (
                "A campaign question has a brief half and a numbers half. This "
                "tool returns the brief: objective, audience, offer, owner and "
                "post campaign learnings. The NUMBERS come from get_metric using "
                "the campaign_id filter, shown per campaign under "
                "get_performance. Report both; a revenue figure with no objective "
                "cannot be judged as success or failure."),
            "caveats": [
                "Attribution is LAST TOUCH. Campaign attributed revenue is "
                "revenue whose final touch was this campaign, not revenue the "
                "campaign caused.",
                "Budget is planned spend, not necessarily spend delivered.",
                "target_segment 'all' means the campaign was not segment "
                "targeted, not that it reached everyone.",
                "learnings are a human note written after the campaign closed. "
                "They are opinion, useful context, and NOT a governed metric.",
            ],
            "missing_learnings_note": (
                "A null learnings field means the campaign is still running and no "
                "retrospective has been written yet. That is an honest absence, "
                "not missing data to work around."),
        },
    }


def campaign_detail(campaign_id: int) -> dict:
    """Full brief for one campaign, plus its send volume and engagement context."""
    with metrics_engine.connect() as conn:
        r = conn.execute("SELECT * FROM campaigns WHERE id = ?",
                         (int(campaign_id),)).fetchone()
        if not r:
            ids = [x[0] for x in conn.execute(
                "SELECT id FROM campaigns ORDER BY start_date DESC LIMIT 8")]
            raise ValueError(
                f"Campaign {campaign_id} does not exist. Recent campaign ids: "
                f"{ids}. Use search_campaigns to find one by name or objective.")
        sends = conn.execute(
            "SELECT COUNT(*) n, SUM(delivered) d FROM email_sends "
            "WHERE campaign_id = ?", (int(campaign_id),)).fetchone()
        orders = conn.execute(
            "SELECT COUNT(DISTINCT id) n FROM orders WHERE campaign_id = ? "
            "AND status = 'completed' AND channel != 'wholesale'",
            (int(campaign_id),)).fetchone()

    return {
        "campaign_id": r["id"], "name": r["name"],
        "why_it_ran": r["objective"],
        "who_it_targeted": {"segment": r["target_segment"],
                            "category_promoted": r["target_category"]},
        "offer": r["offer"], "channel": r["channel"], "type": r["type"],
        "ran": f"{r['start_date']} to {r['end_date']}",
        "budget": r["budget"], "owner": r["owner"], "status": r["status"],
        "learnings": r["learnings"],
        "delivery": {"sends": sends["n"] or 0, "delivered": sends["d"] or 0,
                     "attributed_orders": orders["n"] or 0},
        "interpretation": {
            "for_performance": (
                "Send counts and attributed order counts above are delivery "
                "context, NOT governed metrics. For revenue call get_metric with "
                f"filters={{'campaign_id': {r['id']}}} and period "
                f"'{r['start_date'][:7]}..{r['end_date'][:7]}'. For engagement "
                f"call email_open_rate or email_click_rate with the same filter."),
            "caveats": [
                "Attribution is last touch.",
                "learnings is a human retrospective, not a measurement.",
            ],
        },
    }


OPERATIONS = {"search_campaigns": search_campaigns,
              "campaign_detail": campaign_detail}
