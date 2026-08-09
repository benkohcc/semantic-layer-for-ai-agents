# What We Built, and Why

A plain explanation of the semantic layer: the problem it solves, why it is worth
building, and how it works. No code, no setup instructions.

If you want to run it, see
[baseline-tennis-poc/README.md](baseline-tennis-poc/README.md). This document is
about the idea.

---

## The problem in one sentence

**When you give an AI agent access to your data, it will answer every question
confidently, and some of those answers will be wrong in ways nobody catches.**

Not wrong because the model is weak. Wrong because the data does not carry its own
meaning, and the agent has no way to know what it is missing.

## What that actually looks like

We built a fictitious online tennis store with a realistic warehouse: 18,000
customers, 91,000 orders, 356,000 email sends, and a folder of marketing
documents. Then we asked an agent the same questions two ways.

**Without a semantic layer**, given raw database access, the agent is capable and
careful. It writes reasonable SQL. And it still produces this:

| Question | Agent answered | Actually | Why it went wrong |
|---|---|---|---|
| What was revenue last month? | $615,188 | **$425,966** | Counted QA test orders and the wholesale business line, neither of which is marketing revenue |
| How did email open rates do? | 35.15% | **23.28%** | Counted automated opens from privacy proxies that no human performed |
| Are customers referred by someone who churned more likely to churn? | "No, the opposite" | **Yes, by 11.7 points** | Invented its own churn definition, compared 9.55% to 9.00%, called it a finding |

Read that last row again. The agent did not fail to answer. It answered
**confidently, with real numbers, in the wrong direction.** A marketer would have
acted on it.

None of these are exotic edge cases. They are the normal state of a warehouse that
grew over time: test data in production, tracking artifacts, business lines with
different economics, terms that mean different things to different departments.

### The synthetic company, briefly

Baseline Tennis Co. is entirely generated, and generated adversarially: it is a
test bed, not a random dataset. Two years of history across 18,000 customers,
91,000 orders, 120 products in five categories, 63 marketing campaigns, 356,000
email sends, and 29 policy and planning documents, all of it shaped like a real
retailer: seasonal peaks for spring leagues, a December dip that is deliberate, two
customer segments with genuinely different economics, and a referral network deep
enough to ask network questions about.

Every trap was planted on purpose, and every trap has a question in the test suite
that hunts it. The QA rows and the wholesale line are in there so that a naive
revenue query fails. A quarter of email opens are machine opens so that a naive
open rate flatters. One policy document is an abandoned draft that reads exactly
like a real policy. And the generator checks its own work: after seeding, it
asserts that every planted pattern actually materialized, so the demo cannot pass
by luck, and it publishes the correct answers so the test suite always knows what
the truth is, even after the data is regenerated.

The gaps are planted with equal care. There is no satisfaction data anywhere, by
design, so an honest system must decline the question rather than improvise.

## Why the agent cannot solve this on its own

The information it needs simply is not in the data.

A table called `orders` does not say that `status = 'test'` rows are QA artifacts
written into production. A column called `opened` does not say that a third of
those opens were image prefetches by a privacy proxy. Nothing in the schema says
that marketing counts revenue net of refunds while finance counts it gross, and
that both are correct for their own purpose.

And documents are worse than tables. A folder of policies does not tell you which
one is in force. **A policy written in 2024 does not say "I was replaced in
2026."** Nobody went back to stamp it, because the person writing the replacement
had no way to reach every copy of the old one. It reads as confident and complete,
because it was, once.

Give an agent that folder and it will find *something*, cite it, and sound
authoritative.

## What we built

A **semantic layer**: a machine-readable knowledge system that sits between the
agent and the data. For any question, it supplies four things the raw data cannot.

**1. What exists.** A catalog of every queryable thing: metrics, tables,
documents, and the paths that reach them.

**2. What it means.** Definitions, formulas, exclusions, caveats, and known
limitations. "Revenue" is not a column, it is a definition with rules attached.

**3. How to get it.** One governed path per asset. Revenue comes from the metrics
engine, which applies the exclusions automatically. The agent cannot write its own
SQL and skip them, because on this system raw SQL is not offered.

**4. How to interpret it.** This is the part most implementations skip, and it is
where the value is. Every number arrives with its benchmark band, which direction
is good, seasonal context, required caveats, and a confidence assessment.

The agent connects to it the same way it would connect to any tool. It asks
questions in plain English; the layer supplies the governed answers and the meaning
that travels with them.

## What the answer looks like with the layer

Same question, same data:

> **"How did email open rates do last month?"**
>
> 23.3 percent, within the normal band of 22.7 to 25.1 percent for this time of
> year. This counts human opens only: machine opens from privacy proxies are
> excluded, as is transactional mail, so it is not comparable to a raw open rate
> from another tool. Open rate is directional only since Apple Mail Privacy
> Protection. Click rate, at 3.1 percent, is the more reliable signal for
> campaign decisions.

A number, a judgment, the definition, the caveat, and what to look at instead. The
raw-access agent gave a bigger number and no way to know it was wrong.

## The four things this makes possible

### It gets the number right

The exclusions live inside the metric, so they are applied every time. Not because
the agent remembered, but because there is no path that skips them.

### It knows which document is current

Documents do not declare their own status, so we built a **registry** that tracks
it externally: what is in force, what is superseded, what was never adopted. The
same role a CMS or an approval workflow plays in a real company.

Our corpus contains a 2024 policy that was drafted and abandoned. Nothing in the
file says so. Search finds it as the fourth-best match for "what is our refund
policy" and the layer demotes it, so the agent answers from the live policy and
mentions the old one exists.

Harder case: two service agreements, **both genuinely in force at different
times**. Neither is wrong. Only the effective date can separate them, and only the
registry knows it.

### It says "I don't know" when it should

This is the underrated part. The layer declares what the business does *not* have,
so an honest refusal is guaranteed rather than hoped for:

> **"What's our NPS?"**
>
> No satisfaction, sentiment, or NPS data is collected anywhere in this business:
> no survey instrument, no survey table, no third-party feed. The nearest
> available signals are repeat purchase rate and refund rate. Neither measures
> sentiment: a customer can be unhappy and still repurchase, or perfectly happy
> and simply not need anything.

Same for forecasts (out of scope), competitor data (not collected), and
stock history (only current levels exist). The layer distinguishes *"we cannot
answer that"* from *"here is an adjacent number you might mistake for it."*

It also draws boundaries precisely. **"Are we out of stock?"** is answerable.
**"How long have we been out of stock?"** is not, because no movement history
exists. The layer says so rather than estimating.

### It adds new capabilities without rewriting anything

The second half of the project tested whether the layer could learn something
genuinely new. We added the ability to trace relationships through the customer
base: referral chains, who was affected by a product recall, whether churn spreads
through a referral network.

**That capability arrived almost entirely as content**, not code. The routing
logic never learned what a graph is. New metrics work the same way: our
gross-margin metric is a configuration file with no program behind it.

This is the difference between a system that has to be re-engineered every time
the business asks something new, and one that can be extended by writing down what
you know.

## Why this is worth doing

**Wrong answers are expensive and invisible.** A 44 percent revenue overstatement
does not announce itself. Someone builds a forecast on it. The failure surfaces a
quarter later, attached to a decision nobody can trace back.

**Definitions drift without one.** Three teams asking "what is revenue" get three
numbers, and the meeting becomes about whose number is right instead of what to
do. The layer makes the governed definition the only one an agent can reach.

**Confident nonsense erodes trust faster than "I don't know" ever does.** A tool
that occasionally invents an answer gets abandoned, because checking it costs more
than doing the work yourself. Reliable refusal is what makes the reliable answers
usable.

**The knowledge already exists, in people's heads.** Someone knows about the test
rows. Someone knows December always dips. That knowledge lives in analysts'
memories and leaves when they do. The semantic layer is where it gets written down
in a form a machine can enforce.

## How it works

### The process: what happens to a question

```
   You ask a question in plain English
                 |
   +-------------v--------------+
   |      SEMANTIC LAYER        |
   |                            |
   |  What do you mean?         |  maps your words to a governed asset
   |  How should this be done?  |  supplies the step-by-step procedure
   |  Compute it correctly      |  applies the exclusions, every time
   |  What does it mean?        |  attaches band, caveats, confidence
   +-------------+--------------+
                 |
     Your data, read but never moved
```

Four steps, and the layer contributes something at each one.

**1. Understand the question.** "How much did we make" maps to the governed
revenue metric. "Who should I send this to" maps to audience building. A question
about something the business does not track maps to a declared gap, which produces
a refusal with a reason.

**2. Follow the right procedure.** Different questions need different methods. A
"why did this drop" question requires checking seasonality *before* hunting for a
cause, or you will diagnose December as a crisis every single year. The layer
supplies these procedures as playbooks so the agent follows a known-good method
instead of improvising.

**3. Compute through the governed path.** The metrics engine applies the
exclusions. Documents are ranked by the registry. Neither depends on the agent
remembering anything.

**4. Attach the meaning.** The number travels with its band, its direction of
goodness, its caveats, and its confidence. Meaning arrives *with* the data rather
than being reconstructed afterward.

### The architecture: what the layer is made of

Four parts. The split matters, and the most important thing about it is that
**almost everything is written knowledge rather than program logic.**

```
  +-------------------------------------------------------------------+
  |  1. THE KNOWLEDGE                        written down, not coded   |
  |                                                                    |
  |   Metric definitions   formula, exclusions, benchmark band,        |
  |                        caveats, and what the metric cannot say     |
  |   Document registry    which version of a document is in force     |
  |   Playbooks            how to approach each kind of question       |
  |   Ontology             plain words to governed assets, plus the    |
  |                        concepts the business declares it lacks     |
  +-------------------------------------------------------------------+
                                   |
  +-------------------------------------------------------------------+
  |  2. THE ENGINES                     small, and deliberately dumb   |
  |                                                                    |
  |   Metrics engine       turns a definition into a query and         |
  |                        applies the exclusions, every time          |
  |   Retrieval            finds passages, ranks them by the registry  |
  |   Traversal            walks relationships, selects populations    |
  |   Interpretation       attaches band, caveats, confidence to       |
  |                        every result before it leaves               |
  +-------------------------------------------------------------------+
                                   |
  +-------------------------------------------------------------------+
  |  3. THE STORES                        three, each for one job      |
  |                                                                    |
  |   Relational           the transactional record: customers,        |
  |   (SQL warehouse)      orders, sends, spend. Every number comes    |
  |                        from here.                                  |
  |                                                                    |
  |   Vector index         the document corpus, split into passages    |
  |                        and embedded so meaning can be searched     |
  |                        rather than keywords. Each passage carries  |
  |                        its governance from the registry.           |
  |                                                                    |
  |   Document graph       DOCUMENTS and what they govern, built from  |
  |                        the registry: which replaced which, which   |
  |                        policies cover which categories. Derived,   |
  |                        never a source of truth.                    |
  +-------------------------------------------------------------------+
                                   |
  +-------------------------------------------------------------------+
  |  4. THE INTERFACE              nine tools over one connection      |
  +-------------------------------------------------------------------+
```

### Why several stores rather than one

Each answers a shape of question the others handle poorly.

**Relational** is exact and additive. "What was revenue in July, by channel" is
arithmetic over rows, and a database does that better than anything else. But it
cannot tell you what a policy means, and it is bad at questions whose depth you do
not know in advance.

**The vector index** exists because policy questions are not keyword questions.
Someone asking "can customers send things back" will never match a document titled
"Refund and Returns Policy" on words alone. Embedding turns both into positions in
a meaning space so the match survives the paraphrase. Documents are split into
passages first, so a question about junior racket tension finds the one paragraph
that answers it rather than a forty-page manual.

**The document graph** handles a problem the vector index cannot touch at all.
Similarity finds text that sounds like your question. It has no notion of one
document replacing another, or of a pricing policy having authority over rackets.
So "what is our refund policy" is a similarity question, and "which policies apply
to racket discounting" is not: the answer is in no single passage, it is in how
the documents sit relative to each other. Asked the second way, similarity returns
something confident and useless.

Note what the graph is not: a second copy of the truth. It is derived from the
registry, holds only relationships, never numbers, and can be rebuilt at any time.

Customer relationship questions, "who did this customer refer, and who did those
people refer," need no separate store at all. An early version kept a second
in-memory copy of the referral structure for them; it bought convenience and paid
for it in staleness, so it is gone. Those walks now run as recursive queries
against the same warehouse every number comes from, which means a traversal can
never disagree with the data it walks.

### The rule that holds it together

Different stores could easily mean different answers to the same question. One
rule prevents that:

> **The graph and the audience builder SELECT populations. Only the metrics engine
> COMPUTES.**

Ask whether referral churn spreads, and the graph picks out the affected customers
and hands back a reference to them. The repeat-purchase rate for that group is then
computed by the metrics engine, through the same governed definition that would
apply to any other question, with the same exclusions.

A number worked out any other way is not the governed metric, even when the
arithmetic happens to be right. That is what keeps several stores from producing
three versions of the truth.

### What this buys you

The engines contain no business knowledge. They do not know what revenue is, which
policy is current, or that December always dips. All of that lives in layer one as
configuration a person can read and edit.

This build carries roughly **3,800 lines of written knowledge against 2,900 lines
of engine**, and the split matters more than the ratio: not one line of the engine
knows what revenue means. The knowledge is the system; the engines just execute it
faithfully.

That is what makes it extensible. Adding a metric means writing a definition file;
adding a question type means writing a playbook. Both were done during this build
with no program change, and the routing logic never learned that either existed.

It is also what makes the knowledge durable. A definition written down survives the
analyst who knew it. A rule buried in code does not, because nobody outside
engineering can read it, let alone challenge it.

### One connection, nine tools

You connect to a single server. It offers nine tools, and **you never choose
between them**: you ask a question in plain language and the layer routes it.

| Tool | What you would ask it |
|---|---|
| `get_started` | *What can I even ask about here?* |
| `list_metrics` | *What numbers do you track?* |
| `get_playbook` | *What is the right way to approach this kind of question?* |
| `discover_assets` | *Do we have anything on customer satisfaction?* |
| `get_metric` | *What was revenue last month?* |
| `search_knowledge` | *What is our refund policy?* or *which policies apply to racket discounting?* |
| `search_campaigns` | *What did we learn from our restring campaigns?* |
| `category_affinity` | *What should we cross-sell to someone who bought a racket?* |
| `build_audience` | *Who should I send this promotion to?* or *which channel produced our best referral chains, counting referrals of referrals?* It selects customers two ways, by attributes or by walking relationships, and hands back a reference either way. |

Routing is most of what the layer is for. It knows that "how much did we make" is
a governed metric, that "what does the policy say" is a document, and that "search
the documents for our revenue" is a metric question wearing a disguise. Getting
that last one wrong is how an agent ends up quoting a stale figure out of a slide
deck.

The same principle operates inside a tool. `search_knowledge` searches document
text and the document graph together, every time, and reports what each
contributed. There is no relationship mode to select and no particular way you
have to phrase the question: ask "what's downstream of the refund policy" or
"if we change the refund window, what breaks" and the relationships come back
because the refund policy is a thing the layer knows has relationships, not
because the wording sounded relational. We built a classifier to make that
choice first, measured it, and deleted it. The two searches return different
kinds of thing, text and relationships, so there was never a choice to make.

Ten is deliberately small. Each tool is a governed path rather than a convenience,
so there is exactly one way to get a number and one way to reach a document. A
tool per metric or per document type would run to dozens and would hand the
governance decisions back to the agent, which is the thing the layer exists to
prevent.

Notice which two do not compute anything. `build_audience` and `search_campaigns` select or retrieve, then hand off. The number always comes from `get_metric`, which is the rule from the previous section made visible in the interface itself. Relationship traversal used to be a tenth tool; once its engine became recursive queries on the warehouse, selecting by relationships and selecting by attributes were the same act, so the two tools merged.

## What it is not

**Not a copy of your data.** It stores meaning and pointers, and reads your
warehouse in place. The one thing it does hold is a search index over your
documents, which is derived from them and rebuilt on demand.

**Not documentation.** Documentation is for humans, optional, and goes stale
quietly. This is machine-enforced and travels with every query result.

**Not a replacement for analysts.** It encodes what they already know so that
knowledge scales past their calendars, and so it survives them leaving.

**Not one giant company-wide ontology.** Those projects fail. This is a small
shared spine with self-contained domain packages hanging off it. Marketing was
built first; another team can add theirs without renegotiating the whole thing.

## The short version

Raw data plus a capable AI produces confident answers, some of which are wrong,
and you cannot tell which from looking at them.

The same AI plus a semantic layer produces answers that are correct, carry their
own caveats, and refuse honestly when the data does not support the question.

The difference is not the model. It is whether the meaning was written down.
