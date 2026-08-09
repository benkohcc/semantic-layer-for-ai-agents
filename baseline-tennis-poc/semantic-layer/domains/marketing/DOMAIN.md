# Marketing Domain: Baseline Tennis Co.

Baseline Tennis Co. is a direct to consumer online tennis store selling rackets,
strings, shoes, apparel, and stringing services. Three years old, United States
only, roughly 18,000 customers. Marketing runs email (lifecycle and campaign),
paid search, paid social, and organic.

This domain package governs marketing performance reporting: acquisition,
revenue, email engagement, retention, and campaign results.

## How to use this layer

Every question follows the same shape: classify the archetype, get the playbook,
follow it. Do not improvise a procedure, and do not compute numbers yourself.

| Archetype | Use when the question is | Playbook |
|---|---|---|
| `metric-lookup` | a number, a rate, a comparison across an allowed dimension | `metric-lookup` |
| `metric-decline-diagnosis` | why a metric moved, what caused a change | `metric-decline-diagnosis` |
| `policy-question` | what a policy, definition, or documented rule says | `policy-question` |
| `targeting-and-audience` | who to send something to, what to cross-sell, which products a customer type prefers | `targeting-and-audience` |
| `graph-traversal` | chains of unknown depth, propagation through relationships, tracing an affected population | `graph-traversal` (requires the graph access path) |

## The two segments

- **Competitive**: two or more restrings in a trailing 12 months, or a
  performance racket purchase (100 square inches or smaller, above 150 dollars).
  Restrings often, higher lifetime value, less price sensitive.
- **Recreational**: everyone else. Occasional purchases, skews to apparel and
  entry level equipment, price sensitive.

Segment is behavioral and recomputed monthly. It is not a skill rating and is
not a proxy for satisfaction.

## Seasonality

This business has a strong and well understood annual shape. Reading a month
against the adjacent month rather than against the same month last year is the
most common analytical error here.

- **March through May**: spring league season. Demand rises across every
  category and channel. The Spring League Kickoff campaign runs in this window.
  Elevated numbers in these months are seasonal.
- **December**: intentionally quiet. Send volume and paid budget are reduced over
  the holidays. **Revenue dips every December by design.** A December decline is
  expected seasonality, not a performance problem.

## Known data traps

Two categories of rows exist in `orders` that must never reach marketing
reporting. Both are enforced inside the governed metrics, so metric answers are
already correct; the trap only bites answers computed from raw SQL.

1. **Test orders** (`status = 'test'`, about 2 percent of rows). Written by QA
   into production with realistic amounts.
2. **Wholesale orders** (`channel = 'wholesale'`, about 5 percent of rows). A
   separate business line with much larger baskets. Including wholesale
   overstates marketing revenue substantially.

A third trap lives in email: since Apple Mail Privacy Protection began
prefetching images, roughly a third of recorded opens never involved a human.
The governed open rate excludes machine opens; raw open counts do not.

## Gross versus net revenue

Finance reports gross booked revenue. Marketing reports net of refunds. Both are
correct for their own purpose, and they will not match.

**The governed marketing metric is net.** The Spring League Kickoff recap deck
quotes a gross figure and was never restated. When a document and the metrics
layer disagree on a number, the metrics layer is authoritative, and the answer
should name the discrepancy rather than quietly pick one.

## What this layer cannot answer

Declining is a correct answer when the data does not support the question. A
confident number built on a known gap is a failure, and it is a worse failure
than saying nothing.

### No satisfaction, sentiment, or NPS data exists

There is no survey instrument, no survey table, and no third party sentiment
feed. **Nothing in this business measures how customers feel.** Questions about
satisfaction, NPS, sentiment, happiness, or loyalty-as-feeling cannot be
answered at all.

The nearest available signals are `repeat_purchase_rate` and `refund_rate`. Both
are behavioral. Neither measures sentiment: a customer can be unhappy and still
repurchase, or perfectly happy and simply not need anything this quarter. Offer
them as adjacent evidence, never as a satisfaction number.

### Attribution is last touch only

The final marketing touch before a conversion gets full credit. There is no
touch path in the data. Multi touch attribution, fractional credit, and
path based questions cannot be answered from this data, only declined.

### Churn is inferred, never observed

This is retail. There is no subscription and no cancellation event. Where churn
is reported, it means **no completed order in the trailing 12 months**. That is
a definition applied to purchase silence, not a measurement of a decision.

Every churn adjacent answer must disclose this. A customer who simply has not
needed a restring in 13 months is counted as churned by this definition.

### Paid social spend has a coverage hole

Paid social spend tracking was implemented late. Spend data begins in month 7 of
the 24 month window. Paid social activity before that happened but was never
logged, so **CAC for paid social cannot be computed for any earlier period**. Do
not extrapolate backward into the hole; report the covered months and name the
boundary.

### The services category is thin

Stringing services run well under 30 orders a month across the whole business,
below the reliability threshold. Category level numbers for services are real
but statistically weak. Report them **with** the sample size and label them
directional.

### No personally identifiable information

This warehouse holds **no names, no email addresses, and no phone numbers**, by
design, and there is no export path. `build_audience` returns customer ids and a
count. When someone asks for a contact list, the honest answer is that the audience
DEFINITION is what goes to the email platform, and the contact list is assembled
there.

### No web analytics, so no conversion rate

There is no session, visit, or traffic data. Only placed orders exist, so no funnel
step above the order can be measured. A click-to-order ratio is not a conversion
rate and must not be presented as one.

### No creative, ad, or keyword level data

`ad_spend` is **channel level only**. There is no creative, ad, subject line, or
keyword dimension anywhere, and no experiment results. "Which creative performed
best" cannot be answered at all. Channel level performance is available and is a
different question.

### No unsubscribe or subscription state

`email_sends` records delivery and engagement but no opt out event, so list
attrition cannot be measured. Deliverability and click rate are the available
program health signals.

### No propensity scoring

The layer does not rank or score customers by predicted behaviour. "Who is most
likely to buy next month" is a prediction and is out of scope. What IS available is
a behavioural audience: who actually did something. Offer that instead, and label
it as past behaviour rather than likelihood.

### Forecasting is out of scope

This layer reports actuals. It does not forecast. Trend history is available and
useful, but a trend restated as a prediction is not a forecast, and presenting
one as an answer to "what will X be" is a failure. Decline the forecast, then
offer the history explicitly labeled as history.

### No competitor data

No competitor pricing feed or market share data exists. Any claim about relative
market position would be qualitative.

## Anti-patterns

Never do any of these, regardless of how reasonable the question sounds:

- Estimate, interpolate, or infer a number the tools did not return.
- Fill a coverage hole by extrapolating from the covered periods.
- Present an inferred definition (churn) as an observed event.
- Answer a forecast question with a trend restated as a prediction.
- Average a non additive metric across periods instead of re deriving it.
- Quote a figure from a document when a governed metric covers the same concept.
- Compare a month to the adjacent month across a seasonal boundary without also
  showing the same month last year.
