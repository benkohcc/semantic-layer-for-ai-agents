---
archetype: targeting-and-audience
label: Targeting, Cross-sell and Audience Building
use_when:
  - The question asks WHO to send something to, or who to target.
  - The question asks what to cross-sell, or what pairs with a product.
  - The question asks which products a customer type prefers.
  - The question asks for an audience, a list, or a segment to action.
do_not_use_when:
  - The question asks for a metric value or a slice of one. Use metric-lookup.
  - The question asks why a metric moved. Use metric-decline-diagnosis.
  - The question needs unbounded relationship chains. Use graph-traversal.
required_tools: [build_audience, get_metric]
optional_tools: [category_affinity, search_campaigns, discover_assets, search_knowledge]
---

# Playbook: Targeting, Cross-sell and Audience Building

These questions exist to make a decision, not to know a number. The output is a
population plus enough evidence to judge whether targeting it is worth doing.

The discipline is the same as everywhere else in this layer: the selection path
selects, and the metrics engine measures. Never do the second job in the first
tool.

## Step 1: Work out which of three shapes the question is

- **Product preference**: "which rackets do competitive players prefer". This is
  a METRIC question at product grain. Use `get_metric` with the `product` or
  `racket_type` dimension and a `segment` filter. It does not need this playbook's
  other tools at all.
- **Cross-sell / affinity**: "what should we cross-sell to racket buyers". Use
  `category_affinity`.
- **Audience**: "who should I send this to". Use `build_audience`, then measure it.

A question can be two shapes at once. "I have a new power racket coming in, who
should I send it to" is really: which customers resemble the people who buy power
rackets, and are they worth mailing? That needs `build_audience` and then
`get_metric`.

## Step 2: For product preference, use the product grain

`net_revenue`, `order_count`, `aov` and `refund_rate` all accept `product`,
`racket_type` and `price_tier` dimensions, plus `is_performance` as a filter.

Prefer `order_count` over revenue when the question is about PREFERENCE. Revenue
conflates "more people chose it" with "it costs more", and preference is about
the first. Report both if the answer differs.

Note the structural fact before interpreting: competitive players skew heavily to
control frames and recreational players to power frames. A racket type split that
reproduces that pattern is expected, not a finding.

## Step 3: For cross-sell, read LIFT and not share

`category_affinity` returns, for each other category, the share of anchor buyers
who also bought it AND the lift of that share over the whole buyer population.

**Share alone is misleading.** Apparel is bought by most customers, so it looks
affine to everything. Lift near 1.0 means the pairing is nothing more than that
category's general popularity. Lift meaningfully above 1.0 is a real pairing.

Lead with the highest LIFT, mention the share for context, and say explicitly when
a high share has no lift behind it.

These are customer level co-purchases, not basket level, so they support a
cross-sell CAMPAIGN ("email racket buyers about strings") rather than a bundle
("put them in one box"). Say which one the evidence supports.

## Step 4: For an audience, select then MEASURE

1. Call `build_audience` with the behavioural criteria. Name it with `handle`.
2. Read the size. An audience of 30 is not worth a campaign; an audience of
   15,000 is not a target, it is the whole base.
3. **Measure it**: pass the handle to `get_metric` as `cohort`, with
   `segment_ltv` or `repeat_purchase_rate`.
4. **Compare it**: measure a sensible comparison audience the same way, or use the
   overall value as context while saying that is what you are doing. An audience
   whose LTV matches the base average is not a good target; it is average.

Selecting without measuring is the failure mode here. A count on its own tells a
marketer nothing about whether to spend money.

## Step 5: Respect what the layer cannot give you

- **No contact details.** There are no email addresses, names, or phone numbers in
  this warehouse, and no export path. `build_audience` returns customer ids and a
  count. If asked for a contact list, say plainly that the layer holds no PII and
  that the audience DEFINITION is what goes to the email platform.
- **An audience is not a prediction.** It describes who did what. "Customers most
  likely to buy next month" is a propensity score, which this layer does not
  produce. Offer the behavioural audience instead and label it as past behaviour.
- **Lapse and churn are inferred.** `lapsed_category_months` and
  `inferred_churned_only` rest on purchase silence, not on an observed event. A
  customer who simply had no need looks identical to one who left. Disclose this
  every time either criterion is used.
- **Purchases elsewhere are invisible.** `not_bought_category` means "no recorded
  purchase here", not "has never owned one".

## Step 6: Write the answer

1. The audience or finding, with its size.
2. The criteria that defined it, in plain language.
3. The governed measurement, and what it is compared against.
4. A recommendation, if the evidence supports one, and a plain statement when it
   does not.
5. The caveats from step 5 that actually apply.

## Anti-patterns

- Reporting an audience count with no measurement of its value.
- Leading with affinity share when the lift is 1.0.
- Presenting a behavioural audience as a propensity or likelihood score.
- Treating a null relationship or an absent purchase as proof of never.
- Attempting to assemble or export contact details.
- Using revenue to answer a preference question without saying that price is
  confounded into it.
- Recommending a campaign to an audience whose LTV is no better than average.
