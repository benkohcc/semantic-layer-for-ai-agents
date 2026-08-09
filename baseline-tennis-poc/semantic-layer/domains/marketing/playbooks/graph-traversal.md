---
archetype: graph-traversal
label: Graph Traversal (influence, propagation, impact trace)
milestone: 2
use_when:
  - The question needs chains of unknown or unbounded depth: referrals of referrals, downstream networks.
  - The question is about propagation or exposure through a relationship.
  - The question traces an affected population across three or more entity hops.
do_not_use_when:
  - The question is an aggregation over an attribute, even a relationship attribute. Counting referred customers is metric-lookup.
  - The question asks for revenue or a rate from a group defined by a simple filter. That is metric-lookup.
  - A single level join answers it. Depth 1 is not a chain.
required_tools: [build_audience, get_metric]
optional_tools: [search_knowledge, discover_assets]
---

# Playbook: Graph Traversal

The graph selects cohorts. The metrics engine computes numbers. Keeping those two
jobs apart is the whole discipline of this playbook.

## Step 1: Confirm the question is actually traversal shaped

Traversal is the right path only when at least one of these holds:

- **Unknown depth**: "referrals of referrals", "chains", "downstream", "all the
  way through". If the depth is fixed at 1, this is not a chain.
- **Path language**: "who came from", "traced back to", "network position".
- **Propagation or exposure**: "at risk because of", "spread", "exposed to".
- **Three or more entity hops**: campaign to send to order to product.

STOP AND USE `metric-lookup` INSTEAD if the question is an aggregation over an
attribute. These are NOT traversal questions even though they mention
relationships:

- "How many customers were referred" is a count over an attribute.
- "Revenue from referred customers" is an aggregation with a filter.
- "Signups by acquisition channel" includes the referral channel and is still a
  metric.

Misrouting these to the graph is a failure even if the number comes out right.

## Step 2: Pick the operation

The operation set is CLOSED. There is no arbitrary traversal, by design.

| Operation | Answers |
|---|---|
| `chain_stats` | which grouping produced the deepest or largest chains |
| `referral_chain` | the shape of chains from one root or one channel |
| `exposed_cohort` | who is exposed to a condition through a relationship |
| `trace_cohort` | who is reached through a campaign to a specific product |

If none of them fits, say so. An unregistered traversal is unavailable, not
something to approximate with a different tool.

## Step 3: Read the edge descriptor before interpreting anything

Every result carries the edge semantics. The part that matters most is what the
ABSENCE of an edge means:

> A NULL `referred_by` means the signup was not ATTRIBUTED to a referral. It does
> not mean the customer has no relationships. Uncoded word of mouth referrals are
> invisible, so the graph systematically undercounts real referral influence.

Note also that a referred customer's own acquisition channel is always
`referral`. To ask which channel SEEDED a chain, depth must be attributed to the
chain ROOT's channel, which `chain_stats` does. Grouping on the member's own
channel answers nothing.

## Step 4: For any measured quantity, compose through the metrics engine

**This is the step that must never be skipped.**

When the question asks for a rate, a revenue figure, or any other measured
quantity for the cohort you selected:

1. `build_audience` (relationship mode: `operation` plus `params`) registers each cohort under a short HANDLE and lists them in the
   result under `cohort_handles`. Typically `exposed` and `comparison`, or
   `traced` and `control`.
2. Call `get_metric` with `cohort="<handle>"`.
3. The metrics engine computes the governed metric on that cohort.

Do the same for the comparison cohort, in a second `get_metric` call, using the
same metric and the same period.

**Use the handle, not the id list.** These cohorts run to thousands of customers.
Long id lists are replaced in the result by a handle plus a sample, precisely so
you do not paste them back. A call that tries to enumerate several thousand ids is
slow enough to fail outright.

A number you compute yourself from the id list is NOT the governed metric. It is
not acceptable even if the arithmetic is right, because the governed definition
carries exclusions, a window, and a denominator choice that hand computation
silently drops. If you find yourself counting ids, stop and call `get_metric`.

## Step 5: Verify temporal ordering wherever causality is implied

A relationship plus an outcome is not a sequence. Check the order explicitly.

- **Referral and churn**: the referral must PRECEDE the churn. `exposed_cohort`
  returns a `temporal_ordering` block with the count of referrals falling before
  the churn window and a verdict. Read it. If the ordering is not clean, say the
  direction cannot be asserted.
- **Purchases and a recall**: purchases made BEFORE the recall date carry no
  exposure to it. Retrieve the recall notice with `search_knowledge` to get the
  date, and restrict any divergence claim to behavior after it. A comparison
  spanning the recall date mixes exposed and unexposed behavior.

## Step 6: Compare against the matched or non exposed cohort, never the band

Every cohort selecting operation returns a comparison cohort chosen to hold the
confounders constant:

- `exposed_cohort` returns referees of NON churned referrers. That holds "was
  referred" constant and varies only the referrer's churn status.
- `trace_cohort` returns buyers of a DIFFERENT product in the same category
  through the SAME campaign. That holds campaign and category constant.

Do NOT compare a cohort to the overall benchmark band. The band is computed on
the whole active population, and any narrow cohort will differ from it for
structural reasons that have nothing to do with the hypothesis.

## Step 7: Frame the finding as correlational

This is observational data with no experiment behind it. Write associations, not
causes.

- Supportable: "referees of churned referrers repeat about 11 points less often
  than referees of active referrers."
- NOT supportable: "referrer churn causes referee churn."

Also disclose the definitional caveat every time it applies: churn in this
business is INFERRED from purchase silence (no completed order in the trailing 12
months). There is no cancellation event. A customer who simply had no need is
counted as churned.

## Step 8: Write the answer

1. What the traversal found, with the cohort sizes.
2. The governed metric for each cohort, and the difference in points.
3. The temporal ordering check and what it does and does not license.
4. The correlational framing, stated plainly.
5. The definitional caveats: inferred churn, last touch attribution, uncaptured
   word of mouth referrals, and the recall boundary where relevant.

## Anti-patterns

- Computing a rate inside the traversal step, or by hand from the id list.
- Comparing a cohort against the overall benchmark band.
- Claiming causation from an association.
- Skipping the temporal ordering check when the question implies a sequence.
- Treating a NULL relationship as proof that no relationship exists.
- Routing an ordinary aggregation to the graph because the question said
  "referred".
- Reporting a chain depth without saying it is attributed to the chain root's
  channel.
