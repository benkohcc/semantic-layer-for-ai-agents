# Baseline Tennis Co. Semantic Layer POC

A fully local proof of concept of a semantic layer for AI agents. Claude connects
over MCP and answers marketing questions about a fictitious online tennis store by
consulting governed metrics, authority ranked documents, and analytical playbooks
instead of guessing from raw data.

Everything runs on your machine. SQLite for data and traversal, ChromaDB for
vectors. No Docker, no cloud, no API key for the demo.

**New here?** [../OVERVIEW.md](../OVERVIEW.md) explains the concept, the problem,
and the value in plain language, with no setup or code. This README is the
operator's manual: how to run it, how it is built, and how it was verified.

## The claim

Two things are being demonstrated, and both are checkable.

**Milestone 1: machine enforced semantics change answer correctness.** The same
question over the same data produces a different answer depending on whether the
definitions are enforced. Governed metrics apply exclusions the agent would miss,
authority ranking picks the policy that is actually in force, interpretation
payloads attach the judgment, and declared gaps produce honest declines instead of
confident numbers.

**Milestone 2: a new access path arrives through content, not code.** Graph
traversal is added without touching the router or the descriptor schema. One
playbook, two edge descriptors, some ontology entries, and a closed operation
set on the audience tool.

## Setup

Five commands.

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python data/seed.py      # generates the database, documents, benchmarks
.venv/bin/python cli.py index      # embeds documents and catalog entries
.venv/bin/python eval/verify_layer.py            # 313 checks, no API key needed
.venv/bin/python eval/verify_knowledge_graph.py  # 16 checks, no API key needed
```

Seeding is deterministic (fixed seed 42) and ends by asserting that every planted
signal, coverage requirement, and deliberate gap is present. If an assertion
fails, seeding fails loudly rather than shipping broken data.

`verify_layer.py` runs 313 checks over the whole layer with no model involved. It
is the fastest way to confirm the install is sound.

## Register with Claude

**One server.** Run it with no flags and you get the whole semantic layer.

### Claude Desktop

Add to `claude_desktop_config.json`:

macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "semantic-layer": {
      "command": "/ABSOLUTE/PATH/TO/baseline-tennis-poc/.venv/bin/python",
      "args": ["/ABSOLUTE/PATH/TO/baseline-tennis-poc/mcp_server.py"]
    }
  }
}
```

Replace `/ABSOLUTE/PATH/TO` with the real path, then quit Claude Desktop
completely (Cmd-Q, not just closing the window) and reopen it.

### Claude Code

```bash
claude mcp add semantic-layer -- /ABS/PATH/.venv/bin/python /ABS/PATH/mcp_server.py
```

### The demo flags

The same server takes two flags, and both exist only for the before-and-after
comparison. Normal use needs neither.

```bash
python mcp_server.py                # the whole layer, 9 tools. This is the product.
python mcp_server.py --no-graph     # DEMO: withhold traversal, force a decline
python mcp_server.py --baseline     # DEMO: strip the layer, raw SQL only
```

To run the demo script below, register the two demo modes as additional entries
under different names, and enable one at a time:

```json
"semantic-layer-nograph": { "command": "...", "args": ["...mcp_server.py", "--no-graph"] },
"semantic-layer-baseline": { "command": "...", "args": ["...mcp_server.py", "--baseline"] }
```

### Verify with the MCP Inspector

```bash
npx @modelcontextprotocol/inspector .venv/bin/python mcp_server.py
```

Nine tools, and `run_sql` is never among them.

One caveat if you use the Inspector's `--cli` mode: it does not forward extra
arguments to the server, so the demo flags are silently dropped and every mode
looks identical. To check the gating, use the protocol probes, which drive the
server directly:

```bash
.venv/bin/python eval/probe_mcp.py      # 9 semantic / 2 baseline; --no-graph declines, not hides
.venv/bin/python eval/probe_cohort.py   # cohort handles over the real protocol
```

## The tools

Nine tools on one server. Every sample question below is taken from the evaluation
suite, so each is a question the tool actually served in a passing run.

| Tool | When to use it | Sample question |
|---|---|---|
| `get_started` | At the start of a question when you do not know what exists or which approach fits. Cheap, so when in doubt, call it. | *Why did new customer signups drop last month?* (orient before diagnosing) |
| `list_metrics` | When you only need metric names, or to check which dimensions one allows. A third the size of `get_started`. | *Which brand is most profitable?* (is there a margin metric, and what can it split by?) |
| `get_playbook` | After classifying the question and BEFORE calling anything else. Essential for multi step work. | *Why did new customer signups drop last month?* (diagnosis must check seasonality first) |
| `discover_assets` | When you do not know whether the layer covers a concept at all. A `known_gap` result is the authoritative answer, not a failed search. | *How many customers churned last quarter?* (is churn even a metric here?) |
| `get_metric` | **Any question whose answer is a number**: value, rate, count, total, comparison. Even when the question names a document or mentions relationships. | *What was revenue last month?* |
| `search_knowledge` | For what a document SAYS, and for how documents RELATE: what replaced this, which policies cover a category, who owns it. Searches text and the document graph together. Never for a number, however the question is phrased. | *What is our refund policy?* / *Which policies apply to racket discounting?* |
| `search_campaigns` | Any question about past campaign performance, or finding a comparable campaign. A revenue figure with no objective cannot be judged a success. | *What did we learn from our restring campaigns?* |
| `category_affinity` | Cross sell and bundling. Read LIFT, not share: popular categories look affine to everything. | *What should we cross-sell to someone who just bought a racket?* |
| `build_audience` | WHICH customers, two ways. Attributes: who to target, who is due, who is at risk. Relationships (`operation` + `params`): chains of UNKNOWN DEPTH, exposure, 3+ hop tracing; depth 1 is never a traversal. Then measure with `get_metric`. | *Who should I send a power-racket promotion to?* / *Are customers referred by someone who churned more likely to churn themselves?* |

### Where the boundaries get confused

Each of these was a real misroute found by
[eval/probe_routing.py](eval/probe_routing.py). They are the cases where the
user's own phrasing points at the wrong tool. Most were fixed in the tool
descriptions; the one that was not is called out below the table.

| The question sounds like | Correct tool | Not | Why |
|---|---|---|---|
| *Search the documents for our revenue figure* | `get_metric` | `search_knowledge` | Documents carry stale, unfiltered figures. The governed metric wins even when the user names the document. |
| *How many customers were referred to us?* | `get_metric` | `build_audience` (relationship mode) | Mentions relationships, but it is a count over an attribute. One hop deep. |
| *Trace the referral network to count referrals* | `get_metric` | `build_audience` (relationship mode) | "Trace" is the user guessing at mechanism. Judge the DEPTH the question needs, not its vocabulary. |
| *Cross-sell analysis: AOV for racket buyers?* | `get_metric` | `category_affinity` | Framed as cross sell, asks for a metric slice. |
| *Build an audience of everyone, total revenue?* | `get_metric` | `build_audience` | "Everyone" is not a selection. Selecting only pays when the criteria narrow the population. |
| *What is our margin after costs?* | *decline* | `get_metric` | Gross margin exists, operating costs do not. The layer says so rather than presenting gross as profit. |

**The one that still misroutes.** *"What was the revenue in the spring campaign
recap deck?"* routes to `search_knowledge` when the first call should be
`get_metric`. Three consecutive probe runs, and it behaves identically on the
description as it stood before the document graph was added, so this is settled
behaviour rather than a regression.

It is arguably defensible: the question does name a document, and "what figure is
printed in that deck" is a legitimate document question. The reason the probe
counts it as a failure is specific to this deck, whose registry entry records that
its figures are gross and unfiltered, so the printed number and the governed
number disagree. The required answer retrieves the narrative AND calls
`get_metric`, then names the discrepancy.

Worth noting the probe scores the FIRST call only. An agent that starts at
`search_knowledge` and then calls `get_metric` produces exactly the right answer
and still scores as pulled, which is a limit of the probe rather than proof of a
broken boundary: both milestones pass 25/25 on the full eval, where the composed
answer is what gets graded.

### The composition rule

| Step | Tool | Returns |
|---|---|---|
| 1. Select a population | `build_audience` (attributes or relationships) | A cohort **handle**, never a number |
| 2. Measure it | `get_metric` with `cohort="<handle>"` | The governed metric, computed by the engine |

Three tools select, one computes. A number worked out by hand from an id list is
not the governed metric even when the arithmetic is right, and the eval scorer
fails it on those grounds.

## Demo script

Enable **one server at a time** so the contrast is unambiguous.

### Beat 1: the raw SQL trap

Enable `semantic-layer-baseline` only. Ask:

> How did email open rates do last month?

The agent counts opens over delivered and reports **35.15 percent**. Prompted by
the column name it may then self-correct to about 25.8 percent by excluding
machine opens, which is a good instinct and still wrong: it has not excluded
transactional mail, which is operational and has structurally higher engagement.

Switch to `semantic-layer-nograph`. The governed answer is **23.28 percent**, with the
MPP caveat attached and click rate offered as the decision metric. The naive
figure was **51 percent too high**.

Then ask:

> What was revenue last month?

Baseline reports **573,361 dollars**. It found the refunds on its own, which is
more than the usual strawman does, and it still missed the QA test rows and the
wholesale business line. Governed: **425,966 dollars**. Overstated by **35
percent**, from a query that looked careful.

This is the honest shape of the comparison. A capable agent gets partway there
from column names alone; what it cannot infer is which rows this business excludes
from marketing reporting and why.

### Beat 2: a decline the layer earns, and one it does not

With `semantic-layer-baseline`:

> What's our NPS?

Baseline declines correctly. It finds the sentence in the data and reporting notes
saying no satisfaction data is collected, and reads it back.

**Worth being straight about this:** that is not the semantic layer working. The
document says the answer in plain prose and any retrieval system can find it. The
layer's contribution here is that the decline is *guaranteed* by a declared
`absent_concept` rather than dependent on the right document surfacing.

The declines that baseline cannot reach are the ones with no document behind them:

> How long has this product been out of stock?

Governed answers: current stock level is available, stock *history* is not, no
movement log exists, do not estimate a duration. That boundary lives in the metric
descriptors, not in any prose a search can retrieve.

### Beat 3: the stale document that does not know it is stale

Ask both servers:

> What is our refund policy?

The corpus contains a 2024 policy with a 30 day window and a 15 percent restocking
fee. It was never adopted. **Nothing in the file says so.** Open it: there is no
"draft" header, no "superseded" note, no hint of any kind. It reads as a complete,
confident policy, because that is what a draft policy looks like.

Baseline has no way to tell the two apart and ranks purely on similarity.

The governed server demotes it to `draft` and flags it, using the document
registry. Ask the same question about stringing turnaround for the harder version
of the case: two SLAs, **both genuinely in force at different times**, so neither
is wrong and only the effective date separates them.

### Beat 4: the same question three ways

This is the strongest beat. Ask all three servers:

> Are customers referred by someone who churned more likely to churn themselves?

**Baseline (`semantic-layer-baseline`) answers confidently, and gets it backwards.**

It writes SQL, invents its own churn definition, and reports:

```
No Referrer:                  13.58% churn  (1,829 of 13,467)
Referred by Churned Customer:  9.55% churn  (53 of 555)
Referred by Active Customer:   9.00% churn  (358 of 3,978)
```

Conclusion: *"customers referred by someone who churned are NOT more likely to
churn themselves. In fact, the pattern suggests the opposite."*

Every number there is real. The conclusion is wrong. It compared 9.55 against
9.00, called a 0.55 point gap a finding, used a churn definition nobody agreed to,
and never checked whether the referral came before or after the churn.

**Milestone 1 (`semantic-layer-nograph`) declines.** No registered access path supports
relationship traversal, and it names what the question would need. No number, no
approximation, no fabrication.

**Milestone 2 (`semantic-layer`) answers.** The graph selects the exposed
cohort, the governed repeat purchase rate is computed on it **through the metrics
engine**, and the answer is **11.7 points in the opposite direction to baseline**:
70.1 percent repeat for referees of churned referrers against 81.8 percent for
referees of active ones. With the temporal ordering checked (the referral precedes
the churn window for 582 of 643), framed as correlational, and the inferred churn
definition disclosed.

Three servers, one question, same data. Confidently wrong, honestly silent,
correctly answered.

### Beat 5: seasonality

> Did the December revenue dip mean something is wrong?

The answer is no, and the layer knows why: December is intentionally quiet, budget
and send volume are cut, and the dip happens every year by design.

## Other things worth asking

Registered as MCP prompts, so they appear as shortcuts in Claude Desktop.

| Question | What it exercises |
|---|---|
| How did email open rates do last month? | machine open exclusion, MPP caveat, click rate companion |
| Why did new customer signups drop last month? | decomposition by channel, then the documented budget pause |
| How much revenue did the spring campaign drive? | governed net beats the deck's gross figure |
| Which segment is worth more long term? | LTV, not AOV, which ranks them in the opposite order |
| What's the AOV for the services category? | a real number with a small sample warning attached |
| What was our CAC on paid social two years ago? | a coverage hole named rather than extrapolated across |
| How many customers churned last quarter? | churn disclosed as inferred, not observed |
| What will revenue be next quarter? | forecasting declined as out of scope |
| Which channel produced our best referral chains? | recursive chain depth (graph server) |

## What a marketer can actually ask

The 20 eval questions were written alongside the layer, so they prove correctness
rather than coverage. [eval/marketer_questions.yaml](eval/marketer_questions.yaml)
is a separate set of 74 questions a marketing person would ask on an ordinary
Monday, classified by whether the layer supports them.

```bash
.venv/bin/python eval/verify_marketer_coverage.py    # 74/74, no model needed
```

**74 of 74 either answer or decline with a stated reason. None fall through
silently**, which is the outcome that matters: a question that is neither answered
nor refused leaves the agent improvising.

| Category | What it covers |
|---|---|
| Performance reporting | revenue, AOV, signups, refunds, email, CAC, retention, order and customer counts |
| Diagnosis | why a metric moved, seasonality, recall impact |
| Product performance | which rackets sell, by type, tier and head size |
| Cross-sell and affinity | what racket buyers also buy, with lift |
| Audience building | who to send a promotion to, who is due for a restring, who is at risk |
| Campaign planning | past campaign performance, comparable campaigns, timing |
| Correctly unanswerable | NPS, forecasts, creative, keywords, propensity, contact details |

### Three question shapes the first build could not touch

Product, cross-sell and targeting questions all failed originally, and not because
the data was missing. The data supported every one of them; there was simply no
registered path, and no declared gap either, so they fell through.

> **Which rackets do competitive players prefer?**
> Control frames, 3 to 1 over power. Every metric stopped at CATEGORY, so this was
> unanswerable until `products` gained `racket_type`, `head_size_sq_in` and
> `price_tier`, and the order based metrics gained a product grain.

> **What should we cross-sell to racket buyers?**
> Strings, at 1.12 lift. Note that apparel has a HIGHER co-purchase share and a
> lift below 1.0: it is simply popular, not affine. `category_affinity` reports
> both numbers precisely so a popular category is not mistaken for an opportunity.

> **New power racket arriving. Who should I send it to?**
> `build_audience` finds around 1,000 competitive players who bought a racket more
> than 12 months ago and are still active, and their LTV measured through
> `get_metric` runs well above the segment average. Selection and measurement stay
> separate: the audience path never computes the value itself.

### Campaign history: why it ran, who it targeted, what was learned

Originally 62 of 63 campaigns had dates, a channel and a budget, and nothing else.
A marketer could pull a campaign's revenue but could not say what it was FOR, so
the number could not be judged and comparable campaigns could not be found.

Campaigns now carry a brief: `objective`, `target_segment`, `target_category`,
`offer`, `owner`, `status` and post-campaign `learnings`. `search_campaigns`
searches all of it and hands back the exact `get_metric` call for the governed
numbers, plus a `check_for_recap` pointer to any recap deck that will disagree.

```bash
.venv/bin/python cli.py tool search_campaigns '{"query":"restring"}'
```

A campaign question has two halves and the layer keeps them apart: the BRIEF says
why it ran, the METRIC says what it produced, and the deck is a third source that
usually quotes gross. A running campaign has a null `learnings`, which is an
honest absence rather than a gap to work around.

## Closing gaps versus declaring them

An audit found brand, margin, stock and supplier questions falling through: not
answered, and not declared as gaps either. The tempting fix was to declare them,
which would have been honest and wrong. A tennis retailer knows who makes its
products, what they cost and whether they are in stock. Declaring those as gaps
would have been treating "my generator did not produce it" as a fact about the
business.

So the data went in instead:

| Added | Makes answerable |
|---|---|
| `products.brand` across seven brands | which brands sell, and to whom |
| `products.unit_cost` | `gross_margin` and `margin_rate` |
| `products.stock_level`, `lifecycle_stage` | availability, what is new, what is clearing |
| `suppliers` table with lead times and terms | who supplies what, and why stock arrives when it does |

The brand split is real rather than decorative: performance brands take **79
percent** of competitive players' orders against **28 percent** of recreational
ones. Margin rate spans 40 percent on performance brands to 71 percent on own
label, which is what makes "which brand is most profitable" a question with a
defensible and slightly counter-intuitive answer.

**Two gaps stayed declared, because they are real.** There is no stock history, so
"are we out of stock" is answerable and "how long have we been out of stock" is
not. And gross margin covers product cost only, so net profit genuinely cannot be
computed. The boundary between those pairs is exactly the interesting part.

## Governance lives outside the document

The first version of this corpus had every document declare its own authority:
`Authority: canonical` in the header, `Status: HISTORICAL` on the stale ones, and
`NOT ADOPTED` in a title. That made the authority ranking demo worthless. A naive
keyword search could identify the superseded document by reading line three, so
the semantic layer was not adding anything.

**Real documents do not work that way.** A policy written in 2024 was simply the
policy. Nobody went back and stamped it when the replacement landed, because the
person writing the replacement had no way to reach every copy of the old one. A
superseded document reads exactly like a current one, with the same confident tone
and the same internal consistency, because it *was* current when it was written.

So the documents now contain only content. Every statement about status,
precedence and supersession lives in
[document_registry.yaml](semantic-layer/domains/marketing/catalog/document_registry.yaml),
which stands in for whatever system a real business uses: a CMS, a wiki hierarchy,
an approval workflow. Retrieval reads the registry and never the document header.

Precedence is status, then effective date within a lineage, then similarity.

```bash
.venv/bin/python cli.py tool search_knowledge '{"query":"what is our refund policy"}'
```

The 2024 refund policy comes back at **similarity rank 4** and is demoted to
`draft` purely from the registry. Nothing in the file gives it away. Compare
against the baseline server, where `naive_search` has no registry and ranks purely
on similarity.

### Three lineages, three different problems

- **Refund policy.** A 2024 draft that was never adopted. It reads as a complete,
  confident policy with a 30 day window and a restocking fee, because that is what
  a draft policy looks like.
- **Stringing SLA.** The harder case: both versions were *genuinely in force*, so
  neither is wrong and status alone cannot separate them. Only the effective date
  can. An answer about 2025 performance should use the 2025 SLA; an answer about
  current commitments must not.
- **Media plan.** A recurring quarterly document where only the newest issue is
  operative. Same author, same template, same tone. Citing Q2 against a July
  signup drop would be confidently wrong.

### The registry as a graph, and why there is no classifier

The registry already recorded which document replaced which, which family each
belongs to, and who owns it. Those are edges, and they were only ever read one at
a time as a ranking key. Reading them as a graph makes a class of question
answerable that vector similarity cannot reach at all:

| Question | Similarity | Graph |
|---|---|---|
| *What is our refund policy?* | answers it | adds "a 2024 draft exists in this lineage" |
| *What supersedes the 2024 refund policy?* | finds refund text | answers it |
| *Which policies apply to racket discounting?* | **confident and useless** | answers it |

The last row is the point. The answer is in no single passage, so there is no
embedding good enough to find it: it is in how the documents sit relative to each
other.

`search_knowledge` therefore runs both searches every time and reports what each
contributed, in a `retrieval` block. It does NOT decide between them.

That was not the first design. A router was built, which read the question and
picked a strategy, and it was measured against realistic phrasings rather than the
ones it was written for:

| Approach | Score | How it failed |
|---|---|---|
| Keyword rules | 6/15 | Missed *"what's downstream of the refund policy"* because no rule said "downstream". Missed *"what supersedes the 2024 refund policy"*, which is the literal name of an edge. |
| Entity resolution | 9/15 | Naming an entity does not separate *"what does the refund policy say"* from *"what depends on the refund policy"*. Both name the same entity. |
| Run both | n/a | The question dissolves. |

Both attempts assumed the searches were alternatives. They are not: similarity
returns TEXT and traversal returns RELATIONSHIPS, and one answer can carry both.
Once both always run, you cannot miss a traversal you always perform, and an
unnecessary one costs a few hops over a few hundred in memory nodes.

The keyword version also had a failure mode worth naming, because it is the one
that would have shipped: falling back to similarity on *"if we change the refund
window, what breaks"* returns confident, well formed, useless chunks about refund
windows, and nothing in the payload signals that the traversal never happened.

**What decides whether relationships appear is the graph, not the phrasing.**
*"What's downstream of the refund policy"* works because "refund policy" resolves
to a node with edges, not because "downstream" was anticipated.

One filter remains, and it is about which nodes contribute rather than which
strategy runs: a bare category word is weak evidence. *"How long do customers have
to return a racket"* mentions rackets, but attaching every discounting policy to
it is noise. Scope nodes contribute only when the question is about scope;
document and lineage nodes always contribute, because naming a document is
deliberate.

Verified by [eval/verify_knowledge_graph.py](eval/verify_knowledge_graph.py), 16
deterministic checks, no model: 11 relationship phrasings including all 9 the
classifier missed, 2 plain questions that must stay quiet, 2 unknown subjects that
must return nothing, and the governing policies query.

### Coverage, stated honestly

`supersedes`, `in_lineage` and `owned_by` are derived from fields that already
existed and cost nothing. **`governs` has to be authored**, because nothing in a
document states which categories it applies to, and it is declared in the registry
for the same reason status is: a document is not a reliable narrator about its own
scope.

It is currently authored for the **discounting slice only**: three documents of
29. 24 of 29 are reachable by some edge, but that is mostly ownership, which is a
single hop attribute lookup wearing a graph costume. Scope questions outside
discounting will not resolve until those edges are written. A document without a
`governs` edge is a coverage gap, not a claim that it governs nothing, and the
verifier prints these numbers rather than letting a green run imply full coverage.

## The document corpus

29 documents, 14,318 words, 58 chunks. Every document is at least 50 lines,
because anything shorter is too thin to retrieve within, too thin to chunk, and
too thin for a near miss to be genuinely near.

The original corpus was 15 documents averaging 153 words with one chunk each.
Sparsity manufactured false confidence: "what brands do we carry" returned the
Segmentation Guide at a distance the layer treated as relevant, because with
nothing better in the index something is always the nearest neighbour.

Beyond the three lineages, two more retrieval traps:

- **A buried passage.** The Stringing Operations Manual runs ten sections across
  several chunks. The junior frame tension sits in one subsection deep inside it,
  so finding the right document is not enough.
- **A plausible near miss.** Transactional email operations reports a 40 percent
  open rate. It surfaces on any email question and is the wrong system entirely.

## Cohort composition, and why it uses handles

Milestone 2's central mechanism is that the graph selects a cohort and the metrics
engine measures it. The obvious implementation is for a relationship operation to return
customer ids and the agent to pass them to `get_metric`. That does not survive a
real cohort.

The comparison group for question 14 is **3,876 customers**. Echoing that back as
a tool argument is tens of thousands of tokens of integers, per call, twice. In
testing it was slow enough that the question timed out at ten minutes.

So every cohort is registered under a short **handle**:

```python
build_audience(operation="exposed_cohort", ...)  # registers "exposed" and "comparison"
get_metric("repeat_purchase_rate", cohort="exposed")
get_metric("repeat_purchase_rate", cohort="comparison")
```

The ids are resolved server side. Explicit id lists still work, so the handle is
ergonomics rather than a gate, and the payload shrank from 36KB to 5.5KB.

Two guardrails came out of getting this wrong first:

- The payload includes **no sample of ids**. An earlier version returned the first
  20 as `sample_ids`, and the agent passed those to `get_metric` as if they were
  the cohort. It produced a confident, clean, entirely wrong answer: a 1.8 point
  gap measured on 20 customers instead of the real 15.1 points on 3,876. A partial
  id list is worse than none, because it looks like the cohort.
- `get_metric` **rejects an id list that is a strict subset** of a registered
  cohort, naming the handle to use instead. The same mistake made another way now
  fails loudly rather than computing.

## Adding a metric is a content change

`email_delivered_rate` exists only as a YAML descriptor. No Python was written for
it. It carries a declarative `sql` block:

```yaml
sql:
  source: email_sends
  value: "SUM(e.delivered) * 1.0 / NULLIF(COUNT(*), 0)"
  sample_size: "COUNT(*)"
  where: "e.email_type != 'transactional'"
```

That is the whole implementation. Restart the server and ask "what is our
deliverability" and it answers, with the caveats, companion metric, benchmark
comparison, and confidence block all attached by the same machinery every other
metric uses. Dimensions work too, including the customer join that `segment`
implies.

The ten original metrics keep hand written compilers because their shapes are not
expressible declaratively: cross table ratios, trailing 12 month windows, and a
LEFT JOIN denominator that has to retain customers who never ordered. Anything
that fits the declarative form needs no code.

```bash
.venv/bin/python cli.py tool get_metric '{"metric_id":"email_delivered_rate","dimensions":["segment"]}'
```

## Repository layout

```
mcp_server.py            MCP server: instructions, tool descriptions, mode gating
cli.py                   seed, index, direct tool calls, ask, eval
src/
  catalog.py             loads the semantic layer into memory
  metrics_engine.py      compiles metric requests to parameterized SQL
  interpretation.py      attaches evaluation, framing, and confidence payloads
  retrieval.py           chunking, embedding, authority ranked search
  knowledge_graph.py     document relationships: supersedes, lineage,
                         ownership, governs. No classifier; see the file.
  tools.py               tool implementations, shared by MCP and eval
  graph.py               four closed traversal operations, recursive SQL over
                         the warehouse (an earlier networkx cache is gone)
  graph_tools.py         relationship operations with edge semantics attached,
                         reached through build_audience(operation=...)
  agent.py               eval only: in-process agent loop over the Anthropic API
semantic-layer/
  spine/entities.yaml    shared entities, cross domain definitions, absent data
  domains/marketing/
    DOMAIN.md            domain overview and "what this layer cannot answer"
    metrics/             10 metric descriptors
    catalog/             wrappers, tables, edges, and the document registry
    playbooks/           4 archetype procedures
    ontology/            concept mappings, combination rules, routing rules
    benchmarks/          GENERATED by seed.py from the seeded data
data/
  seed.py                deterministic generator, asserts every planted signal
  tennis_store.db        18,000 customers, 90,729 orders, 355,668 email sends
  documents/             15 marketing documents
eval/
  questions.yaml            25 questions with gold criteria
  run_eval.py               scorer + API driver (needs ANTHROPIC_API_KEY)
  run_eval_claude_cli.py    same scorer, driven by `claude -p` (no API key)
  verify_layer.py           313 checks over the whole layer, no model
  marketer_questions.yaml   74 questions a marketer would really ask
  verify_marketer_coverage.py  checks all 74 route or decline
  verify_knowledge_graph.py 16 checks on relationship retrieval, no model
  probe_mcp.py              MCP protocol probe: mode gating in all three modes
  probe_cohort.py           MCP protocol probe: cohort handles end to end
  probe_routing.py          do the tool DESCRIPTIONS alone route correctly
  rescore.py                replay saved transcripts against current criteria
```

## The data

Everything is synthetic, generated by a single script ([data/seed.py](data/seed.py),
about 4,000 lines), and none of it is random noise: the warehouse is built to be a
test bed, with every trap planted deliberately and every planted pattern asserted at
seed time.

### The inventory

| Table | Rows | What it holds |
|---|---|---|
| `customers` | 18,000 | segment, region, acquisition channel, and `referred_by`, which encodes the referral graph |
| `orders` | 91,216 | 83,989 completed, 5,433 refunded, 1,794 test rows (2.0%); retail and wholesale channels |
| `order_items` | 115,695 | line items joining orders to products |
| `products` | 120 | rackets (30), strings (28), apparel (30), shoes (20), services (12), across seven fictional brands |
| `suppliers` | 5 | with lead times, referenced by the merchandising documents |
| `campaigns` | 63 | 41 lifecycle, 12 promotional, 10 seasonal, each with objective, target, budget, and learnings |
| `email_sends` | 356,002 | 202k campaign, 109k lifecycle, 44k transactional; open, machine-open, and click flags per send |
| `ad_spend` | 2,006 | daily spend by channel, with a deliberate 6-month hole in paid social |

Plus the document corpus: 29 markdown files, 14,318 words, every one over 50 lines,
governed externally by the registry. The documents assert nothing about their own
status, which is the point.

### The shape

- **24 complete months**, ending at the last complete month relative to when you
  seed, so "last month" questions work whenever you run it.
- **Seasonality is built into the curve**: March through May run hot for spring
  leagues, December dips by design because send volume is cut.
- **Segments**: 10,737 recreational, 7,263 competitive, with genuinely different
  behavior (basket size, category mix, lifetime value).
- **Acquisition**: five channels. Referral is the largest (5,637), and 4,533
  customers carry a `referred_by` edge, which is what the graph traverses.
- **Machine opens**: 32,473 of 123,962 total opens (about 26 percent) are proxy
  prefetches no human performed, flagged in a column the naive query never reads.

### How it stays honest

Three mechanisms keep the demo from passing by luck:

1. **Seed-time assertions.** `verify()` inside the seeder checks every planted
   pattern after generation: the referral chain depths, the churn contagion gap,
   the AOV-vs-LTV inversion, the signup drop matching the documented pause. If a
   pattern fails to materialize, seeding fails loudly rather than shipping a
   warehouse that cannot support its own demo.
2. **Published gold values.** The seeder writes [data/seed_facts.json](data/seed_facts.json)
   with the campaign ids, the recall date, the window bounds, and a `gold` block of
   correct answers. The eval resolves `{{gold.*}}` placeholders from it, so criteria
   never rot when the data is reseeded.
3. **Deterministic generation.** Same seed, same warehouse, so a failure is
   reproducible rather than a shrug.

### Planted traps

Each with exactly one hunting question in the eval:

- QA test rows and wholesale rows in `orders` (inflate naive revenue by 44 percent)
- About a quarter of email opens are machine opens from privacy proxies
- A superseded refund policy draft that scores high on similarity
- A recap deck quoting gross revenue where the governed metric is net
- A documented paid search budget pause matching a real 37 percent signup drop
- December seasonality
- Average order value ranking the segments opposite to lifetime value

### Planted gaps

Because knowing what you cannot answer is part of the job:

- No satisfaction, sentiment, or NPS data of any kind
- Paid social spend missing for the first 6 months
- Last touch attribution only, so no multi touch questions
- Services category under 30 orders a month, below the reliability threshold
- Churn not observed, only inferred from 12 months of purchase silence

### Planted signals for traversal

- Organic seeds referral chains averaging 3.21 depth against about 1.2 elsewhere
- Referees of churned referrers repeat about 15 points less often
- Buyers of the recalled string diverge about 16 points from a matched control

## Development

```bash
.venv/bin/python cli.py tools                 # list callable tools
.venv/bin/python cli.py tool get_metric '{"metric_id":"net_revenue","period":"last_month"}'
.venv/bin/python cli.py tool get_playbook '{"archetype":"policy-question"}'
.venv/bin/python eval/verify_layer.py         # 313 checks, no model
```

The `tool` subcommand matters: it verifies the semantic layer independently of any
model. When an answer is wrong, this tells you whether the layer or the model is at
fault.

## Running the scored eval

The eval scores both the answer text and the tool trace. There are two drivers,
and they share the same questions, gold criteria, and scorer.

### Without an API key (uses your Claude Code login)

`claude -p` can drive the MCP server directly, so the model comes from your
existing Claude Code subscription. This is billed to that account, not free, and
the runner prints what it spent.

```bash
.venv/bin/python cli.py eval --driver claude-cli                  # milestone 1, 25 questions
.venv/bin/python cli.py eval --driver claude-cli --milestone 2    # milestone 2
.venv/bin/python cli.py eval --driver claude-cli --only 1,7,16 -v
.venv/bin/python cli.py eval --driver claude-cli --baseline
```

Roughly 2 to 6 cents a question with `sonnet`, so a full 25 question gate lands
around $1.50. Override with `--model`.

Two things this driver has to compensate for, both properties of the CLI rather
than of the layer:

- **stdin must be closed.** `claude -p` inherits the parent's stdin and blocks
  forever if that is a live terminal. The runner passes `DEVNULL`.
- **`-p` mode answers tersely**, and left alone it reduces a metric question to
  the bare figure, dropping caveats the payload supplied. The runner appends a
  short verbosity instruction to restore conversational output. It adds no domain
  knowledge and no procedure: all steering still comes from the server
  instructions, tool descriptions, and playbooks.

### With an API key

```bash
export ANTHROPIC_API_KEY=sk-...
.venv/bin/python cli.py eval                   # milestone 1 gate: 20 questions
.venv/bin/python cli.py eval --milestone 2     # milestone 2 gate: graph enabled
.venv/bin/python cli.py eval --only 1,4,16 -v  # a subset, with tool traces
.venv/bin/python cli.py eval --baseline        # capture comparison transcripts
```

The API driver uses `src/agent.py`, an in-process loop that reuses the MCP
server's own instruction text so both drivers exercise identical content.

**A correct number reached the wrong way is a FAIL.** The scorer checks that
metric questions went through `get_metric`, that policy questions went through
`search_knowledge`, that raw SQL was never used, and that graph cohorts reached
the metrics engine through the `cohort` parameter rather than being counted by
hand. The trace is what proves the mechanism, and the mechanism is the point.

For honesty questions, a confident fabricated answer scores below a wrong but
caveated one. Questions 16 and 20 fail outright if any number appears.

Questions 21 to 25 cover the later capabilities:

| Q | Tests |
|---|---|
| 21 | Cross-sell. Apparel has a 66 percent co-purchase share against strings at 72, so on share alone it looks like a close second. Its **lift is 0.93**, meaning it is just popular. Recommending apparel is the failure. |
| 22 | Audience composition. Must build the audience AND measure it through `get_metric` with the cohort handle. A count alone does not say whether to spend money. |
| 23 | Product grain routing. Mentions a product preference, which pulls toward affinity or audience building, but is answerable with a dimension on a governed metric. |
| 24 | Campaign briefs. Has **no numeric answer at all**: it is entirely about what the registry records as the objective and the learnings. |
| 25 | Margin. Genuinely ambiguous, and both readings are correct: dollars put Baseline first on volume, rate puts own label first at 69 percent. The test is whether the answer names the other measure. |

At milestone 1, questions 13 to 15 are scored against a *different* criteria block:
they must decline and name the missing capability. At milestone 2 the same
questions must answer fully, and questions 1 to 12 must still pass, which is the
routing regression check.

### What the gates actually show

Both gates pass **25 of 25** on the `claude -p` driver:

```
MILESTONE 1 GATE: PASSED   25 passed, 0 failed of 25   $1.60
MILESTONE 2 GATE: PASSED   25 passed, 0 failed of 25
```

Questions 21 to 25 were added later, and for a reason worth recording. A usage
audit across 21 full runs found `category_affinity` had been called **zero
times**. Not because it was redundant, and not because the agent was avoiding it:
none of the original 20 questions asks a cross-sell question. Three capabilities
added after the original plan (cross-sell, audience building, campaign history)
were covered by `verify_layer.py`, which needs no model, but had never been
exercised by an AGENT. Those are different tests: the layer having a capability is
not the same as the agent finding and using it.

The milestone 2 traces show the composition pattern doing its job rather than the
answer arriving by luck:

```
Q13  graph=[chain_stats]                     metrics=[]
Q14  graph=[exposed_cohort]   metrics=[repeat_purchase_rate x2]
Q15  graph=[trace_cohort]     metrics=[repeat_purchase_rate x2]
```

One graph call to select, two metric calls to measure, once per cohort. Q13 uses
no metric at all, correctly: chain depth is a graph statistic, not a governed
number. The scorer independently checks that the `cohort` parameter was actually
used, so a right answer computed by hand from an id list still fails.

Questions 13 to 15 decline cleanly at milestone 1, naming the missing access path,
and answer correctly at milestone 2 through graph traversal composed with the
metrics engine. Questions 1 to 12 pass at both, which is the routing regression
check. Questions 16 to 20 pass at both.

Expect some run to run variance. `claude -p` occasionally compresses a metric
answer toward the bare figure despite the verbosity instruction, dropping caveats
the payload supplied, which fails a criterion that requires them. That is the CLI
harness, not the layer: Claude Desktop is conversational by default. When a run
does dip, `eval/verify_layer.py` and `eval/rescore.py` tell you which it was.

Run `eval/verify_layer.py` to separate the two. It checks the same 20 questions'
data paths with no model at all, so a failure there is a layer bug and a failure
only in the scored eval usually is not.

### Real bugs these runs found

Every one of these was a content or plumbing fault the no-model verification had
missed, and each is now covered by a check in `verify_layer.py`:

- **An undiscoverable filter.** `campaign_id` worked on `net_revenue` but nothing
  advertised it, so the agent declined an answerable campaign revenue question.
  Every metric now declares `available_filters`, surfaced in `list_metrics`.
- **An ambiguous empty result.** A campaign filter over the default period returns
  nothing because the campaign ran earlier. The agent read that as "campaign
  attribution is unavailable". The `no_data` reason now names the period as the
  likely cause and says to re query the campaign's own window.
- **A silently ignored filter.** `revenue_per_email` accepted filters and dropped
  them, returning a number that looked narrowed and was not. It now rejects them
  and explains why (its numerator and denominator come from different tables).
- **A census counted as a sample.** `min_sample` fired on `new_customer_signups`,
  labelling "74 paid search signups" as unreliable when it is exact. Count metrics
  now declare `is_census`.
- **An over-decline.** Asked how many customers churned, the agent refused because
  no churn metric exists, when the layer supports the question through a disclosed
  inference. The ontology now carries an `answer_shape` telling it to answer.
- **A partial cohort.** Described above under cohort handles: the worst of the set,
  because it produced a confident wrong number rather than an error.

## One server, and how the tool count was arrived at

### One server, named for what it does

The server is `semantic-layer`. Register it once, with no flags, and you have the
whole thing: governed metrics, authority ranked documents, playbooks, campaign
history, audience building, and relationship traversal. Nine tools.

The name is deliberate. It describes the **function**, not the store underneath.
The data lives in SQLite today and could live in a warehouse tomorrow, and the
contract this server offers is identical either way. A name like `sqlite-tools` or
`tennis-db` would leak an implementation detail into every prompt and would be
wrong the first time the backend changed.

Two flags exist, and both are for the demonstration rather than for use:

| Invocation | Tools | Purpose |
|---|---|---|
| `mcp_server.py` | 10 | **The product.** Everything. |
| `mcp_server.py --no-graph` | 9 | Demo: withhold traversal so the layer must decline |
| `mcp_server.py --baseline` | 2 | Demo: strip the layer entirely, the experimental control |

An earlier version shipped three separately named servers and defaulted the graph
OFF, which made a demo artifact look like the product. It is one server now, and
the complete build is what you get by default.

### Nine tools, and how that number was arrived at

Tool count is a real cost: every tool is another thing the agent has to choose
between, and a wrong choice is a wrong answer. So the question for each one is
whether it earns its slot.

We checked usage across 21 full evaluation runs and found two tools that were
**never called once**. That is the kind of evidence worth acting on, so we looked
at both.

`campaign_detail` was genuinely redundant: it added exactly ONE field over
`search_campaigns`, a delivery block. That is navigation cost with no capability
behind it, so it was folded in and the tool removed. Delivery context now arrives
inline on every search result.

`category_affinity` was unused for a different reason. It computes co-purchase
with lift, which `get_metric` structurally cannot: `get_metric` slices one metric
by a dimension, while affinity is a co-occurrence across customers. It went
uncalled because none of the 20 evaluation questions ask a cross-sell question,
not because it duplicates anything. Kept.

The rest were each tested for merge potential:

| Tool | Could it merge? | Verdict |
|---|---|---|
| `get_started` | orientation, called 228 times | keep |
| `get_metric` | the only number path, 493 calls | keep |
| `get_playbook` | into `get_started`? | **no**: 5 playbooks at ~5k chars each. Folding them in adds 26k chars to every orientation call when a question needs one. This is lazy loading. |
| `list_metrics` | into `get_started`? | **content is duplicated**, but the payload is 6x smaller. Kept as the cheap path when you only need metric names. |
| `discover_assets` | into `search_knowledge`? | **no**: one searches the CATALOG (what exists), the other searches DOCUMENT TEXT. Merging gives one tool that sometimes returns assets and sometimes prose. |
| `search_knowledge` | see above | keep |
| `search_campaigns` | absorbed `campaign_detail` | keep |
| `category_affinity` | into `get_metric`? | **no**, different computation |
| `build_audience` | into `get_metric`? | **no**: selects a population, deliberately cannot measure it |
| `query_graph` | into `build_audience`? | **MERGED**: once traversal moved into recursive SQL, both tools selected populations from the same store and returned the same handles. The mechanism distinction that justified two tools had died with the in-memory graph. `chain_stats` rides along with an explicit note that it returns statistics, not a cohort. |

The one merge that was justified got made. `list_metrics` is the remaining
duplication and it is a deliberate one: a cheap call that avoids pulling 22KB of
orientation when you want a list of names.

### The deeper reason the count stays low

Every tool here is a **governed path**, not a convenience wrapper. There is one
way to get a number, one way to reach a document, one way to select a population.
The alternative design, a tool per metric or a tool per document type, would run
to dozens and would push the governance decisions back onto the agent.

Nine tools where each one answers a different *kind* of question is easier to use
than five that each do several things ambiguously.

## How robust are the tool descriptions?

Descriptions are the primary steering surface, so it is worth knowing whether they
work on their own rather than being carried by the server instructions and the
playbooks. [eval/probe_routing.py](eval/probe_routing.py) isolates them: the agent
gets the tool descriptions and **nothing else**, and is asked only which tool it
would call first.

```bash
.venv/bin/python eval/probe_routing.py    # needs the claude CLI, a few cents
```

Two tests, and the second is the one that found real problems.

**Neutral phrasing: 16/16.** Including the misroute traps. "How many customers
were referred to us" goes to `get_metric`, not the graph, because the description
says counting is a metric question regardless of the word "referred".

**Adversarial phrasing: 4/8 on the first run.** These are worded the way someone
speaks when they have already decided, wrongly, what they want. The failures all
shared one shape: **when the user named a document, the document tool won**, even
for a governed metric value.

| Phrasing | Went to | Should be |
|---|---|---|
| "Search the documents for our current revenue figure" | `search_knowledge` | `get_metric` |
| "Look up the email open rate in the email program overview" | `search_knowledge` | `get_metric` |
| "What was the revenue in the spring campaign recap deck?" | `search_knowledge` | `get_metric` |
| "Build an audience of everyone and tell me total revenue" | `build_audience` | `get_metric` |

`search_knowledge` already said "WHEN NOT TO USE: to obtain a metric VALUE", but
it was buried mid-description while the opening line said "Search marketing
documents". When the user says "search the documents", the opening line wins.

Three fixes, all in the descriptions:

- **Front-load the prohibition.** `search_knowledge` now leads with NEVER USE THIS
  TO GET A NUMBER and names the exact phrasings that mislead.
- **Give `get_metric` a WHEN TO USE.** The most important tool on the server had
  neither section, so it was competing on its opening line alone. It now claims
  number questions explicitly, including ones that mention a document or a
  relationship.
- **Guard on depth, not vocabulary.** "Trace the referral network to find how many
  people each customer referred" pulled the traversal tool on the word "trace".
  The description (now on `build_audience`) says the user has guessed at the
  mechanism and that depth 1 is
  never a traversal.

**After: 8/8 adversarial, 16/16 neutral, and every tool has both a WHEN TO USE and
a WHEN NOT TO USE section.** Total budget is about 2,800 tokens of descriptions
plus 1,200 of server instructions.

The general lesson: a prohibition only works where the model is looking. Buried
three paragraphs down it loses to the opening sentence, and the opening sentence
is what a misleading phrasing latches onto.

## How the steering works

Claude Desktop does not let you edit the system prompt, so all orchestration lives
in the server:

1. **Server instructions** (the MCP `instructions` field) carry the procedure and
   the hard rules.
2. **Tool descriptions** carry when to use and when not to use, written directive
   and dense. This is the primary steering surface.
3. **Playbooks**, returned by `get_playbook`, script the multi step procedures.

Every honest decline traces to a content field rather than to model goodwill:
`cannot_answer`, `coverage`, `min_sample`, or a `DOMAIN.md` section. Adding a new
known limitation is a content edit.

## Milestone 2 is content, not code

The headline claim is that the graph access path required no router change and no
descriptor schema change. What milestone 2 added:

| Added | Kind |
|---|---|
| `semantic-layer/.../playbooks/graph-traversal.md` | content |
| `semantic-layer/.../catalog/graph_edges.yaml` | content |
| ontology trigger mappings and the negative routing rule | content |
| `src/graph.py`, `src/graph_tools.py` | the new access path itself |
| relationship operations behind the graph flag | parameters on `build_audience` |
| `cohort` parameter on `get_metric` | composition |

You can check the claim yourself:

```bash
grep -c "graph\|traversal\|referral\|chain" src/interpretation.py src/metrics_engine.py
```

Both return zero. The interpretation layer and the metrics engine contain no
knowledge of the graph at all, yet both serve the traversal questions: the graph
hands cohorts to `get_metric`, which computes and interprets them exactly as it
does any other request.

`catalog.py` gained one generic asset category (`edges`, handled identically to
`documents` and `tables`, nine lines) so edge descriptors are discoverable. It
contains no graph-specific rule, no operation names, and no edge ids.

Archetype routing did not change because there was nothing to change: the router
reads archetypes from playbook frontmatter, so dropping in
`graph-traversal.md` created a new archetype. The descriptor schema did not change
either, which is why `repeat_purchase_rate` needed only a
`cohort_filter_supported: true` flag in its existing `definition` block to
participate in composition.

## Non-goals

No web UI, no HTTP or SSE transport (stdio only), no dbt (a template compiler
stands in), no graph database (traversal is recursive SQL), no arbitrary graph query
language (a closed operation set), no auth, no multi domain, no telemetry.

Complexity belongs in the semantic content, not the plumbing.
