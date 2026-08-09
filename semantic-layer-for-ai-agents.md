# Semantic Layer for AI Agents

Three deliverables: (1) explanation with worked examples, (2) ideal architecture, (3) prototype build plan.

---

## Deliverable 1: What the Semantic Layer Is and Why It Exists

### The problem

AI agents fail at answering business questions not because models are weak or data is missing, but because raw data carries no meaning. A warehouse table named `fct_orders_v3` does not tell an agent whether refunds are included, whether test accounts are filtered, or whether "revenue" here matches the "revenue" in the board deck. A folder of PowerPoints does not tell an agent which deck is canonical and which is an abandoned draft. Given raw access, an agent will retrieve *something*, compute *something*, and present it confidently. The result is plausible and wrong.

### What the semantic layer does

The semantic layer is a machine-readable knowledge system that sits between agents and data. For any information need, it answers four questions:

1. **What exists** — a catalog of every queryable asset: metrics, tables, documents, APIs
2. **What it means** — definitions, formulas, caveats, authority levels, freshness
3. **How to access it** — the governed path to each asset (metrics API, retrieval index, SQL)
4. **How to interpret and use it** — computation rules, benchmarks, analytical playbooks, framing requirements

The first three make answers *retrievable*. The fourth makes them *correct and useful*. Most semantic layer implementations stop at three, which is why they disappoint.

### What it is not

- Not a copy of your data. It stores metadata and pointers; data stays where it lives.
- Not documentation. Docs are human-readable and optional; the semantic layer is machine-enforced and travels with query results.
- Not a single ontology for the whole company. It is domain packages on a thin shared spine.

### Worked examples

**Example 1: A metrics question**

> User: "How did email open rates do last month?"

*Without semantic layer:* The agent finds an `email_events` table, writes SQL counting opens over sends, and reports 31%. It unknowingly counted Apple Mail privacy-proxy opens, included transactional emails, and has no idea whether 31% is good.

*With semantic layer:*
1. Ontology lookup maps "email open rate" to the governed metric `email_open_rate` in the lifecycle marketing domain package.
2. The metric definition specifies: unique opens / delivered (not sent), machine-opens excluded, transactional excluded, weekly grain minimum.
3. The metrics engine compiles and runs the correct query: 22.4%.
4. Evaluation semantics attach automatically: internal baseline 21–24%, direction-of-goodness noted, seasonal caveat ("July dips are expected").
5. Framing directives require the caveat that open rate is a directional signal post-MPP, and suggest click rate as the decision metric.

Answer: "22.4%, within the normal 21–24% band for this time of year. Note open rate is directional only since Apple MPP; click-through (2.9%, up from 2.6%) is the more reliable signal."

**Example 2: A "why" question spanning modalities**

> User: "Why did new merchant signups drop last week?"

*With semantic layer:*
1. Question classifier recognizes the archetype: `metric-decline-diagnosis`. It retrieves the matching playbook.
2. The playbook prescribes the procedure: verify pipeline health first, then decompose by channel and geography, then compare to prior-year seasonality, then check the campaign calendar and known-events log.
3. Each step resolves through the catalog: pipeline status from the ops API, signup metric decomposed by the dimensions the metric definition allows, campaign calendar retrieved from the knowledge index (where the wrapper marks it canonical and current).
4. Combination rules govern conflicts: the governed signup metric beats a number quoted in last week's slide deck.
5. The agent finds paid search signups fell 40% in two markets, and the campaign calendar shows a planned budget pause.

Answer: a diagnosis, not a recitation — "the drop is concentrated in paid search in DE/UK and matches the planned budget pause documented in the Q3 media plan; organic signups are flat."

**Example 3: A document/policy question**

> User: "What's our policy on merchant refund windows?"

*With semantic layer:* Retrieval hits four documents. The semantic wrappers rank them: one is marked `authority: canonical`, effective March 2026, superseding a 2024 version that is also in the index. The agent answers from the canonical document, cites its effective date, and ignores the stale draft that pure vector similarity would have ranked highest.

### The completeness test

Could a competent analyst who has never seen your business produce a correct, properly caveated answer using only what the semantic layer provides? If they would need to ask a colleague "wait, is that number good?" or "which of these docs is real?", the layer has a gap.

---

## Deliverable 2: Ideal Architecture

### Design principles

1. **Semantics as code.** All definitions in version-controlled text (YAML/Markdown). Reviewable, diffable, ownable. AI can write config; humans approve via PR.
2. **Schema universal, content domain-specific.** One fixed structure; each domain (marketing, finance, risk) fills its own package.
3. **Meaning travels with data.** Caveats, benchmarks, and framing rules are injected into the agent's context at query time, not left in documentation.
4. **Never copy data.** The layer holds metadata and pointers; the warehouse and document stores remain systems of record.
5. **Governed access paths only.** Agents request metrics, never raw fact-table SQL. Compilation happens in the metrics engine.

### Component architecture

```
┌─────────────────────────────────────────────────────────┐
│                      AI AGENTS                          │
└───────────────────────┬─────────────────────────────────┘
                        │ MCP
┌───────────────────────▼─────────────────────────────────┐
│              SEMANTIC LAYER SERVICE                     │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │   ROUTER     │  │   CATALOG    │  │  PLAYBOOKS   │   │
│  │ question →   │  │ asset        │  │ question-    │   │
│  │ concepts →   │  │ descriptors, │  │ archetype    │   │
│  │ archetype →  │  │ ontology,    │  │ procedures   │   │
│  │ assets       │  │ semantics    │  │              │   │
│  └──────────────┘  └──────────────┘  └──────────────┘   │
└──────┬──────────────────┬──────────────────┬────────────┘
       │                  │                  │
┌──────▼───────┐  ┌───────▼────────┐  ┌──────▼─────────┐
│ METRICS      │  │ RETRIEVAL      │  │ GOVERNED SQL / │
│ ENGINE       │  │ INDEX          │  │ APIs           │
│ (dbt SL/Cube)│  │ (pgvector)     │  │                │
└──────┬───────┘  └───────┬────────┘  └──────┬─────────┘
       │                  │                  │
┌──────▼──────────────────▼──────────────────▼───────────┐
│   EXISTING DATA ESTATE (unchanged)                     │
│   Warehouse · Document stores · Operational systems    │
└────────────────────────────────────────────────────────┘
```

### Component detail

**Semantic repository (Git).** The system of record. Structure:

```
/semantic-layer/
  /spine/                      # shared, cross-domain
    entities.yaml              # customer ID resolution, fiscal calendar
    access-patterns.yaml
  /domains/
    /lifecycle-marketing/
      DOMAIN.md                # domain overview, progressive disclosure entry
      /catalog/                # asset descriptors (one file per asset)
      /metrics/                # metric definitions
      /playbooks/              # question-archetype procedures
      /benchmarks/             # evaluation semantics
      /ontology/               # concept → asset mappings, combination rules
    /finance/
      ...
```

**Asset descriptor schema** (every asset, any modality):

```yaml
id: email_open_rate
type: metric                    # metric | table | document | api
domain: lifecycle-marketing
owner: team-lifecycle
freshness: daily
access: metrics_engine          # the only allowed path
definition: unique_opens / delivered
grain: weekly_min
dimensions: [channel, segment, region]
computation_semantics:
  additivity: non-additive      # never sum rates; re-derive
  null_handling: exclude_undelivered
evaluation_semantics:
  baseline: [0.21, 0.24]
  direction: higher_better
  known_patterns: ["July seasonal dip"]
framing:
  required_caveats: ["directional-only post Apple MPP"]
  preferred_companion: email_click_rate
when_to_use: "engagement trend questions"
when_not_to_use: "campaign ROI decisions — use click/conversion"
```

Document assets use the same shell with `authority`, `effective_date`, and `supersedes` fields.

**Router.** Two-stage: concept extraction against the ontology (which assets are relevant) and archetype classification (which playbook governs the procedure). Both are cheap LLM calls over small, in-context indexes.

**Metrics engine.** dbt Semantic Layer or Cube compiling metric requests into warehouse SQL. Definitions live in the Git repo; the engine consumes them. This is the single biggest error-reduction component.

**Retrieval index.** pgvector holding (a) document chunk embeddings with their semantic wrappers and (b) embeddings of catalog entries themselves, so vague queries can discover assets semantically.

**MCP server.** The delivery mechanism. Exposes tools like `discover_assets`, `get_metric`, `search_knowledge`, `get_playbook`. Every tool response embeds the interpretation payload — this is how meaning travels with data.

**Telemetry (Postgres).** Query logs, routing decisions, answer feedback. The raw material for improving playbooks and finding ontology gaps.

**Deliberately absent (until earned):** a graph database (YAML ontologies traversed in-context suffice for 1–3 domains), a dedicated vector DB (pgvector holds to tens of millions of chunks), any re-hosting of documents, and a spine designed up front (extract it from what domain packages duplicate).

---

## Deliverable 3: Prototype Build Plan

**Scope discipline:** one domain, ~10 metrics, ~20 documents, 3 playbooks, one agent surface. The prototype's job is to prove the answer-quality delta, not to cover the estate.

### Phase 0 — Pick the domain and the questions (Week 1)

- Choose one domain where you personally hold the expert knowledge (lifecycle marketing is the obvious candidate — the knowledge transfer cost is zero).
- Write down 15 real questions users ask in that domain, spanning the three modalities: pure metric lookups, diagnosis questions, and policy/document questions.
- For each, write the *gold answer*: what a correct, properly caveated response looks like. This is your eval set, and writing it forces the interpretation content into the open.
- Baseline: run all 15 through a vanilla agent with raw data access. Record the failures. This is your before/after evidence.

### Phase 1 — Semantic repository (Weeks 1–2)

- Stand up the Git repo with the directory structure above.
- Write descriptors for ~10 metrics and ~20 documents that the 15 questions touch. Fill all four semantic sections: definition, computation, evaluation, framing.
- Write 3 playbooks: `metric-lookup`, `metric-decline-diagnosis`, `policy-question`.
- Write the domain ontology file: concept → asset mappings for the terms in your 15 questions.
- Accept that the first drafts will be wrong; the eval loop fixes them.

### Phase 2 — Access paths (Weeks 2–3)

- Metrics: if a dbt project exists, define the 10 metrics in dbt Semantic Layer. If not, a thin "compiler" that maps metric requests to parameterized SQL templates is a legitimate prototype shortcut — the contract matters more than the engine.
- Documents: chunk the 20 documents, embed into pgvector, store wrapper metadata alongside each chunk.
- Embed the catalog entries themselves for semantic asset discovery.

### Phase 3 — MCP server and router (Weeks 3–4)

- Build the MCP server with four tools: `discover_assets`, `get_metric(metric, dimensions, period)`, `search_knowledge(query)`, `get_playbook(archetype)`.
- Every tool response returns data + the full interpretation payload from the descriptor.
- Router as a system-prompt convention first: the agent is instructed to classify the question, fetch the playbook, then follow it. A dedicated routing model is a later optimization.

### Phase 4 — Evaluate and iterate (Weeks 4–5)

- Run the 15 questions through the agent with the semantic layer. Score against gold answers on: correct number, correct caveats applied, correct source authority, correct interpretation (good/bad judgment present).
- Every failure is a content gap, not a code bug, in roughly this order: missing benchmark, missing combination rule, playbook step missing, ontology term unmapped. Fix in the repo, re-run.
- Log everything to the telemetry store from day one.

### Phase 5 — Prove the thesis (Week 5+)

- Demo artifact: same 15 questions, before/after, side by side. The delta *is* the pitch.
- Stress test with 10 questions you did not design for. Where it fails reveals whether the schema generalizes or you overfit to the eval set.
- Only then consider: second domain package (tests the universal-schema claim), extraction of the spine (from observed duplication), and the graph store (only if cross-domain questions actually appear).

### Success criteria

1. ≥12/15 gold questions answered correctly with caveats, vs. baseline.
2. Zero raw-SQL paths used by the agent for metric questions.
3. A new question in the domain is answerable by *adding content to the repo*, with no code changes.
4. The completeness test passes: the answer quality no longer depends on the agent having your domain knowledge — it depends only on the repo.

Criterion 3 is the one that proves the architecture: it demonstrates that the semantic layer, not the model, is where the intelligence accrues.
