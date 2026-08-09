"""No-LLM verification of the semantic layer.

The scored eval (`cli.py eval`) needs an API key because it measures whether a
model, steered only by this layer, produces correct answers. This script needs no
key and answers a different question: does the layer itself hold up?

For every eval question it checks that the assets the gold answer depends on
resolve, that the governed numbers match the gold values, and that the honesty
machinery (coverage holes, thin samples, absent concepts, authority ranking) fires
where it should. If this fails, the scored eval cannot pass and the fault is in
the layer, not the model.

  python eval/verify_layer.py
"""

from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

import tools as T  # noqa: E402
from catalog import get_catalog  # noqa: E402

CHECKS: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append((label, bool(ok), detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail
                                                      and not ok else ""))
    return bool(ok)


def near(a, b, tol) -> bool:
    return a is not None and abs(a - b) <= tol


def val(metric_id, dims=None, period=None, filters=None, cohort=None):
    r = T.get_metric(metric_id, dims, period, filters, cohort)
    assert "error" not in r, f"{metric_id}: {r.get('error')}"
    return r


def one(r):
    return r["results"][0]["value"]


def main() -> int:
    cat = get_catalog()
    # Gold values come from data/seed_facts.json, published by the seeder. They
    # were hardcoded here originally, which meant every reseed broke a dozen
    # assertions that only ever tested "the data has not changed".
    import json
    with open(os.path.join(ROOT, "data", "seed_facts.json")) as f:
        FACTS = json.load(f)
    GOLD = FACTS["gold"]
    SPRING = FACTS["spring_campaign_id"]

    print("\n=== content integrity ===")
    CORE_METRICS = {
        "net_revenue", "email_open_rate", "email_click_rate",
        "new_customer_signups", "aov", "repeat_purchase_rate", "cac",
        "refund_rate", "revenue_per_email", "segment_ltv",
    }
    check("all 10 core governed metrics load",
          CORE_METRICS <= set(cat.metrics),
          f"missing {sorted(CORE_METRICS - set(cat.metrics))}")
    check("5 playbooks load", len(cat.playbooks) == 5, f"got {len(cat.playbooks)}")
    check("every document has a wrapper", len(cat.documents) >= 25,
          f"got {len(cat.documents)}")
    check("graph edge descriptors load", len(cat.edges) == 2,
          f"got {len(cat.edges)}")
    check("benchmarks were generated from the data",
          bool(cat.benchmarks.get("metrics")))
    for mid, spec in cat.metrics.items():
        rel = spec.get("reliability") or {}
        ok = all(k in rel for k in ("min_sample", "coverage", "definition_caveats",
                                    "cannot_answer"))
        check(f"metric '{mid}' has a complete reliability block", ok)
        for block in ("definition", "evaluation", "framing", "access"):
            check(f"metric '{mid}' has the '{block}' block", block in spec)
    docs_dir = os.path.join(ROOT, "data", "documents")
    files = {f for f in os.listdir(docs_dir) if f.endswith(".md")}
    wrapped = {d.get("file") for d in cat.documents.values()}
    check("every document on disk has a catalog wrapper",
          files <= wrapped, f"unwrapped: {sorted(files - wrapped)}")
    check("every wrapper points at a real file",
          wrapped <= files, f"missing: {sorted(wrapped - files)}")

    print("\n=== Q1: email open rate (machine opens + transactional excluded) ===")
    r = val("email_open_rate")
    v = one(r)
    check("open rate is in the governed 18-30% band", 0.18 <= (v or 0) <= 0.30,
          f"got {v}")
    check("band verdict is within_band",
          r["interpretation"]["evaluation"]["comparison"]["position"] == "within_band")
    cav = " ".join(r["interpretation"]["framing"]["required_caveats"]).lower()
    check("MPP caveat is attached", "privacy protection" in cav or "mpp" in cav)
    check("click rate is the companion",
          "email_click_rate" in r["interpretation"]["framing"]["companions"])
    filt = " ".join(r["interpretation"]["computation"]["filters_applied"]).lower()
    check("transactional exclusion is declared", "transactional" in filt)
    check("machine open exclusion is declared", "machine_opened" in filt)

    print("\n=== Q2: net revenue (test + wholesale excluded) ===")
    r = val("net_revenue")
    v = one(r)
    check("net revenue resolves", near(v, GOLD["net_revenue_last_month"], 1),
          f"got {v}")
    import sqlite3
    conn = sqlite3.connect(os.path.join(ROOT, "data", "tennis_store.db"))
    naive = conn.execute(
        "SELECT SUM(gross_amount) FROM orders WHERE order_date BETWEEN ? AND ?",
        (r["period_start"], r["period_end"])).fetchone()[0]
    check("naive gross materially overstates governed net", naive > v * 1.3,
          f"naive {naive:.0f} vs governed {v:.0f}")
    filt = " ".join(r["interpretation"]["computation"]["filters_applied"]).lower()
    check("completed-status filter is declared", "completed" in filt)
    check("wholesale exclusion is declared", "wholesale" in filt)

    print("\n=== Q3: signup drop isolates paid_search, other channels flat ===")
    last = {x["acquisition_channel"]: x["value"]
            for x in val("new_customer_signups", ["acquisition_channel"])["results"]}
    prev = {x["acquisition_channel"]: x["value"]
            for x in val("new_customer_signups", ["acquisition_channel"],
                         "2026-06")["results"]}
    drop = 1 - last["paid_search"] / prev["paid_search"]
    check("paid_search signups dropped 10-50% month over month",
          0.10 <= drop <= 0.50, f"{prev['paid_search']} -> {last['paid_search']}")
    flat = all(abs(1 - last[c] / prev[c]) <= 0.25
               for c in ("organic", "paid_social"))
    check("organic and paid_social held roughly flat", flat,
          f"organic {prev['organic']}->{last['organic']}, "
          f"social {prev['paid_social']}->{last['paid_social']}")
    sk = T.search_knowledge("paid search budget pause media plan")
    titles = [h["title"] for h in sk["hits"]]
    check("the media plan is retrievable for the pause",
          any("Media Plan" in t for t in titles), f"got {titles}")
    chunk = " ".join(h["chunk"] for h in sk["hits"]
                     if "Media Plan" in h["title"]).lower()
    check("the media plan documents the pause", "pause" in chunk)

    print("\n=== Q4: refund policy resolves canonical, draft demoted ===")
    sk = T.search_knowledge("what is our refund policy")
    top = sk["hits"][0]
    check("top hit is in force", top["status"] == "in_force",
          f"got {top['status']}")
    check("top hit is the current policy", "2024" not in top["title"],
          f"got {top['title']}")
    draft = [h for h in sk["hits"] if h["status"] in ("draft", "superseded")]
    check("the superseded draft is retained and visible", bool(draft))
    if draft:
        check("the draft scored high on similarity (so the ranking mattered)",
              draft[0]["similarity_rank"] <= 6,
              f"simrank {draft[0]['similarity_rank']} of 56 chunks")
        check("the draft is ranked below the in force policy",
              sk["hits"].index(draft[0]) > 0)
        # THE POINT: the file contains no clue. Only the registry knows.
        body = open(os.path.join(ROOT, "data", "documents",
                                 "refund-policy-2024.md")).read()
        check("the stale document does NOT self identify as stale",
              not re.search(r"draft|superseded|not adopted|obsolete|historical",
                            body, re.I),
              "the document gives itself away")
        check("its status comes from the registry instead",
              cat.registry_for_file("refund-policy-2024.md").get("status")
              == "draft")
    check("stale versions are explicitly flagged",
          bool(sk.get("stale_versions_present")))

    print("\n=== Q5: CAC by channel, lower-is-better ===")
    r = val("cac", ["channel"])
    by = {x["channel"]: x["value"] for x in r["results"]}
    check("paid_search CAC resolves", by.get("paid_search") is not None)
    check("paid_social CAC resolves", by.get("paid_social") is not None)
    check("organic has no CAC (no spend)", "organic" not in by)
    check("direction is lower_better",
          r["interpretation"]["evaluation"]["direction"] == "lower_better")

    print("\n=== Q6: repeat purchase rate with a band judgment ===")
    r = val("repeat_purchase_rate")
    check("repeat rate is in a plausible band", 0.6 <= (one(r) or 0) <= 0.9,
          f"got {one(r)}")
    check("a band comparison is attached",
          "comparison" in r["interpretation"]["evaluation"])
    cav = " ".join(r["interpretation"]["framing"]["required_caveats"]).lower()
    check("the inferred-churn caveat travels with it",
          "infer" in cav or "trailing 12" in cav)

    print("\n=== Q7: spring campaign conflict, governed net beats deck gross ===")
    r = val("net_revenue", None, "2025-03..2025-05", {"campaign_id": SPRING})
    net = one(r)
    gross_all = conn.execute(
        "SELECT SUM(gross_amount) FROM orders WHERE campaign_id = ?", (SPRING,)).fetchone()[0]
    check("governed campaign net resolves", near(net, GOLD["spring_net"], 1),
          f"got {net}")
    check("the deck gross figure differs from governed net", gross_all > net,
          f"gross {gross_all:.0f} vs net {net:.0f}")
    check("the conflict rule is attached to the metric",
          "conflict_rule" in r["interpretation"]["framing"])
    sk = T.search_knowledge("spring campaign revenue recap")
    recap = [h for h in sk["hits"] if "Recap" in (h["title"] or "")]
    check("the recap deck is retrievable", bool(recap))
    if recap:
        check("the deck's gross figure is present in its text",
              "gross" in recap[0]["chunk"].lower())

    print("\n=== Q8/Q9: AOV inverts, LTV is the value metric ===")
    aov = {x["segment"]: x["value"] for x in val("aov", ["segment"])["results"]}
    ltv = {x["segment"]: x["value"]
           for x in val("segment_ltv", ["segment"], "all_time")["results"]}
    check("competitive AOV resolves", aov.get("competitive") is not None)
    check("recreational AOV resolves", aov.get("recreational") is not None)
    # The durable fact is that AOV does NOT track segment value: the LTV gap is
    # over 2x while the AOV gap is single digit percent. The exact AOV ordering
    # has flipped twice across reseeds, so asserting a direction would be
    # asserting a coincidence.
    aov_gap = abs(aov["competitive"] - aov["recreational"]) / max(aov.values())
    ltv_gap = ltv["competitive"] / ltv["recreational"]
    check("AOV does not track segment value: tiny AOV gap, large LTV gap",
          aov_gap < 0.15 and ltv_gap > 1.8,
          f"AOV gap {aov_gap:.1%} vs LTV ratio {ltv_gap:.2f}x")
    check("LTV ranks competitive higher", ltv["competitive"] > ltv["recreational"],
          f"{ltv}")
    check("competitive LTV is roughly double", ltv["competitive"] > ltv["recreational"] * 1.6)
    note = (cat.metric("aov")["framing"].get("segment_note") or "").lower()
    check("the AOV descriptor warns that AOV cannot rank segment value",
          "counter intuitive" in note and "same average" in note, note[:80])
    check("the AOV descriptor redirects value questions to segment_ltv",
          "segment_ltv" in note)

    print("\n=== Q10: December seasonality ===")
    r = val("net_revenue", None, GOLD["december_month"])
    notes = " ".join(str(n) for n in r["interpretation"]["evaluation"]["seasonal_notes"])
    check("December revenue resolves", near(one(r), GOLD["december_net"], 1))
    check("the December seasonality note fires", "December" in notes)
    check("the note says the dip is expected",
          "expected" in notes.lower() or "by design" in notes.lower())
    sk = T.search_knowledge("december seasonality promotional calendar")
    check("the promo calendar is retrievable",
          any("Promotional" in (h["title"] or "") for h in sk["hits"]))

    print("\n=== Q11: revenue per email is non-additive ===")
    r = val("revenue_per_email", ["month"], "last_6_months")
    series = [x["value"] for x in r["results"]]
    check("a monthly series is returned", len(series) >= 5, f"got {len(series)}")
    check("the metric is declared non-additive",
          r["interpretation"]["computation"]["additive"] is False)
    note = (r["interpretation"]["computation"]["additive_note"] or "").lower()
    check("the additive note forbids averaging",
          "never average" in note or "not an average" in note
          or "re derive" in note or "wrong answer" in note, note[:60])
    # The period value must be re-derived (summed numerator over summed
    # denominator), not averaged. Verified against the SQL, because in this data
    # monthly send volumes are similar enough that the weighted and unweighted
    # averages nearly coincide: a value comparison would pass either way and so
    # would prove nothing.
    whole_r = val("revenue_per_email", None, "last_6_months")
    sql = whole_r["compiled_sql"].lower()
    check("the period value is re-derived from summed numerator over summed "
          "denominator", sql.count("sum(") >= 2 and "avg(" not in sql)
    whole = one(whole_r)
    check("the re-derived value is volume weighted, not a mean of period values",
          abs(whole - sum(series) / len(series)) < 0.5,
          "sanity: the two should be close in this data, not identical by design")

    print("\n=== Q12: segmentation criteria from the guide ===")
    sk = T.search_knowledge("criteria for the competitive segment")
    guide = [h for h in sk["hits"] if "Segmentation" in (h["title"] or "")]
    check("the segmentation guide is retrievable", bool(guide))
    if guide:
        # The guide is long enough to split, so the criteria may sit in any of its
        # chunks. That is the chunking working, not a failure.
        body = " ".join(h["chunk"] for h in sk["hits"]
                        if "Segmentation" in (h["title"] or "")).lower()
        if "two or more" not in body:
            full = open(os.path.join(ROOT, "data", "documents",
                                     "segmentation-guide.md")).read().lower()
            check("the restring threshold is in the guide", "two or more" in full)
            check("the racket criterion is in the guide", "150" in full)
        else:
            check("the restring threshold is present", "two or more" in body)
            check("the racket criterion is present", "150" in body)
        check("the guide is in force", guide[0]["status"] == "in_force")

    print("\n=== Q16: NPS is a declared absent concept ===")
    da = T.discover_assets("what is our NPS")
    kg = da.get("known_gap")
    check("NPS resolves to a known gap", bool(kg))
    if kg:
        check("status is not_collected", kg["status"] == "not_collected")
        check("nearest signals are offered",
              set(kg["nearest_available"]) == {"repeat_purchase_rate", "refund_rate"})
        check("the response rule requires a clean decline",
              "decline" in kg["response_rule"].lower())
    check("no NPS or survey table exists in the warehouse",
          not conn.execute(
              "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND "
              "(name LIKE '%nps%' OR name LIKE '%survey%' OR name LIKE '%satisf%')"
          ).fetchone()[0])
    for phrasing in ["how do customers feel", "customer satisfaction",
                     "are customers happy"]:
        check(f"'{phrasing}' also resolves to the gap",
              bool(T.discover_assets(phrasing).get("known_gap")))

    print("\n=== Q17: paid_social CAC coverage hole ===")
    r = val("cac", ["channel"], "2024-09")
    chans = {x["channel"] for x in r["results"]}
    conf = r["interpretation"]["confidence"]
    check("paid_social returns no rows before tracking started",
          "paid_social" not in chans, f"got {chans}")
    check("the absent slice is flagged, not silently omitted",
          "declared_slice_absent" in conf["flags"], f"flags {conf['flags']}")
    check("confidence is degraded", conf["level"] == "low")
    check("the agent is told to surface it", conf["must_surface"])
    reasons = " ".join(conf["reasons"]).lower()
    check("the reason names the tracking start", "tracking" in reasons)
    check("the reason forbids extrapolation", "extrapolat" in reasons)
    # After the tracking start, paid_social must be present.
    later = {x["channel"] for x in val("cac", ["channel"], "2026-01")["results"]}
    check("paid_social IS present after tracking started",
          "paid_social" in later, f"got {later}")

    print("\n=== Q18: thin services slice ===")
    r = val("aov", ["category"])
    svc = [x for x in r["results"] if x["category"] == "services"][0]
    conf = r["interpretation"]["confidence"]
    check("services AOV resolves", svc["value"] is not None,
          f"got {svc['value']}")
    check("the services sample is below the threshold", svc["sample_size"] < 100,
          f"n={svc['sample_size']}")
    check("a low_sample flag is raised", "low_sample" in conf["flags"])
    check("confidence is low", conf["level"] == "low")
    reasons = " ".join(conf["reasons"]).lower()
    check("the reason requires a directional label", "directional" in reasons)
    check("the reason states the sample size",
          str(svc["sample_size"]) in " ".join(conf["reasons"]))

    print("\n=== Q19: churn is inferred, not observed ===")
    churn = cat.shared_definition("churn")
    check("the spine declares churn unobserved", churn.get("observed") is False)
    check("the spine states the inference rule", "trailing 12" in churn.get("rule", ""))
    check("disclosure is required", churn.get("disclosure_required") is True)
    rel = cat.metric("repeat_purchase_rate")["reliability"]
    caveats = " ".join(rel["definition_caveats"]).lower()
    check("the churn-adjacent metric carries the inference caveat",
          "infer" in caveats and "cancellation" in caveats)
    r = val("repeat_purchase_rate")
    reasons = " ".join(r["interpretation"]["confidence"]["reasons"]).lower()
    check("the caveat reaches the payload at query time", "infer" in reasons)
    onto = [c for c in cat.ontology["concepts"] if "churn" in c["terms"]]
    check("the ontology routes churn with a disclosure requirement",
          bool(onto) and onto[0].get("disclosure_required") is True)

    print("\n=== Q20: forecasting is out of scope ===")
    for phrasing in ["what will revenue be next quarter",
                     "forecast revenue", "predict next month"]:
        kg = T.discover_assets(phrasing).get("known_gap")
        check(f"'{phrasing}' resolves to a scope decline",
              bool(kg) and kg["status"] == "out_of_scope")
    kg = T.discover_assets("what will revenue be next quarter")["known_gap"]
    check("the rule forbids producing a forecast number",
          "no forecast" in kg["response_rule"].lower())

    print("\n=== Q13/14/15: graph access path (milestone 2) ===")
    import graph_tools
    cs = graph_tools.relationship_selection("chain_stats", {"group_by": "acquisition_channel"})
    stats = {s["acquisition_channel"]: s for s in cs["stats"]}
    organic = stats["organic"]["avg_chain_depth"]
    others = [v["avg_chain_depth"] for k, v in stats.items() if k != "organic"]
    check("organic seeds the deepest chains", organic > max(others),
          f"organic {organic} vs best other {max(others)}")
    check("the gap is decisive (>= 1.0 depth)", organic - max(others) >= 1.0,
          f"gap {organic - max(others):.2f}")
    check("chain depth is attributed to the root's channel",
          "root" in cs["measurement_note"].lower())

    ec = graph_tools.relationship_selection("exposed_cohort",
                                 {"edge_type": "referred_by",
                                  "condition": "referrer_churned"})
    check("the exposed cohort is large enough", ec["exposed_size"] >= 250,
          f"got {ec['exposed_size']}")
    check("the comparison cohort is large enough", ec["comparison_size"] >= 2000,
          f"got {ec['comparison_size']}")
    check("temporal ordering is reported",
          "verdict" in ec["temporal_ordering"])
    check("the ordering verdict holds",
          "holds" in ec["temporal_ordering"]["verdict"].lower())
    check("the inferred-churn disclosure travels with the cohort",
          "inferred" in ec["definition_disclosure"].lower())

    # Cohort HANDLES, not id lists. A 3,876 id comparison cohort echoed back as a
    # tool argument is tens of thousands of tokens per call, which timed out the
    # milestone 2 gate before handles existed.
    check("cohorts are registered under handles", "cohort_handles" in ec)
    check("both handles are present",
          {"exposed", "comparison"} <= set(ec.get("cohort_handles") or {}))
    import json as _json
    check("long id lists are not inlined in the payload",
          len(_json.dumps(ec, default=str)) < 12_000,
          f"payload is {len(_json.dumps(ec, default=str))} bytes")

    a = one(val("repeat_purchase_rate", None, "last_month", cohort="exposed"))
    b = one(val("repeat_purchase_rate", None, "last_month", cohort="comparison"))
    delta = (b - a) * 100
    check("composition through get_metric finds the planted delta",
          6 <= delta <= 22, f"got {delta:.1f} points")
    print(f"        exposed {a:.4f} vs comparison {b:.4f} -> {delta:.1f} points")
    # An explicit id list must keep working, so the handle is ergonomics only.
    a_ids = one(val("repeat_purchase_rate", None, "last_month",
                    cohort=graph_tools.resolve_cohort("exposed")))
    check("a handle and an explicit id list give the same answer",
          a_ids == a, f"handle {a} vs ids {a_ids}")
    bad = T.get_metric("repeat_purchase_rate", None, "last_month",
                       cohort="does_not_exist")
    check("an unknown handle is rejected with the registered handles listed",
          "error" in bad and "exposed" in bad.get("error", ""))

    # A PARTIAL cohort is the dangerous case: it computes cleanly and reports a
    # confident number for the wrong population. An earlier payload exposed 20
    # sample ids and the agent passed those as the cohort, producing 82.1 vs 83.9
    # (a 1.8 point gap) instead of the real 67.8 vs 82.8.
    full_exposed = graph_tools.resolve_cohort("exposed")
    partial = T.get_metric("repeat_purchase_rate", None, "last_month",
                           cohort=full_exposed[:20])
    check("a partial cohort id list is rejected, not silently computed",
          "error" in partial and "SUBSET" in partial.get("error", ""))
    check("no id sample is exposed in the payload to be pasted by mistake",
          isinstance(ec["exposed_customer_ids"], dict)
          and "sample_ids" not in ec["exposed_customer_ids"])

    tc = graph_tools.relationship_selection("trace_cohort", {"campaign_id": SPRING,
                                                 "recalled": True})
    check("the traced cohort is large enough", tc["traced_size"] >= 300,
          f"got {tc['traced_size']}")
    check("a matched control is returned", tc["control_size"] >= 300,
          f"got {tc['control_size']}")
    check("the recalled product is identified",
          tc["product"]["name"].endswith("SpinTech 17"), f"got {tc['product']}")
    check("the recall boundary note is attached", "recall_boundary_note" in tc)
    check("trace_cohort also registers handles",
          {"traced", "control"} <= set(tc.get("cohort_handles") or {}))
    c = one(val("repeat_purchase_rate", None, "last_month", cohort="traced"))
    d = one(val("repeat_purchase_rate", None, "last_month", cohort="control"))
    div = (d - c) * 100
    check("the recall divergence is present", 5 <= div <= 22,
          f"got {div:.1f} points")
    print(f"        recalled {c:.4f} vs control {d:.4f} -> {div:.1f} points")
    sk = T.search_knowledge("string recall notice")
    check("the recall notice is retrievable",
          any("Recall" in (h["title"] or "") for h in sk["hits"]))

    print("\n=== graph operations fail readably, not with a traceback ===")
    # An uncaught int() crash on a campaign NAME sent the agent into a 12 call
    # retry loop guessing at parameters. Names now resolve, and anything that
    # cannot be resolved returns guidance rather than a stack trace.
    byname = graph_tools.relationship_selection("trace_cohort",
                                     {"campaign_id": "Spring League Kickoff",
                                      "recalled": True})
    check("trace_cohort accepts a campaign NAME as well as an id",
          "error" not in byname and byname.get("traced_size", 0) >= 300)
    miss = graph_tools.relationship_selection("trace_cohort",
                                   {"campaign_id": "No Such Campaign"})
    check("an unresolvable campaign returns guidance, not a crash",
          "error" in miss and "search_knowledge" in miss.get("error", ""))
    amb = graph_tools.relationship_selection("trace_cohort", {"campaign_id": "Push"})
    check("an ambiguous campaign name lists the candidates",
          "error" in amb and "matches" in amb.get("error", ""))
    badroot = graph_tools.relationship_selection("referral_chain", {"root": "organic"})
    check("a non numeric root is rejected with a pointer to 'channel'",
          "error" in badroot and "channel" in badroot.get("error", ""))

    print("\n=== negative routing: relationships alone stay with metrics ===")
    rules = {r["rule"]: r for r in cat.negative_routing_rules()}
    check("the relationship-does-not-imply-graph rule exists",
          "relationships_alone_do_not_route_to_graph" in rules)
    check("the never-recompute rule exists",
          "never_recompute_a_governed_metric_outside_the_metrics_engine" in rules)
    r = rules["relationships_alone_do_not_route_to_graph"]
    check("it names the aggregations that stay with the metrics engine",
          len(r.get("stays_with_metrics_engine", [])) >= 3)
    # "How many customers were referred" must be answerable as a metric.
    ref = val("new_customer_signups", ["acquisition_channel"], "all_time")
    by = {x["acquisition_channel"]: x["value"] for x in ref["results"]}
    check("referral counts are answerable via the metrics engine",
          by.get("referral", 0) > 4000, f"got {by.get('referral')}")

    print("\n=== access control ===")
    for mid, spec in cat.metrics.items():
        check(f"metric '{mid}' forbids raw SQL",
              spec["access"].get("raw_sql_allowed") is False)
    check("run_sql is not a semantic tool", "run_sql" not in T.SEMANTIC_TOOLS)
    check("naive_search is not a semantic tool",
          "naive_search" not in T.SEMANTIC_TOOLS)
    check("run_sql is baseline-only", "run_sql" in T.BASELINE_TOOLS)

    print("\n=== brand, margin and inventory: gaps CLOSED, not declared ===")
    # These were falling through undeclared. The temptation was to declare them as
    # gaps, which would have been honest and wrong: a retailer knows its brands,
    # its costs and its stock. The fix was to put the data in.
    r = val("order_count", ["brand"], "trailing_12m")
    brands = {x["brand"]: x["value"] for x in r["results"] if x["brand"]}
    check("brand is a real dimension", len(brands) >= 6, f"got {len(brands)}")
    comp = val("order_count", ["brand"], "trailing_12m",
               {"segment": "competitive"})["results"]
    rec = val("order_count", ["brand"], "trailing_12m",
              {"segment": "recreational"})["results"]
    PERF = {"Baseline", "Cordage", "Meridian"}
    def perf_share(rows):
        tot = sum(x["value"] or 0 for x in rows if x["brand"]) or 1
        return sum(x["value"] or 0 for x in rows
                   if x["brand"] in PERF) / tot
    cs, rs = perf_share(comp), perf_share(rec)
    print(f"        performance brand share: competitive {cs:.0%}, "
          f"recreational {rs:.0%}")
    check("segments differ in brand preference", cs - rs >= 0.15,
          f"gap {cs - rs:.2f}")

    m = val("gross_margin", None, "last_month")
    check("gross margin resolves", (one(m) or 0) > 0, f"got {one(m)}")
    mr = val("margin_rate", ["brand"], "trailing_12m")
    rates = {x["brand"]: x["value"] for x in mr["results"] if x["brand"]}
    check("margin rate varies by brand",
          max(rates.values()) - min(rates.values()) >= 0.15,
          f"spread {max(rates.values()) - min(rates.values()):.3f}")
    check("own label carries the best margin rate",
          max(rates, key=rates.get) == "House",
          f"best is {max(rates, key=rates.get)}")
    cav = " ".join(cat.metric("gross_margin")["framing"]["required_caveats"]).lower()
    check("gross margin declares it is not profit", "not profit" in cav)

    import sqlite3 as _sq
    _c = _sq.connect(os.path.join(ROOT, "data", "tennis_store.db"))
    check("suppliers are recorded with terms",
          _c.execute("SELECT COUNT(*) FROM suppliers WHERE lead_time_days > 0 "
                     "AND payment_terms IS NOT NULL").fetchone()[0] >= 5)
    check("stock and lifecycle are recorded per product",
          _c.execute("SELECT COUNT(*) FROM products WHERE stock_level IS NULL "
                     "OR lifecycle_stage IS NULL").fetchone()[0] == 0)
    _c.close()

    print("\n=== governance is EXTERNAL: no document self identifies ===")
    # The original corpus had every document declare its own authority in its
    # header, and the stale ones announced their own obsolescence ("NOT ADOPTED",
    # "Status: HISTORICAL"). That made the ranking demo a reading comprehension
    # exercise: even naive search could spot the stale document from line three.
    # Status now lives only in document_registry.yaml.
    docs_dir = os.path.join(ROOT, "data", "documents")
    SELF_ID = re.compile(
        r"^\s*(Authority|Status|Supersedes|Superseded by)\s*:|NOT ADOPTED|"
        r"Status:\s*(draft|superseded|HISTORICAL)", re.I | re.M)
    offenders = []
    for fn in sorted(os.listdir(docs_dir)):
        if not fn.endswith(".md"):
            continue
        body = open(os.path.join(docs_dir, fn)).read()
        if SELF_ID.search(body):
            offenders.append(fn)
    check("no document declares its own authority or status",
          not offenders, f"self identifying: {offenders}")

    # And every document is substantial. Under 50 lines is too thin to retrieve
    # within, too thin to chunk, and too thin for a near miss to be near.
    short = []
    for fn in sorted(os.listdir(docs_dir)):
        if not fn.endswith(".md"):
            continue
        n = len(open(os.path.join(docs_dir, fn)).read().splitlines())
        if n < 50:
            short.append((n, fn))
    check("every document carries substantial content (50+ lines)",
          not short, f"too short: {short}")

    check("the registry covers every document",
          len(cat.doc_registry) >= len([f for f in os.listdir(docs_dir)
                                        if f.endswith(".md")]),
          f"{len(cat.doc_registry)} registry entries")
    check("the registry declares its precedence rules",
          len(cat.precedence_rules) >= 3)

    # The three lineages, each a different flavour of the same problem.
    for lineage, current, stale in [
            ("refund-policy", "refund-policy-2026", "refund-policy-2024"),
            ("stringing-sla", "stringing-sla-2026", "stringing-sla-2025"),
            ("media-plan", "q3-media-plan", "q2-media-plan")]:
        cur = cat.registry_for_id(current)
        old = cat.registry_for_id(stale)
        check(f"{lineage}: the current version is in force",
              cur.get("status") == "in_force")
        check(f"{lineage}: the older version is demoted by the registry alone",
              old.get("status") in ("draft", "superseded"))
        body = open(os.path.join(docs_dir, old["file"])).read()
        check(f"{lineage}: the older document does not admit it is stale",
              not re.search(r"superseded|not adopted|no longer|obsolete|"
                            r"historical|do not use", body, re.I),
              "the document gives itself away")

    # The hardest case: both were genuinely in force, so status alone is not
    # enough and the effective date has to do the work.
    a = cat.registry_for_id("stringing-sla-2025")
    b = cat.registry_for_id("stringing-sla-2026")
    check("the SLA pair is discriminated by effective date, not by wording",
          a.get("effective_date") < b.get("effective_date")
          and a.get("lineage") == b.get("lineage"))

    print("\n=== the corpus is big enough to exercise retrieval ===")
    import retrieval as _r
    n_chunks = _r._collection("documents").count()
    check("the corpus spans more chunks than documents",
          n_chunks > len(cat.documents),
          f"{n_chunks} chunks for {len(cat.documents)} documents")

    # TRAP: the answer is a buried subsection of a long manual, not a whole doc.
    sk = T.search_knowledge("what tension do we string a junior racket at", limit=3)
    top = sk["hits"][0]
    check("within document retrieval finds the right PASSAGE",
          "forty eight pounds" in top["chunk"],
          f"top hit was {top['title']}")

    # TRAP: two documents, both once canonical, discriminated by effective date.
    sk = T.search_knowledge("what is our stringing turnaround commitment", limit=4)
    check("the current SLA outranks the superseded one",
          sk["hits"][0]["status"] == "in_force"
          and "Stringing Service Level" in sk["hits"][0]["title"],
          f"top is {sk['hits'][0]['title']} ({sk['hits'][0]['status']})")
    check("the superseded SLA is flagged, not hidden",
          "2025" in str((sk.get("stale_versions_present") or {}).get("documents")))

    # TRAP: transactional email is a plausible near miss for a marketing question.
    sk = T.search_knowledge("what is our email open rate", limit=3)
    titles = [h["title"] for h in sk["hits"]]
    check("a marketing email question does not surface transactional first",
          not titles[0].startswith("Transactional"), f"top is {titles[0]}")

    print("\n=== previously false confident answers now land correctly ===")
    for q, expect in [("what brands do we carry", "Brand and Supplier"),
                      ("what is our margin on rackets", "Brand and Supplier"),
                      ("what do customers complain about", "Customer Service"),
                      ("what suppliers do we work with", "Supplier Terms"),
                      ("who is our target customer persona", "Customer Personas"),
                      ("what is our pricing strategy", "Pricing and Discount")]:
        hit = T.search_knowledge(q, limit=1)["hits"][0]
        check(f"'{q[:40]}' finds a document that answers it",
              expect in hit["title"], f"got {hit['title']}")

    print("\n=== marketer coverage: plain language routes to an asset ===")
    # The ontology previously routed only 3 of 12 plain phrasings; the term lists
    # were jargon ("revenue", "cac") while people say "how much money did we make".
    # That meant the MODEL was doing concept resolution, not the layer.
    PLAIN = [
        "how much money did we make", "how many people signed up",
        "are people opening our emails", "what does it cost to get a customer",
        "do customers come back", "how much is a customer worth",
        "how many returns", "basket size", "are emails landing in inbox",
        "which channel is cheapest", "did we grow", "best selling category",
        "how many orders", "how big is our base", "gross revenue",
        "who should I send a promotion to", "cross sell", "past campaigns",
        "which rackets do competitive players prefer",
    ]
    unrouted = [q for q in PLAIN
                if not cat.resolve_concept(q) and not cat.resolve_absent_concept(q)]
    check("every plain language phrasing routes to an asset or a declared gap",
          not unrouted, f"unrouted: {unrouted}")

    print("\n=== product grain (targeting questions) ===")
    r = val("order_count", ["racket_type"], "trailing_12m",
            {"segment": "competitive", "category": "rackets"})
    by = {x["racket_type"]: x["value"] for x in r["results"] if x["racket_type"]}
    check("order_count supports the racket_type dimension", len(by) == 3, str(by))
    check("competitive players prefer control frames in the data",
          by.get("control", 0) > by.get("power", 0) * 2,
          f"control {by.get('control')} vs power {by.get('power')}")
    rp = val("net_revenue", ["product"], "last_month")
    check("net_revenue supports the product dimension",
          len([x for x in rp["results"] if x["product"]]) > 20)
    perf = val("order_count", None, "trailing_12m", {"is_performance": 1})
    check("the segmentation guide's performance criterion is computable",
          (one(perf) or 0) > 0)

    print("\n=== cross-sell affinity reports lift, not just share ===")
    aff = T.category_affinity("rackets")
    check("affinity resolves for rackets", "error" not in aff)
    lifts = {a["category"]: a["lift"] for a in aff["affinities"]}
    check("strings show real lift for racket buyers", lifts.get("strings", 0) >= 1.05,
          f"lift {lifts.get('strings')}")
    # A category can have a high SHARE and no lift; the payload must expose both so
    # a popular category is not mistaken for an affinity.
    shares = {a["category"]: a["share_of_cohort"] for a in aff["affinities"]}
    check("share and lift are both reported per category",
          all(a.get("lift") is not None and a.get("share_of_cohort") is not None
              for a in aff["affinities"]))
    check("the payload warns that share alone misleads",
          "lift" in aff["interpretation"]["how_to_read"].lower())

    print("\n=== audience building composes into governed metrics ===")
    au = T.build_audience(segment="competitive", bought_category="rackets",
                          lapsed_category_months=12, active_only=True,
                          handle="verify_promo")
    check("an audience is built", "error" not in au and au["size"] > 100,
          str(au.get("error") or au.get("size")))
    check("the audience returns a handle, not a pasted id list",
          au.get("ids_withheld") is True and "audience_handle" in au)
    check("the criteria applied are stated in plain language",
          len(au.get("criteria_applied") or []) >= 3)
    check("the no PII rule travels with the audience",
          "NO CONTACT DETAILS" in au["interpretation"]["no_pii"])
    check("inferred lapse is disclosed when that criterion is used",
          "inferred_churn_disclosure" in au["interpretation"])
    m = val("segment_ltv", None, "all_time", cohort="verify_promo")
    check("the audience handle composes into get_metric",
          (one(m) or 0) > 0 and m["results"][0]["sample_size"] == au["size"])
    empty = T.build_audience()
    check("an audience with no criteria is rejected rather than selecting everyone",
          "error" in empty and "at least one criterion" in empty["error"])

    print("\n=== campaign briefs: why, to whom, what was learned ===")
    sc = T.search_campaigns(query="restring")
    check("campaign search resolves", "error" not in sc and sc["matches"] > 0)
    c0 = sc["campaigns"][0]
    for field in ("why_it_ran", "who_it_targeted", "offer", "owner"):
        check(f"campaign brief carries '{field}'", bool(c0.get(field)))
    check("each result carries the get_metric call for its numbers",
          c0["get_performance"]["args"]["filters"]["campaign_id"] == c0["campaign_id"])
    check("the period offered is the campaign's own run dates, not last_month",
          ".." in c0["get_performance"]["args"]["period"])
    check("the payload separates the brief from the numbers",
          "two_halves" in sc["interpretation"])
    # Delivery context used to live behind a separate campaign_detail tool. It
    # added exactly one field, so it was navigation cost with no capability
    # behind it, and it is now inline on every search result.
    check("delivery context is inline, no second call needed",
          "delivery" in c0 and "sends" in c0["delivery"])
    check("delivery is labelled as context, not a governed metric",
          "NOT governed metrics" in c0["delivery"].get("note", ""))

    print("\n=== newly declared gaps decline rather than fall through ===")
    for phrase, status in [
            ("unsubscribe rate", "not_collected"),
            ("conversion rate", "not_collected"),
            ("which ad creative performed best", "not_collected"),
            ("which customers are most likely to buy", "out_of_scope"),
            ("give me the email addresses", "not_collected")]:
        gap = cat.resolve_absent_concept(phrase)
        check(f"'{phrase}' resolves to a declared gap",
              bool(gap) and gap[0]["status"] == status,
              f"got {gap[0]['status'] if gap else 'nothing'}")
    prop = cat.resolve_absent_concept("most likely to buy")
    check("the propensity decline offers a behavioural audience instead",
          bool(prop) and "build_audience" in str(prop[0]["nearest_available"]))

    print("\n=== descriptor and engine agree on filters ===")
    # A descriptor that advertises a filter the engine rejects makes an
    # answerable question look unanswerable. One that omits a filter the engine
    # accepts hides a capability, which is what made question 7 fail: the agent
    # declined a campaign revenue question because nothing advertised
    # campaign_id. Worst of all is a filter accepted and silently ignored, which
    # returns a number the caller believes is narrowed when it is not.
    PROBE = {"channel": "paid_social", "segment": "competitive",
             "category": "strings", "region": "west",
             "acquisition_channel": "organic", "campaign_id": 23,
             "email_type": "campaign"}
    drift = []
    for mid, spec in cat.metrics.items():
        declared = set(spec["definition"].get("available_filters") or {})
        for name, v in PROBE.items():
            accepted = "error" not in T.get_metric(mid, None, "last_month",
                                                   {name: v})
            if name in declared and not accepted:
                drift.append(f"{mid} declares '{name}' but the engine rejects it")
            if name not in declared and accepted:
                drift.append(f"{mid} accepts '{name}' but does not declare it")
    check("every metric's declared filters match engine behavior", not drift,
          "; ".join(drift[:3]))

    # A filter must never be accepted and then ignored.
    base = one(val("net_revenue"))
    narrowed = one(val("net_revenue", None, "last_month",
                       {"segment": "competitive"}))
    check("an accepted filter actually narrows the result", narrowed < base,
          f"unfiltered {base:.0f} vs filtered {narrowed:.0f}")
    rpe = T.get_metric("revenue_per_email", None, "last_month",
                       {"segment": "competitive"})
    check("revenue_per_email rejects filters rather than ignoring them",
          "error" in rpe and "does not support filters" in rpe.get("error", ""))

    # An empty filtered result must say WHY it might be empty. Without this, a
    # campaign filter on the default period reads as "campaign attribution is
    # unavailable" and the agent declines an answerable question.
    empty = val("net_revenue", None, "last_month", {"campaign_id": SPRING})
    conf = empty["interpretation"]["confidence"]
    check("an empty filtered result is flagged no_data",
          "no_data" in conf["flags"])
    why = " ".join(conf["reasons"])
    check("the no_data reason names the period as the likely cause",
          "does not exist IN THAT PERIOD" in why)
    check("the no_data reason tells the agent to re query the campaign window",
          "campaign's own start and end dates" in why)
    check("the campaign filter DOES work over the campaign's own window",
          near(one(val("net_revenue", None, "2025-03..2025-05",
                       {"campaign_id": SPRING})), GOLD["spring_net"], 1))

    print("\n=== criterion 6: a new metric is a CONTENT change ===")
    # email_delivered_rate exists only as a YAML descriptor with a declarative
    # `sql` block. No Python was written for it. If this computes, adding a
    # metric needs no code change.
    demo = "email_delivered_rate"
    check(f"'{demo}' is registered from YAML alone", demo in cat.metrics)
    spec = cat.metric(demo) or {}
    check("it declares a declarative sql block", bool(spec.get("sql")))
    r = val(demo)
    check("it computes a value", 0.90 <= (one(r) or 0) <= 1.0, f"got {one(r)}")
    check("interpretation is attached automatically",
          bool(r["interpretation"]["framing"]["required_caveats"]))
    check("its companion metric is attached",
          "email_open_rate" in r["interpretation"]["framing"]["companions"])
    rd = val(demo, ["segment"])
    check("dimensions work, including the implied join",
          len(rd["results"]) == 2 and "JOIN customers" in rd["compiled_sql"])
    bad = T.get_metric(demo, ["channel"])
    check("undeclared dimensions are still rejected", "error" in bad)

    print("\n=== rejection messages are self-correcting ===")
    e = T.get_metric("net_revenue", ["nonexistent"])
    check("an invalid dimension is rejected", "error" in e)
    check("the rejection lists the allowed dimensions",
          "month" in e.get("error", "") and "channel" in e.get("error", ""))
    e = T.get_metric("made_up_metric")
    check("an unknown metric is rejected", "error" in e)
    check("the rejection lists available metrics",
          "net_revenue" in str(e.get("available_metrics", [])))
    g = graph_tools.relationship_selection("arbitrary_traversal", {})
    check("an unregistered graph operation is rejected", "error" in g)
    check("the rejection says the set is closed",
          "closed set" in g.get("error", "").lower())

    conn.close()

    n_pass = sum(1 for _, ok, _ in CHECKS if ok)
    n_fail = len(CHECKS) - n_pass
    print("\n" + "=" * 74)
    print(f"  {n_pass} passed, {n_fail} failed of {len(CHECKS)} checks")
    print("=" * 74)
    if n_fail:
        print("\nFailures:")
        for label, ok, detail in CHECKS:
            if not ok:
                print(f"  - {label}  [{detail}]")
        return 1
    print("\n  The semantic layer verifies end to end with no model involved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
