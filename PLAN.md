# PLAN.md — Semantic Layer POC: "Baseline Tennis Co."

Handoff plan for Claude Code. Build a fully local, runnable proof of concept of a semantic layer for AI agents, using a fictitious online tennis store's marketing domain. The primary interface is an **MCP server**: the user connects it to Claude Desktop or Claude Code and asks questions in natural language, with Claude acting as the agent and the semantic layer as its tools. Everything runs on the local machine.

The build has two milestones. **Milestone 1** proves that machine-enforced semantics change answer correctness (governed metrics, authority ranking, interpretation, conflict resolution). **Milestone 2** proves the layer extends to a new access path (graph traversal) through content additions alone: same router, same schema, one new tool. Build them in order and keep them separately demoable.

---

## 1. Objective and success criteria

Build a system where Claude (via MCP) answers marketing questions about Baseline Tennis Co. by consulting a semantic layer instead of guessing from raw data.

**Milestone 1 success criteria:**

1. The MCP server registers in Claude Desktop and Claude Code; all tools appear and are callable.
2. Asking Claude "How did email open rates do last month?" in Claude Desktop returns the correct number from generated data, with caveats and a good/bad judgment attached, via tool calls only.
3. All 12 milestone-1 questions (Section 8) produce correct, properly caveated answers.
4. Metric questions never touch raw SQL from the agent side; they resolve through the metrics compiler. The `run_sql` tool exists but is gated behind baseline mode.
5. A document question resolves to the canonical document, not the stale draft that is deliberately planted in the corpus.
6. Adding a new metric definition YAML (no code change, server restart allowed) makes a new question answerable.
7. Baseline comparison is demonstrable: starting the server with `--baseline` exposes only `run_sql` and `naive_search`, so the same question asked in Claude shows the before/after delta.
8. **Graceful decline:** at milestone 1, traversal questions (13 to 15) produce an explicit statement that no registered access path supports relationship traversal, not hallucinated SQL or fabricated answers.
9. **Honest limitations:** questions 16 to 20 (Section 8b) pass: known data gaps, thin samples, inferred definitions, and out-of-scope requests are disclosed with specific reasons and nearest alternatives, never papered over with confident numbers.

**Milestone 2 success criteria:**

10. Questions 13 to 15 pass with the graph access path enabled: correct traversal, and for cohort questions, the governed metric computed through the metrics engine on the graph-selected cohort (never recomputed inside graph code).
11. The milestone-2 diff touches only: seed data flags already planted, `query_graph` tool registration, one playbook, ontology entries, and catalog descriptors. Router code and the descriptor schema are unchanged. Verify this by diff inspection; it is the headline claim.
12. All milestone-1 questions including honesty checks still pass with the graph path enabled (no routing regressions; metric and policy questions must not misroute to the graph; the graph path must not erode honest declines).

**Constraints:**

- Python 3.11+, SQLite for data, ChromaDB (embedded) or sqlite-vec for vectors, networkx for the milestone-2 graph (in-memory, built from SQLite at server start), no Docker, no cloud infra, no graph database.
- MCP server built with the official `mcp` Python SDK (FastMCP), stdio transport.
- Semantic layer content is YAML/Markdown files in-repo. AI writes config, never code: answering new questions must require only content changes.
- The eval harness (not the demo) uses the Anthropic API (claude-sonnet-4-6) directly, key from `ANTHROPIC_API_KEY`. The MCP demo path requires no API key since Claude Desktop/Code is the model.
- No em dashes in any generated prose or documentation.

---

## 2. Repository layout

```
baseline-tennis-poc/
  README.md                       # setup + run instructions
  requirements.txt
  mcp_server.py                   # MCP server entry point (FastMCP, stdio)
  cli.py                          # secondary: seed, eval, direct ask for debugging
  /src/
    catalog.py                    # loads semantic repo into memory
    metrics_engine.py             # compiles metric requests to SQL
    retrieval.py                  # document chunking, embedding, search
    graph.py                      # milestone 2: networkx graph built from SQLite, traversal functions
    interpretation.py             # attaches semantics payloads to results
    tools.py                      # tool implementations shared by MCP server and eval agent
    agent.py                      # eval-only: in-process agent loop over tools.py via Anthropic API
  /semantic-layer/
    /spine/
      entities.yaml
    /domains/marketing/
      DOMAIN.md
      /catalog/                   # one YAML per asset
      /metrics/                   # metric definitions
      /playbooks/                 # 3 playbooks (markdown with YAML frontmatter)
      /benchmarks/benchmarks.yaml
      /ontology/concepts.yaml
  /data/
    seed.py                       # generates all sample data
    tennis_store.db               # SQLite, created by seed.py
    /documents/                   # generated marketing documents
  /eval/
    questions.yaml                # 12 questions + gold answers
    run_eval.py
```

---

## 3. Fictitious business: Baseline Tennis Co.

DTC e-commerce store selling rackets, strings, shoes, apparel, and stringing services. Operating 3 years. ~18,000 customers, US market. Marketing channels: email (lifecycle + campaigns), paid search, paid social, organic. Known business facts to encode in the semantic layer:

- Two customer segments matter: `competitive` (buys performance rackets, restrings often, high LTV) and `recreational` (occasional purchases, price sensitive).
- Seasonality: demand spikes March to May (spring leagues) and dips in December.
- A deliberate data quirk: the `orders` table includes `status = 'test'` rows from QA and `channel = 'wholesale'` rows that marketing metrics must exclude. This is the trap that raw-SQL agents fall into.
- Revenue definition dispute: finance counts gross revenue, marketing counts net of refunds. The governed metric uses net. A planted slide deck quotes the gross number. Combination rules must resolve this conflict in favor of the governed metric.

---

## 4. Sample data (data/seed.py)

Generate deterministically (fixed random seed = 42) so eval answers are stable.

**SQLite tables:**

- `customers` (18,000 rows): id, segment, region, signup_date, acquisition_channel, referred_by (nullable customer_id; ~25% of customers referred, chains up to depth 5, chain density varying by acquisition channel so question 13 has a real answer)
- `orders` (~55,000 rows): id, customer_id, order_date, gross_amount, refund_amount, channel (web/email/paid_search/paid_social/wholesale), status (completed/refunded/test). Include ~2% test rows and ~5% wholesale rows.
- `products` (~120 rows): id, category (rackets/strings/shoes/apparel/services), name, price, recalled (bool; exactly one string product flagged, promoted by the spring campaign)
- `order_items`: order_id, product_id, quantity, unit_price
- `email_sends` (~400,000 rows): campaign_id, customer_id, send_date, delivered (bool), opened (bool), machine_opened (bool), clicked (bool), email_type (lifecycle/campaign/transactional). ~35% of opens flagged machine_opened to simulate Apple MPP.
- `campaigns` (~60 rows): id, name, type, start_date, end_date, channel, budget
- `ad_spend` (daily rows per channel): date, channel, spend, clicks, attributed_signups

**Planted signal for the diagnosis question:** in the most recent full month, paid_search attributed_signups drop ~40% for 12 days, coinciding with a documented budget pause (see documents). Everything else stays flat. The "why did signups drop" question must be answerable by decomposition.

**Planted signals for milestone 2 (traversal questions):**

- **Referral churn cluster (question 14):** within one referral subtree (~300 customers), churned referrers' referees show a repeat_purchase_rate ~12 points below the non-exposed baseline, with referral dates preceding churn dates so temporal ordering is checkable. Outside that subtree, referee behavior matches baseline.
- **Recall divergence (question 15):** customers who bought the recalled string via spring-campaign-attributed orders show repeat rate ~10 points below a matched cohort who bought other strings through the same campaign. The divergence begins after the recall date.
- **Chain density (question 13):** one acquisition channel (organic) seeds measurably deeper referral chains (avg depth 2.8 vs 1.3 elsewhere) so "best referral chains by origin channel" has a defensible answer.
- seed.py must end with assertions that verify every planted signal exists in the generated data (the drop, the cluster deltas, the chain depth gap). If an assertion fails, seeding fails loudly.

**Coverage requirements (seed.py must assert all of these):**

Every eval question needs enough data behind it that its answer is statistically defensible, not an artifact of sparsity:

- Every metric x every allowed dimension value has >= 200 underlying rows in any single month (e.g. email opens per segment per month, orders per channel per month). No dimension slice used by questions 1 to 12 may be thin.
- Every campaign referenced by a question (spring campaign especially) has >= 5,000 sends and >= 400 attributed orders.
- The referral graph has >= 4,000 referred customers total; the question-14 exposed cohort >= 250 and its comparison cohort >= 2,000; the question-15 recalled-string cohort >= 300 and its matched control >= 300.
- Both segments are populated in every region and every acquisition channel, so segment splits never hit empty cells.
- All 24 months have complete data for every table; no partial months except the current one.

**Deliberately planted GAPS (for honesty testing, Section 8b):** the data must also contain known holes, and the semantic layer must know about them:

- No customer satisfaction or NPS data exists anywhere. No survey table, no metric.
- `ad_spend` for paid_social is missing for months 1 to 6 of the 24 (tracking started late). The CAC metric descriptor must declare this coverage limit.
- Attribution is last-touch only; the data cannot support multi-touch questions. Declared in the spine and in the CAC/signups descriptors.
- One low-volume slice is left intentionally thin: the `services` category has < 30 orders per month, below the reliability threshold, so category-level questions about services trigger small-sample warnings.
- Churn is not directly observed (no cancellation event; this is retail). "Churn" is an inference: no completed order in trailing 12 months. The definition lives in the spine, and every churn-adjacent answer must disclose it is inferred.

**Data must cover 24 months** ending at the last complete month relative to run date, so "last month" questions work whenever the POC runs.

**Documents (data/documents/, generated as .md files, 12 to 15 total):**

1. `email-program-overview.md` (canonical, current)
2. `refund-policy-2026.md` (canonical, effective date this year)
3. `refund-policy-2024-DRAFT.md` (stale, superseded, deliberately kept in the index; wrapper must mark it superseded)
4. `q3-media-plan.md` (canonical; documents the paid search budget pause with dates matching the planted data signal)
5. `spring-campaign-recap.md` (contains the GROSS revenue figure that conflicts with the governed net metric)
6. `segmentation-guide.md` (defines competitive vs recreational, thresholds)
7. `string-recall-notice.md` (canonical; names the recalled product, recall date matching the seeded flag, remediation offered)
8. `brand-voice.md`, `promo-calendar.md`, `stringing-service-faq.md`, `loyalty-program-terms.md`, plus 3 to 5 filler docs
Each document gets a companion wrapper entry in the catalog with: authority (canonical/draft/superseded), effective_date, supersedes, summary, when_to_use.

---

## 5. Semantic layer content

**Metrics (10, in /domains/marketing/metrics/, one YAML each):**

1. `net_revenue`: sum(gross_amount - refund_amount) where status='completed' and channel != 'wholesale'. Additive. Dimensions: month, channel, segment, category.
2. `email_open_rate`: unique human opens / delivered, excluding machine_opened and transactional. Non-additive (never average; re-derive). Weekly grain minimum.
3. `email_click_rate`: clicks / delivered, transactional excluded.
4. `new_customer_signups`: count customers by signup month. Dimensions: acquisition_channel, region, segment.
5. `aov`: net_revenue / completed order count. Non-additive.
6. `repeat_purchase_rate`: customers with 2+ completed orders in trailing 12m / active customers.
7. `cac`: ad_spend / attributed_signups, per channel. Direction: lower better.
8. `refund_rate`: refund_amount / gross_amount. Direction: lower better.
9. `revenue_per_email`: net revenue from email channel / delivered. Non-additive.
10. `segment_ltv`: avg cumulative net revenue per customer by segment.

Every metric YAML must include all four semantic blocks from the descriptor schema: definition/computation, evaluation (baseline range derived from the seeded data, direction, known seasonal patterns), framing (required caveats, companions, when_not_to_use), and access (metrics_engine only).

Benchmarks in `benchmarks.yaml` must be computed from the seeded data during seeding (seed.py writes them), so "is this good" judgments are internally consistent.

**Playbooks (4):**

1. `metric-lookup.md`: resolve concept -> governed metric -> compile -> attach evaluation + framing -> answer with judgment.
2. `metric-decline-diagnosis.md`: verify data freshness -> pull metric trend -> decompose by each allowed dimension -> compare to same period prior year -> search knowledge index for planned changes (media plans, promo calendar) -> synthesize cause.
3. `policy-question.md`: retrieve candidates -> rank by authority and effective_date -> answer from canonical only -> cite effective date -> flag if superseded versions exist.
4. `graph-traversal.md` (milestone 2): confirm the question is traversal-shaped (unknown-depth chains, path language, network position, propagation, 3+ entity hops) -> select traversal via `query_graph` -> **for cohort questions: graph selects the cohort, then the governed metric is computed on that cohort through `get_metric` with a cohort filter, never recomputed inside graph code** -> verify temporal ordering where causality is implied (referral must precede churn; purchases before recall date excluded from divergence claims) -> compare against a non-exposed or matched baseline cohort -> frame findings as correlational, never causal.

**Graph edge descriptors (milestone 2, in /catalog/):** `referred_by` and `purchased` edges get catalog entries like any asset: directionality, semantics (what an edge means, what its absence implies: null referred_by means organic/unattributed, not "no relationship"), known limitations (referral capture began at store launch; self-referrals impossible), when_to_use / when_not_to_use ("counting referrals is a metric question if depth is 1; use the graph only for chains").

**Ontology (`concepts.yaml`):** map natural language terms to assets. Examples: "open rate/opens" -> email_open_rate; "sales/revenue" -> net_revenue (with note: governed metric is net; gross figures in documents are non-authoritative); "signups/new customers/acquisitions" -> new_customer_signups; "refund policy" -> refund-policy-2026 document. Include combination rule: governed metric beats any number found in a document. Milestone 2 adds trigger mappings for the graph archetype: "referrals of referrals / chains / downstream" -> influence-analysis; "spread / at risk because of / exposed to" -> propagation; "trace everyone who / affected by" -> impact-trace; all three -> graph-traversal playbook + query_graph. Also add the negative rule: presence of relationships alone does not route to the graph; aggregations over attributes stay with the metrics engine.

---

## 5b. Epistemic honesty layer

The semantic layer must know what it cannot answer and say so with specifics. "I don't have that data" is a passing answer when true; a confident number built on a known gap is a failure. This is enforced through content and payloads, not model goodwill:

**Descriptor fields (add to the schema, required on every metric):**

```yaml
reliability:
  min_sample: 100              # below this, result ships with low_confidence flag
  coverage:                    # known data holes
    - "paid_social spend missing before <month 7>; CAC for that channel unavailable for those periods"
  definition_caveats:
    - "churn is inferred (no order in trailing 12m), not observed"
  cannot_answer:               # explicit negative scope
    - "multi-touch attribution (data is last-touch only)"
```

**Interpretation payload additions (interpretation.py):** every get_metric result includes a `confidence` block computed at query time: sample size vs min_sample, whether the requested period intersects a declared coverage hole, and whether any definition_caveats apply. When confidence is degraded, the payload states WHY in plain language, and the server instructions require the agent to surface it, not bury it.

**Domain-level negative scope (`DOMAIN.md` gets a "What this layer cannot answer" section):** no NPS/satisfaction data exists; attribution is last-touch; churn is inferred; forecasting is out of scope (the layer reports actuals, not predictions). `discover_assets` returns this section as a hit when a query matches a known-missing concept, so "what's our NPS" resolves to an authoritative "we don't have that and here's why" instead of a failed search.

**Honest-decline behaviors, in order of preference:**

1. **Answer with disclosed degradation** when data exists but is weak: small sample, partial coverage, inferred definition. State the number AND the limit ("services category AOV is $62, but with 28 orders last month this is below the reliability threshold; treat as directional").
2. **Partial answer with explicit boundary** when part of a question is answerable: "CAC by channel is available from month 7 onward; before that, paid_social spend was not tracked. Here are the covered months."
3. **Clean decline with explanation and nearest alternative** when nothing supports the question: "No satisfaction or NPS data is collected. The closest available signals are repeat_purchase_rate and refund_rate; neither measures sentiment."
4. **Capability decline** (milestone 1 traversal questions): name the missing access path, as already specified.

Server instructions codify the anti-pattern list: never estimate a number the tools did not return, never fill a coverage hole by extrapolation, never present an inferred definition as observed, never answer a forecast question with a trend restated as a prediction.

**Why this is content, not code:** every honest decline traces to a YAML field (cannot_answer, coverage, min_sample) or a DOMAIN.md section. Adding a new known limitation is a content edit, which keeps the honesty layer inside the core thesis.

---

## 6. System behavior (MCP-first)

**MCP server (mcp_server.py):** built with FastMCP, stdio transport. Claude Desktop or Claude Code is the agent; the server provides tools, instructions, and prompts. Because the user does not control Claude's system prompt in the desktop app, the orchestration logic must live in the server itself, in three places:

1. **Server instructions** (the MCP `instructions` field): a compact directive telling Claude how to use the layer: "For any Baseline Tennis Co. question, first call `get_started` if unsure, classify the question archetype, call `get_playbook`, then follow it step by step. Never estimate numbers; always resolve metrics through `get_metric`. Governed metrics override any figure found in documents."
2. **Tool descriptions**: each tool description carries its own usage rules (when to use, when not to). Descriptions are the agent's primary steering surface; write them like AMDR frontmatter, directive and dense.
3. **The playbooks themselves**, returned by `get_playbook`, which script multi-step procedures.

**MCP tools:**

- `get_started()`: returns DOMAIN.md, the archetype list, and available metrics. Cheap orientation call.
- `discover_assets(query)`: semantic + keyword search over catalog entries.
- `get_metric(metric_id, dimensions, period, filters)`: returns value(s) + full interpretation payload (computation notes, benchmark comparison, required caveats, companion suggestions).
- `search_knowledge(query)`: returns chunks + wrapper metadata (authority, effective_date, supersedes).
- `get_playbook(archetype)`: returns playbook text.
- `list_metrics()`: id, one-line description, allowed dimensions for each metric.
- `query_graph(operation, params)` (milestone 2 only): operations are a closed set, not arbitrary traversal code: `referral_chain(root|channel, max_depth)`, `exposed_cohort(edge_type, condition)` (e.g. referees of churned referrers), `trace_cohort(campaign_id, product_id)`, `chain_stats(group_by)`. Returns customer id lists + chain metadata + the edge descriptor semantics as interpretation payload. Backed by networkx in graph.py, graph built from SQLite at server start.

**Milestone gating:** server flag `--enable-graph` (default off for milestone-1 demos). When off, `query_graph` is not registered, and server instructions include: "If a question requires walking relationships (referral chains, spread, tracing affected customers), state that no registered access path supports relationship traversal and name what the question would require. Do not attempt it via other tools." This produces the graceful-decline behavior of success criterion 8. When on, instructions swap to routing guidance for the graph archetype.

**Cohort composition:** `get_metric` gains an optional `cohort` filter (list of customer ids, or a reference to the previous query_graph result) so graph-selected cohorts flow into governed metric computation. This is the composition pattern questions 14 and 15 test, and it must be the ONLY way graph results become numbers.

**Baseline mode:** `python mcp_server.py --baseline` starts the server exposing ONLY `run_sql(query)` (raw SQLite access, schema listing included in description) and `naive_search(query)` (vector search with no wrapper metadata). Register it as a second server entry (`baseline-tennis-raw`) so both can be toggled in Claude Desktop for live comparison. Never expose `run_sql` in the semantic server.

**MCP prompts (nice-to-have):** register the 12 sample questions as MCP prompts so they appear as slash-command style shortcuts in Claude Desktop.

**Registration:** README must include both configs:

- Claude Desktop: JSON snippet for `claude_desktop_config.json` with absolute paths and the venv python.
- Claude Code: `claude mcp add baseline-tennis -- python /abs/path/mcp_server.py`

**Metrics engine (metrics_engine.py):** loads metric YAMLs, compiles get_metric requests into parameterized SQLite queries. Template-based compilation is fine. Reject requests for dimensions or grains a metric does not allow, with an explanatory error the agent can read and self-correct from.

**Interpretation (interpretation.py):** after any metric result, compute benchmark comparison (within/above/below band), attach direction-of-goodness, seasonal notes, and required caveats. This payload is part of the tool result JSON so meaning travels with data into Claude's context.

**Retrieval (retrieval.py):** chunk documents (~500 tokens, overlap 50), embed with a local model (sentence-transformers all-MiniLM-L6-v2) into ChromaDB. Store wrapper metadata on every chunk. Also embed catalog entries for discover_assets. Embedding model loads lazily so server startup stays fast.

**tools.py:** pure-Python implementations of every tool, imported by both mcp_server.py and the eval agent. One implementation, two surfaces.

---

## 7. Interfaces

**Primary (demo): Claude Desktop / Claude Code via MCP.** The user asks questions in plain chat; Claude calls the tools. No API key needed on this path.

**Secondary (development and eval): CLI.**

```
python data/seed.py                       # generate db + documents + benchmarks
python cli.py ask "QUESTION"              # in-process agent over tools.py (needs ANTHROPIC_API_KEY)
python cli.py ask "QUESTION" --verbose    # show tool calls and payloads
python cli.py eval                        # run all 12 questions, score vs gold answers
python cli.py tool get_metric '{"metric_id": "net_revenue", "period": "last_month"}'   # call any tool directly, no LLM
```

The `tool` subcommand matters for debugging: it verifies the semantic layer independently of any model.

---

## 8. Sample questions and expected behavior (eval/questions.yaml)

Store each with: question, archetype, expected assets touched, gold answer criteria (not exact wording; checkable facts).

1. "How did email open rates do last month?" -> metric-lookup. Must exclude machine opens and transactional, state the band judgment, include the MPP caveat, suggest click rate.
2. "What was revenue last month?" -> metric-lookup. Must be NET, exclude test and wholesale, note governed definition.
3. "Why did new customer signups drop last month?" -> diagnosis. Must decompose by channel, identify paid_search, and cite the budget pause from q3-media-plan.md.
4. "What is our refund policy?" -> policy. Must answer from refund-policy-2026, cite effective date, not the 2024 draft.
5. "What is our CAC by channel?" -> metric-lookup. Lower-is-better framing, per-channel values.
6. "Is our repeat purchase rate healthy?" -> metric-lookup. Requires benchmark judgment, segment split suggestion.
7. "How much revenue did the spring campaign drive?" -> conflict test. The recap deck quotes gross; the answer must use the governed net metric and flag the discrepancy.
8. "What's the average order value for competitive players vs recreational?" -> metric-lookup with segment dimension.
9. "Which segment is worth more long term?" -> metric-lookup (segment_ltv) with interpretation.
10. "Did the December revenue dip mean something is wrong?" -> evaluation semantics test. Must invoke known seasonality, answer no.
11. "How is revenue per email trending?" -> metric-lookup, non-additive handling (re-derive per period, never average).
12. "What are the criteria for the competitive segment?" -> policy/knowledge. From segmentation-guide.md.

**Milestone 2 questions (tagged `milestone: 2` in questions.yaml):**

13. "Which acquisition channel produced our best referral chains, counting referrals of referrals?" -> influence-analysis. Milestone-1 expected behavior: graceful decline naming the missing capability. Milestone-2 pass: recursive chain depth/size via query_graph, rolled up by origin channel, organic identified (planted avg depth 2.8 vs 1.3).
14. "Are customers referred by someone who churned more likely to churn themselves?" -> propagation + composition. M1: graceful decline. M2 pass: exposed cohort selected via graph, repeat_purchase_rate computed on it THROUGH get_metric with cohort filter, compared to non-exposed baseline, temporal ordering respected (referral precedes churn), planted ~12pt delta found, framed as correlational.
15. "Trace everyone who bought the recalled string through the spring campaign. Did their repeat rate diverge?" -> impact-trace. M1: graceful decline. M2 pass: campaign->send->order->product cohort resolved, governed repeat rate on cohort vs matched control (other-string buyers, same campaign), planted ~10pt post-recall divergence found, recall notice document cited.

**8b. Honesty questions (tagged `honesty`, run in both milestone gates):**

16. "What's our NPS?" -> clean decline. Pass: states no satisfaction/NPS data is collected, offers repeat_purchase_rate and refund_rate as nearest signals while noting neither measures sentiment. FAIL if any number is produced.
17. "What was our CAC on paid social two years ago?" -> partial answer with boundary. Pass: states paid_social spend tracking began at month 7, provides covered months only, no extrapolation into the hole.
18. "What's the AOV for the services category?" -> disclosed degradation. Pass: gives the number WITH the small-sample warning (below min_sample threshold), labels it directional.
19. "How many customers churned last quarter?" -> definition disclosure. Pass: answers using the trailing-12-month inference AND discloses that churn is inferred, not observed, citing the definition.
20. "What will revenue be next quarter?" -> scope decline. Pass: states the layer reports actuals and forecasting is out of scope, may offer the historical trend explicitly labeled as not a prediction. FAIL if a forecast number is produced.

**Eval scoring:** score the tool trace as well as the answer text. A correct number reached through the wrong path (raw SQL, or a metric recomputed inside graph code) is a FAIL; the trace proving the mechanism is the point. For honesty questions, a confident fabricated answer is the worst possible failure and scores below a wrong-but-caveated one. Every planted trap and gap must have exactly one hunting question (test/wholesale -> Q2, machine opens -> Q1, stale draft -> Q4, gross-vs-net -> Q7, budget pause -> Q3, seasonality -> Q10, churn cluster -> Q14, recall -> Q15, chain density -> Q13, no-NPS -> Q16, spend hole -> Q17, thin slice -> Q18, inferred churn -> Q19, no-forecasting -> Q20).

`run_eval.py` modes:

- `python cli.py eval` : questions 1 to 12 with graph disabled, 13 to 15 expecting graceful declines, 16 to 20 honesty checks. This is the milestone-1 gate (20 questions).
- `python cli.py eval --milestone 2` : all 20 with graph enabled. Questions 1 to 12 must still pass (routing regression check), 13 to 15 must pass fully, 16 to 20 must still pass (the graph path must not erode honesty). This is the milestone-2 gate.
- Baseline transcripts: run questions 1 to 3 and 16 in baseline mode and save for the before/after demo (the baseline agent confidently inventing an NPS-adjacent answer from nothing is a strong demo beat).

---

## 9. Build order

**Milestone 1:**

1. Repo scaffold, requirements, README.
2. `data/seed.py` complete with ALL planted signals including milestone-2 flags (referred_by chains, recall, churn cluster) AND deliberate gaps (no NPS data, paid_social spend hole, thin services slice); seed once, never reseed between milestones. Ending assertions verify every signal, every coverage requirement, and every planted gap.
3. Semantic layer content: all 10 metric YAMLs including reliability blocks, catalog entries, 3 milestone-1 playbooks, ontology, DOMAIN.md with the negative-scope section, benchmarks writer.
4. `metrics_engine.py` + tests against seeded data (assert metric #1 excludes test/wholesale; assert cohort filter works).
5. `retrieval.py` + document ingestion.
6. `tools.py` + interpretation payloads; verify each tool via `cli.py tool` with no LLM involved.
7. `mcp_server.py` including `--baseline` mode and graceful-decline instructions; verify with MCP Inspector (`npx @modelcontextprotocol/inspector python mcp_server.py`), then register in Claude Desktop and Claude Code and manually test questions 1, 3, 4, 7, and 14 (expect decline).
8. `agent.py` + `eval/`; iterate until the milestone-1 gate passes (12 pass + 3 graceful declines + 5 honesty checks). Failures are content bugs first: fix YAML, restart server, retest. Touch code last.

**Milestone 2 (a separate commit or branch, so the diff IS the demo):**

9. `graph.py`: networkx graph from SQLite, the four closed operations.
10. Content additions: `graph-traversal.md` playbook, edge descriptors, ontology trigger mappings and the negative routing rule.
11. Register `query_graph` behind `--enable-graph`; add cohort filter plumbing to get_metric if not done in step 4.
12. Iterate until the milestone-2 gate passes (20/20, no regressions). Inspect the diff: if router code or the descriptor schema changed, the thesis claim failed; fix by moving logic into content.
13. README polish: setup in under 5 commands, both MCP registration configs verbatim, demo script covering baseline vs semantic vs graph-enabled (ask question 14 three ways: baseline flails, milestone 1 declines cleanly, milestone 2 answers; then ask question 16 in baseline vs semantic: baseline fabricates, semantic declines with alternatives).

## 10. Non-goals

No web UI, no HTTP/SSE transport (stdio only), no dbt (template compiler stands in), no graph database (networkx in-memory only), no arbitrary graph query language (closed operation set), no auth, no multi-domain, no telemetry DB. Keep total code under ~2,200 lines; complexity belongs in the semantic content, not the plumbing.
