#!/usr/bin/env python
"""MCP server for the Baseline Tennis Co. semantic layer.

Claude Desktop or Claude Code is the agent. This server supplies the tools, the
instructions, and the playbooks. Because the user cannot edit Claude's system
prompt in the desktop app, all orchestration steering lives here, in three
places:

  1. server instructions (the MCP `instructions` field)
  2. tool descriptions (the agent's primary steering surface)
  3. the playbooks returned by get_playbook

Modes:
  python mcp_server.py                  semantic layer, graph OFF (milestone 1)
  python mcp_server.py --enable-graph   semantic layer, graph ON  (milestone 2)
  python mcp_server.py --baseline       raw SQL + naive search only, NO semantics
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from mcp.server import MCPServer

import tools as T
from catalog import get_catalog

# ---------------------------------------------------------------------------
# Server instructions. Compact, directive, and mode dependent.
# ---------------------------------------------------------------------------

CORE_INSTRUCTIONS = """
You are answering questions about Baseline Tennis Co., a direct to consumer
online tennis store, using a governed semantic layer. The layer holds the
definitions; you hold the reasoning. Follow this procedure.

## Procedure

1. If you are unsure what exists, call `get_started` first. It is cheap.
2. Classify the question into an archetype: metric-lookup,
   metric-decline-diagnosis, policy-question, or graph-traversal.
3. Call `get_playbook` for that archetype and FOLLOW IT STEP BY STEP. Do not
   substitute your own procedure.
4. Resolve every number through `get_metric`. Read the full interpretation
   payload before writing anything.

## Hard rules

- NEVER estimate, interpolate, or compute a number the tools did not return. If a
  tool did not give you the number, you do not have it.
- ALWAYS resolve metrics through `get_metric`. There is no raw SQL access on this
  server, by design: the exclusion filters that make each metric correct live
  inside the metrics engine.
- Governed metrics OVERRIDE any figure found in a document, deck, or report. When
  they disagree, report the governed number and NAME the discrepancy with its
  reason. Do not average them and do not silently pick one.
- Documents are ranked by AUTHORITY (canonical > draft > superseded), not by
  similarity. Answer from canonical documents only. If a superseded or draft
  version surfaced, say it exists and is not in force.
- CHECK `direction` before using any evaluative word. For `cac` and
  `refund_rate`, LOWER IS BETTER, so an increase is bad news.
- Non additive metrics must never be averaged across periods. Re derive them.
- Every required caveat in the payload must appear in your answer. They are not
  optional garnish.

## Honesty rules

Declining is a correct answer when the data does not support the question. A
confident number built on a known gap is the worst possible failure, worse than
no answer at all.

- When the payload carries degraded `confidence`, surface it in the ANSWER BODY
  with the reason, not as a footnote and never omitted.
- When a tool reports a `known_gap`, that is an AUTHORITATIVE ANSWER, not a
  search failure. Do not keep searching, and do not substitute a nearby metric
  dressed up as the thing that was asked for.
- Never fill a coverage hole by extrapolating from the covered periods.
- Never present an inferred definition as an observed fact. Churn in this
  business is INFERRED from purchase silence (no completed order in the trailing
  12 months); there is no cancellation event. Say so every time churn comes up.
- Never answer a forecast question with a trend restated as a prediction. This
  layer reports actuals. Forecasting is out of scope.
- There is NO satisfaction, sentiment, or NPS data anywhere in this business.
  Not thin data, none. Decline those questions and offer repeat_purchase_rate and
  refund_rate as adjacent behavioral signals while stating that neither measures
  sentiment.

## Seasonality

December revenue dips every year by design, and March through May run hot for
spring leagues. Check `seasonal_notes` before diagnosing anything as a problem.
Compare to the same month last year, not to the adjacent month.
""".strip()

GRAPH_OFF_INSTRUCTIONS = """
## No relationship traversal is available

This server has NO access path for walking relationships. If a question requires
traversing chains of unknown depth (referrals of referrals, downstream networks),
tracing propagation or exposure through relationships, or following a population
across three or more entity hops, then:

STATE PLAINLY that no registered access path supports relationship traversal,
and NAME what the question would require (for example: recursive traversal of the
referral graph to unbounded depth, then a governed metric computed on the
resulting cohort).

Do NOT attempt it through other tools. Do NOT approximate it with a single level
aggregation and present that as the answer. Do NOT write SQL; there is no SQL
tool here. Do NOT fabricate a traversal result.

A clean capability decline naming the missing path is the CORRECT answer.

Note the boundary carefully: questions that merely MENTION relationships are
usually ordinary metric questions and must still be answered. "How many customers
were referred" is a count over an attribute. "Revenue from referred customers" is
an aggregation with a filter. Both belong to `get_metric`. Only unknown depth,
propagation, and multi hop tracing need traversal.
""".strip()

GRAPH_ON_INSTRUCTIONS = """
## Relationship traversal is available

`build_audience` provides, through its `operation` parameter, a CLOSED SET of
traversal operations over the referral and
purchase graph. Use it only for the graph-traversal archetype: chains of unknown
depth, propagation or exposure through relationships, or tracing a population
across three or more entity hops.

Call `get_playbook("graph-traversal")` before using it.

### The composition rule, which is not optional

The graph SELECTS COHORTS. It does not compute metrics. When a traversal question
asks for a rate, a revenue figure, or any other measured quantity for the cohort
you found:

  1. A relationship operation registers each cohort under a short HANDLE, listed in
     the result under `cohort_handles`, typically "exposed" and "comparison", or
     "traced" and "control".
  2. Call `get_metric` with `cohort="<handle>"`, once per cohort.
  3. The governed metric is computed by the metrics engine, on that cohort.

DO NOT paste id lists into `get_metric`. Cohorts here run to thousands of
customers, and echoing them back wastes the context and risks transcription
errors. The handle is the supported path.

A number computed inside traversal code, or by you from the id list, is NOT the
governed metric and is NOT an acceptable answer even if the arithmetic is right.
Always compare the cohort against the matched or non exposed cohort returned
alongside it, never against the overall benchmark band.

### Do not misroute to the graph

The presence of a relationship in a question does not make it a traversal
question. Aggregations over attributes stay with `get_metric`, including counts of
referred customers and revenue from referred customers. Route to the graph only
for unknown depth, propagation, or multi hop tracing.
""".strip()

BASELINE_INSTRUCTIONS = """
You have direct access to the Baseline Tennis Co. warehouse and a document search
index. Answer the user's questions about marketing performance.
""".strip()


# ---------------------------------------------------------------------------
# Server construction
# ---------------------------------------------------------------------------


def build_semantic_server(enable_graph: bool) -> MCPServer:
    instructions = CORE_INSTRUCTIONS + "\n\n" + (
        GRAPH_ON_INSTRUCTIONS if enable_graph else GRAPH_OFF_INSTRUCTIONS)

    mcp = MCPServer(
        # Named for what it DOES, not for what it sits on. The store underneath
        # is SQLite today and could be a warehouse tomorrow; the contract this
        # server offers is the same either way, and a name like "sqlite-tools"
        # or "tennis-db" would leak an implementation detail into every prompt.
        name="semantic-layer",
        title="Semantic Layer",
        description=("Governed metrics, authority ranked documents, analytical "
                     "playbooks, and relationship traversal. Ask business "
                     "questions in plain language; definitions, exclusions and "
                     "caveats are enforced by the layer."),
        instructions=instructions,
        version="1.0.0",
    )

    @mcp.tool(
        description=(
            "Orientation for the Baseline Tennis Co. marketing domain. Returns the "
            "domain overview, the question archetypes with the playbook for each, "
            "the list of governed metrics, and the rules that resolve conflicts "
            "between sources.\n\n"
            "WHEN TO USE: at the start of any question where you are unsure what "
            "exists or which archetype applies. It is cheap.\n"
            "WHEN NOT TO USE: when you already know the metric id and the "
            "archetype. Go straight to get_playbook and get_metric.\n\n"
            "Read the 'What this layer cannot answer' section of the overview. It "
            "is authoritative about known data gaps.")
    )
    def get_started() -> dict:
        return T.get_started()

    @mcp.tool(
        description=(
            "List every governed metric with its id, one line description, allowed "
            "dimensions, additivity, and direction of goodness.\n\n"
            "WHEN TO USE: to find the right metric_id, or to check which dimensions "
            "a metric permits before calling get_metric.\n"
            "WHEN NOT TO USE: as a substitute for get_metric. This returns "
            "definitions, never values.")
    )
    def list_metrics() -> dict:
        return T.list_metrics()

    @mcp.tool(
        description=(
            "Return the step by step procedure for a question archetype. Valid "
            "archetypes: 'metric-lookup', 'metric-decline-diagnosis', "
            "'policy-question'"
            + (", 'graph-traversal'." if enable_graph else ".")
            + "\n\nWHEN TO USE: after classifying the question and BEFORE calling "
            "any other tool. The playbook tells you which tools to call and in "
            "what order.\n"
            "WHEN NOT TO USE: never skip it for a multi step question. Diagnosis "
            "and policy questions in particular go wrong without it.\n\n"
            "Follow the returned steps in order. Do not substitute your own "
            "procedure.")
    )
    def get_playbook(archetype: str) -> dict:
        return T.get_playbook(archetype)

    @mcp.tool(
        description=(
            "Search the catalog of available assets (metrics, documents, tables) by "
            "meaning and by keyword. Returns what exists, what it means, and the "
            "access path for each.\n\n"
            "WHEN TO USE: when you do not know whether the layer covers a concept, "
            "or which asset answers it.\n"
            "WHEN NOT TO USE: to get a metric value (use get_metric) or a document "
            "body (use search_knowledge).\n\n"
            "CRITICAL: if the response contains 'known_gap', the layer DECLARES it "
            "does not have this data. That is an authoritative answer, not a search "
            "failure. Follow the response_rule and do not substitute a nearby "
            "metric.")
    )
    def discover_assets(query: str, limit: int = 6) -> dict:
        return T.discover_assets(query, limit)

    @mcp.tool(
        description=(
            "Search marketing documents for what they SAY: rules, definitions, "
            "plans, narrative.\n\n"
            "NEVER USE THIS TO GET A NUMBER. If the question asks for a value, a "
            "rate, a count or a total, it is a get_metric question no matter how "
            "it is phrased. A user saying 'search the documents for our revenue' "
            "or 'look up the open rate in the email overview' is naming the wrong "
            "source: documents carry stale, gross, unfiltered figures that were "
            "true when written and were never restated. The governed metric "
            "overrides them, and quoting a document figure as the answer is a "
            "factual error even when the user asked you to.\n\n"
            "WHEN TO USE: policy questions, definitions, documented plans, campaign "
            "narrative, and looking for a planned change that explains a metric "
            "move. ALSO use it for questions about how documents RELATE to each "
            "other or to what they govern: what replaced this, what else is in "
            "this family, which policies apply to a category, who owns it, what "
            "to check before changing something. You do not need to phrase those "
            "differently or call anything else; this tool searches the text and "
            "the document graph together and returns both. NOTE that this "
            "widens WHICH DOCUMENT QUESTIONS this tool answers. It does not "
            "widen it to numbers: naming a document does not turn a request for "
            "a figure into a document question, and 'what was the revenue in "
            "<named deck>' is still get_metric.\n"
            "WHEN NOT TO USE: any question whose answer is a number. Also not for "
            "a figure quoted INSIDE a document, including a campaign recap deck: "
            "retrieve the narrative, get the number from get_metric, and name the "
            "discrepancy.\n\n"
            "RANKING: results are ordered by AUTHORITY first, similarity second. "
            "Answer from canonical documents only. The corpus deliberately contains "
            "a superseded policy draft that scores high on similarity; if "
            "'stale_versions_present' appears, say the stale version exists and is "
            "not in force.\n\n"
            "RELATIONSHIPS: when the question names a document, family, team or "
            "product category the registry knows, a 'related' section reports how "
            "it connects to other documents. Those are relationships, not "
            "answers: the text answers what was asked and 'related' says how the "
            "documents sit relative to each other. A 'superseded_by' edge means "
            "the text you are reading may be out of date even though it reads as "
            "current.")
    )
    def search_knowledge(query: str, limit: int = 6) -> dict:
        return T.search_knowledge(query, limit)

    cohort_doc = (
        "\n- cohort: a cohort HANDLE string from build_audience (for "
        "example \"exposed\", \"comparison\", \"traced\", \"control\", or an "
        "audience handle you named), or an explicit "
        "list of customer ids. The metric is computed on just those customers, "
        "through the governed definition. This is the ONLY sanctioned way to turn "
        "a cohort into a number. PREFER THE HANDLE: cohorts run to thousands of "
        "ids and pasting them back is slow and error prone."
        if enable_graph else "")

    @mcp.tool(
        description=(
            "Compute a governed metric. THE ONLY WAY TO GET A NUMBER on this "
            "server.\n\n"
            "WHEN TO USE: any question whose answer is a value, rate, count, "
            "total, average or comparison. This holds even when the question "
            "mentions a document ('what does the deck say revenue was'), mentions "
            "relationships ('revenue from referred customers', 'how many were "
            "referred'), or is framed as analysis ('cross-sell analysis: what is "
            "AOV for racket buyers'). If the answer is a number, it comes from "
            "here.\n"
            "WHEN NOT TO USE: for what a policy or document SAYS, which is "
            "search_knowledge. For selecting a population, which is "
            "build_audience. For co-purchase rates, which is category_affinity.\n\n"
            "Parameters:\n"
            "- metric_id: from list_metrics (for example 'net_revenue', "
            "'email_open_rate').\n"
            "- dimensions: list of dimension names to group by, for example "
            "['channel'] or ['segment']. Must be allowed by the metric; invalid "
            "dimensions are rejected with an explanation you can correct from.\n"
            "- period: 'last_month' (default, means the last COMPLETE month), "
            "'last_6_months', 'trailing_12m', 'YYYY-MM', 'YYYY-MM..YYYY-MM', "
            "'all_time'.\n"
            "- filters: dict of dimension to value, for example "
            "{'segment': 'competitive'}."
            + cohort_doc + "\n\n"
            "RETURNS the value(s) plus a full interpretation payload: computation "
            "notes and the filters applied, benchmark band comparison, direction of "
            "goodness, seasonal notes, required caveats, companion metrics, and a "
            "confidence block.\n\n"
            "YOU MUST read the payload before answering. Specifically:\n"
            "- 'direction': for cac and refund_rate LOWER IS BETTER, so a rise is "
            "unfavorable.\n"
            "- 'confidence': when level is low, surface the reason in your answer "
            "body. Small samples must be labeled directional; coverage holes must "
            "be named and never extrapolated across.\n"
            "- 'required_caveats': every one belongs in your answer.\n"
            "- 'additive': false means NEVER average across periods; re derive.")
    )
    def get_metric(metric_id: str, dimensions: list[str] | None = None,
                   period: str | None = None, filters: dict | None = None,
                   cohort: str | list[int] | None = None) -> dict:
        return T.get_metric(metric_id, dimensions, period, filters, cohort)

    @mcp.tool(
        description=(
            "Search campaign BRIEFS: why each campaign ran, who it targeted, what "
            "the offer was, who owned it, and what was learned afterwards.\n\n"
            "Parameters: query (free text over name, objective, offer, learnings), "
            "segment, category, channel, campaign_type, period, limit.\n\n"
            "WHEN TO USE: any question about past campaign performance, finding a "
            "comparable campaign, or understanding why something ran. A revenue "
            "figure without the objective cannot be judged a success or failure.\n"
            "WHEN NOT TO USE: to get campaign REVENUE. Each result includes a "
            "ready made get_metric call under get_performance; use that.\n\n"
            "ALWAYS FOLLOW check_for_recap. A campaign with a written recap deck "
            "has a THIRD number in play: decks quote GROSS revenue over all rows "
            "and are almost never restated, so the deck on someone's desk will "
            "disagree with the governed figure. Run the search_knowledge call "
            "given under check_for_recap, and if a recap exists, report the "
            "governed net number AND name the discrepancy with its reason. "
            "Reporting only the governed number leaves the reader holding a deck "
            "that contradicts you.\n\n"
            "A null 'learnings' means the campaign is still running and no "
            "retrospective exists yet. That is an honest absence.")
    )
    def search_campaigns(query: str | None = None, segment: str | None = None,
                         category: str | None = None, channel: str | None = None,
                         campaign_type: str | None = None,
                         period: str | None = None, limit: int = 12) -> dict:
        return T.search_campaigns(query, segment, category, channel,
                                  campaign_type, period, limit)

    @mcp.tool(
        description=(
            "Cross-sell affinity: what else do buyers of a category buy?\n\n"
            "Parameters: category (required: rackets, strings, shoes, apparel, "
            "services), segment (optional), period (default trailing_12m).\n\n"
            "WHEN TO USE: cross-sell and bundling questions, 'what should we "
            "recommend to someone who bought X'.\n"
            "WHEN NOT TO USE: for category revenue or order counts, which are "
            "metric questions; use get_metric with the category dimension.\n\n"
            "READ LIFT, NOT SHARE. Share is the percentage of anchor buyers who "
            "also bought the other category, but popular categories look affine to "
            "everything. Lift compares that share to the rate among all buyers, so "
            "lift near 1.0 means there is NO real affinity however high the share "
            "looks. Findings are correlational.")
    )
    def category_affinity(category: str | None = None,
                          segment: str | None = None,
                          period: str | None = "trailing_12m") -> dict:
        return T.category_affinity(category, segment, period)

    @mcp.tool(
        description=(
            "Select WHICH CUSTOMERS, two ways: by ATTRIBUTES (filter criteria) "
            "or by RELATIONSHIPS (a closed set of traversal operations). Returns "
            "cohort handles and counts. NEVER computes a metric.\n\n"
            "ATTRIBUTE MODE (combine freely, at least one required): "
            "bought_category, not_bought_category, bought_racket_type "
            "(power/control/balanced), segment, region, price_tier, "
            "lapsed_category_months (no purchase in that category for N months, "
            "the 'due for a replacement' shape), active_only, "
            "inferred_churned_only, min_orders, handle (name it), period.\n\n"
            "RELATIONSHIP MODE (pass `operation`, arguments in `params`; do not "
            "mix with attribute criteria):\n"
            "- 'referral_chain': walk referral chains. params: {'root': "
            "customer_id} or {'channel': acquisition_channel}, optional "
            "'max_depth' (default 5).\n"
            "- 'chain_stats': chain depth and size statistics by grouping. "
            "params: {'group_by': 'acquisition_channel'}. The one operation that "
            "returns STATISTICS rather than a cohort.\n"
            "- 'exposed_cohort': customers exposed through an edge to a "
            "condition. params: {'edge_type': 'referred_by', 'condition': "
            "'referrer_churned'}.\n"
            "- 'trace_cohort': customers reached through a campaign to a "
            "product. params: {'campaign_id': int, 'product_id': int} or "
            "{'campaign_id': int, 'recalled': true}.\n\n"
            "WHEN TO USE: 'who should I send this to', 'who is due for a "
            "restring', 'which customers are at risk' (attributes); chains of "
            "unknown or unbounded depth, propagation or exposure through "
            "relationships, tracing a population across three or more entity "
            "hops (relationships).\n\n"
            "WHEN NOT TO USE: when the question is really a metric, and there "
            "are two disguises to refuse. First, 'an audience of everyone' is "
            "not a selection, it is the whole base, and a total over it is a "
            "plain get_metric call. Second, COUNTING over a relationship is not "
            "a traversal: 'how many customers were referred', 'revenue from "
            "referred customers' are get_metric questions, because they are one "
            "hop deep. A user saying 'trace the referral network' has guessed at "
            "the mechanism; ignore the guess and look at the DEPTH the question "
            "actually needs. Depth 1 is never a traversal.\n\n"
            "COMPOSITION RULE, MANDATORY: this tool SELECTS. It does NOT "
            "compute. Every cohort is registered under a short HANDLE listed in "
            "the result (attribute audiences under your `handle`; relationship "
            "cohorts typically \"exposed\"/\"comparison\" or "
            "\"traced\"/\"control\"). To get a rate or revenue figure, call "
            "get_metric with cohort=\"<handle>\". Do NOT paste id lists. A "
            "number computed any other way is NOT the governed metric.\n\n"
            "NO CONTACT DETAILS EXIST in this warehouse: customer ids and counts "
            "only, no export. An audience describes PAST BEHAVIOUR, not a "
            "propensity score.")
    )
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
                       period: str | None = "all_time",
                       operation: str | None = None,
                       params: dict | None = None) -> dict:
        if operation is not None and not enable_graph:
            # The demo decline: with --no-graph the relationship path is
            # withheld, and the correct behaviour is a capability decline that
            # names what is missing, not an error and not an approximation.
            return {
                "capability_decline": True,
                "reason": (
                    "No registered access path supports relationship traversal "
                    "on this server. Answering would require walking the "
                    f"'{operation}' relationships and then computing a governed "
                    "metric on the resulting cohort, and that path is not "
                    "available. Say so plainly; do not approximate it with a "
                    "single-level aggregation."),
            }
        return T.build_audience(
            bought_category=bought_category,
            not_bought_category=not_bought_category,
            bought_racket_type=bought_racket_type, segment=segment,
            region=region, price_tier=price_tier,
            lapsed_category_months=lapsed_category_months,
            active_only=active_only, inferred_churned_only=inferred_churned_only,
            min_orders=min_orders, handle=handle, period=period,
            operation=operation, params=params)

    _register_prompts(mcp, enable_graph)
    return mcp


def build_baseline_server() -> MCPServer:
    """No semantic layer. Raw SQL and unwrapped search only.

    This exists to make the before/after comparison concrete: same questions,
    same data, no governed definitions, no authority metadata, no caveats.
    """
    mcp = MCPServer(
        name="semantic-layer-baseline",
        title="Raw Access (control, no semantic layer)",
        description=("Direct SQL and unwrapped document search, with no governed "
                     "definitions. Exists only as the experimental control for "
                     "the before and after comparison."),
        instructions=BASELINE_INSTRUCTIONS,
        version="1.0.0",
    )

    @mcp.tool(
        description=(
            "Run a read only SQL query against the Baseline Tennis Co. SQLite "
            "warehouse. SELECT and WITH only.\n\nSchema:\n" + T.BASELINE_SCHEMA)
    )
    def run_sql(query: str, limit: int = 200) -> dict:
        return T.run_sql(query, limit)

    @mcp.tool(
        description="Search marketing documents. Returns the matching text chunks."
    )
    def naive_search(query: str, limit: int = 6) -> dict:
        return T.naive_search(query, limit)

    return mcp


# ---------------------------------------------------------------------------
# MCP prompts: the sample questions as slash-command style shortcuts.
# ---------------------------------------------------------------------------

SAMPLE_QUESTIONS = [
    ("email_open_rates", "How did email open rates do last month?"),
    ("revenue_last_month", "What was revenue last month?"),
    ("why_signups_dropped", "Why did new customer signups drop last month?"),
    ("refund_policy", "What is our refund policy?"),
    ("cac_by_channel", "What is our CAC by channel?"),
    ("repeat_rate_health", "Is our repeat purchase rate healthy?"),
    ("spring_campaign_revenue", "How much revenue did the spring campaign drive?"),
    ("aov_by_segment",
     "What's the average order value for competitive players vs recreational?"),
    ("segment_value", "Which segment is worth more long term?"),
    ("december_dip", "Did the December revenue dip mean something is wrong?"),
    ("revenue_per_email_trend", "How is revenue per email trending?"),
    ("competitive_criteria", "What are the criteria for the competitive segment?"),
]

GRAPH_QUESTIONS = [
    ("referral_chains_by_channel",
     "Which acquisition channel produced our best referral chains, counting "
     "referrals of referrals?"),
    ("referral_churn_propagation",
     "Are customers referred by someone who churned more likely to churn "
     "themselves?"),
    ("recall_impact_trace",
     "Trace everyone who bought the recalled string through the spring campaign. "
     "Did their repeat rate diverge?"),
]

HONESTY_QUESTIONS = [
    ("nps", "What's our NPS?"),
    ("paid_social_cac_history", "What was our CAC on paid social two years ago?"),
    ("services_aov", "What's the AOV for the services category?"),
    ("churn_last_quarter", "How many customers churned last quarter?"),
    ("revenue_forecast", "What will revenue be next quarter?"),
]


def _register_prompts(mcp: MCPServer, enable_graph: bool) -> None:
    """Register sample questions as MCP prompts.

    Each prompt returns the question text, so selecting it in Claude Desktop asks
    the question and the normal tool procedure takes over.
    """
    items = list(SAMPLE_QUESTIONS) + list(HONESTY_QUESTIONS)
    if enable_graph:
        items += GRAPH_QUESTIONS

    for name, question in items:
        def make(q: str):
            def prompt_fn() -> str:
                return q
            return prompt_fn

        fn = make(question)
        fn.__name__ = name
        mcp.prompt(name=name, description=question)(fn)


# ---------------------------------------------------------------------------


def main() -> None:
    """One server. Run it with no flags and you get the whole semantic layer.

    The flags exist for the before-and-after demonstration, not for normal use:

      --baseline    strips the semantic layer entirely, leaving raw SQL and
                    unwrapped search. This is the experimental control.
      --no-graph    withholds relationship traversal, so the layer has to decline
                    a traversal question instead of answering it.

    A deployment registers this ONCE with no flags.
    """
    ap = argparse.ArgumentParser(
        description="Semantic layer MCP server: governed metrics, authority "
                    "ranked documents, and analytical playbooks.")
    ap.add_argument("--baseline", action="store_true",
                    help="DEMO ONLY: strip the semantic layer, expose raw SQL "
                         "and unwrapped search as the experimental control")
    ap.add_argument("--no-graph", action="store_true",
                    help="DEMO ONLY: withhold relationship traversal so the "
                         "layer must decline traversal questions")
    # Accepted for backward compatibility with existing registrations. The graph
    # is on by default now, so this is a no-op.
    ap.add_argument("--enable-graph", action="store_true",
                    help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.baseline and args.no_graph:
        ap.error("--baseline already excludes the graph; --no-graph is redundant")

    if args.baseline:
        server = build_baseline_server()
    else:
        # Fail fast with a readable message rather than mid-conversation.
        get_catalog()
        server = build_semantic_server(enable_graph=not args.no_graph)

    server.run(transport="stdio")


if __name__ == "__main__":
    main()
