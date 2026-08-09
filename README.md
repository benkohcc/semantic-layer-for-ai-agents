# A Semantic Layer for AI Agents

Give an AI agent raw access to your data and it will answer every question
confidently, and some of those answers will be wrong in ways nobody catches. Not
because the model is weak, but because the data does not carry its own meaning.

This is a working proof of concept of the fix: a machine-enforced semantic layer
that sits between the agent and the warehouse, supplying the definitions,
governance, and interpretation the raw data cannot.

## The demonstration

A fictitious online tennis retailer with a realistic warehouse: 18,000 customers,
91,000 orders, 356,000 email sends, 29 policy documents. The same questions asked
two ways.

| Question | Raw database access | With the semantic layer |
|---|---|---|
| What was revenue last month? | $615,188 | **$425,966** |
| How did email open rates do? | 35.15% | **23.28%** |
| Does churn spread through referrals? | "No, the opposite" | **Yes, by 11.7 points** |

The raw-access answers are not sloppy. The agent wrote reasonable SQL. It counted
QA test rows and a wholesale business line as marketing revenue, counted machine
opens from privacy proxies as human ones, and invented its own churn definition.
Nothing in the schema told it otherwise.

## Where to start

| If you want | Read |
|---|---|
| The concept, problem, and value in plain language | [OVERVIEW.md](OVERVIEW.md) |
| The same thing as an illustrated page | [semantic-layer-explained.html](semantic-layer-explained.html) |
| To run it, and how it was built and verified | [baseline-tennis-poc/README.md](baseline-tennis-poc/README.md) |
| The original design | [PLAN.md](PLAN.md) |

## Quick start

Requires Python 3.11. Everything runs locally, and the demo needs no API key.

```bash
cd baseline-tennis-poc
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python data/seed.py                    # generates the warehouse and documents
.venv/bin/python cli.py index                    # builds the vector index
.venv/bin/python eval/verify_layer.py            # 313 checks, no model involved
.venv/bin/python eval/verify_knowledge_graph.py  # 16 checks, no model involved
```

The warehouse, the document corpus, and the vector index are generated rather than
committed. Seeding is deterministic (fixed seed 42), so a fresh clone reproduces
the same data, and the seeder asserts every planted signal and gap before it
finishes.

Then register the MCP server with Claude Desktop or Claude Code, per
[the operator guide](baseline-tennis-poc/README.md#register-with-claude).

## What is in here

```
OVERVIEW.md                    the concept, for a reader who will not run it
semantic-layer-explained.html  the same argument, illustrated
PLAN.md                        the original build plan
baseline-tennis-poc/
  semantic-layer/              THE KNOWLEDGE: metric definitions, document
                               registry, playbooks, ontology. About 3,800 lines
                               of written knowledge.
  src/                         THE ENGINES: compute, retrieve, traverse,
                               interpret. About 2,900 lines, and none of it
                               knows what revenue means.
  mcp_server.py                nine tools over one connection
  data/seed.py                 generates the whole synthetic company
  eval/                        403 deterministic checks plus a scored suite
```

More knowledge than engine, and the split is what matters more than the ratio:
the engines contain no business knowledge at all. They do not know what revenue
is, which policy is current, or that December dips. Adding a metric is a new YAML
file; adding a question type is a new playbook. Both were done during this build
with no program change.

## How it is verified

Every claim above is checkable without a model:

```bash
.venv/bin/python eval/verify_layer.py            # 313 checks
.venv/bin/python eval/verify_knowledge_graph.py  # 16 checks
.venv/bin/python eval/verify_marketer_coverage.py  # 74 real marketer questions
.venv/bin/python eval/probe_mcp.py               # the MCP protocol boundary
.venv/bin/python eval/probe_cohort.py            # cohort handles over the wire
```

There is also a scored evaluation suite of 25 questions that runs a real model
against the layer, with and without governance, and a routing probe that isolates
the tool descriptions from everything else. Both are documented in the
[operator guide](baseline-tennis-poc/README.md#running-the-scored-eval), including
the one adversarial case that still misroutes.
