---
archetype: metric-decline-diagnosis
label: Metric Decline Diagnosis
use_when:
  - The question asks WHY a metric moved.
  - The question asks what caused a change, or whether something is wrong.
  - The question asserts a change and asks for an explanation.
do_not_use_when:
  - The question only asks for the value. Use metric-lookup.
  - The question asks what a document says. Use policy-question.
required_tools: [get_metric, search_knowledge]
optional_tools: [list_metrics, discover_assets]
---

# Playbook: Metric Decline Diagnosis

A diagnosis, not a recitation. The output is a cause with evidence, or an honest
statement that the data does not isolate one.

Work the steps in order. Step 2 alone dissolves a surprising number of these
questions, and skipping it produces confident nonsense about a seasonal pattern.

## Step 1: Confirm the change is real

Call `get_metric` for the stated period and the prior period. Do not accept the
premise of the question. Questions frequently assert a drop that did not happen,
or a drop smaller than normal month to month variation.

If there is no material change, say so and stop. That is the answer.

## Step 2: Check seasonality BEFORE looking for a cause

Read `seasonal_notes` in the payload and pull the same period one year earlier.

This business has a strong annual shape:

- **March through May** run above band (spring leagues).
- **December** runs below band by design; budget and send volume are cut.

If the move matches the known seasonal pattern and the prior year shows the same
shape, **the seasonality IS the answer.** Say so directly, state that this is
expected, and do not go hunting for an additional cause. Manufacturing a second
explanation for an expected pattern is the most common failure of this archetype.

Only continue to step 3 if the move is larger than the seasonal pattern explains,
or runs against it.

## Step 3: Decompose by every allowed dimension

Call `get_metric` with each dimension the metric permits, for both the affected
period and the comparison period.

Start with the dimension most likely to isolate the cause. For acquisition and
signup metrics that is **acquisition_channel**, where nearly every real cause in
this business shows up.

You are looking for one of two shapes:

- **Concentrated**: one dimension value moved and the rest held flat. This
  localizes the cause and is the good case.
- **Broad**: everything moved together. This points to a systemic cause
  (seasonality, tracking, a site wide problem) rather than a channel decision.

Name explicitly which values moved and which held. "Paid search fell 37 percent
while organic and paid social held within a few percent" is the finding. "Signups
fell" is not.

## Step 4: Search the knowledge index for a planned change

A concentrated move is very often something someone decided on purpose. Call
`search_knowledge` for the affected dimension value and the period. Query the
media plan, the promo calendar, and any recall or incident notice.

Look specifically for:

- Budget pauses, increases, or reallocations
- Campaign start and end dates
- Tracking or instrumentation changes
- Product recalls or availability problems
- Documented seasonal decisions

Check that the DATES in the document actually overlap the period where the metric
moved. A budget pause in a different month is not the cause, and a document that
merely mentions the channel is not evidence.

Respect authority: a canonical document is evidence, a superseded draft is not.

## Step 5: Synthesize

Write a cause, with the decomposition and the document as evidence:

1. **What moved**: the metric, the magnitude, the period.
2. **Where it concentrated**: which dimension value, and what held flat. The flat
   values matter as much as the moved one; they are what rules out alternatives.
3. **The documented reason**: the source, its dates, and how those dates line up.
4. **The verdict**: is this a problem or an expected consequence of a decision?
   A planned budget pause producing the expected drop is not a problem, and
   saying so is the useful part of the answer.

If nothing isolates the cause, say that. "The decline is broad based across
channels and no documented change covers the period" is a legitimate and honest
diagnosis. Do not pick the most plausible sounding document and present it as the
cause without date alignment.

## Anti-patterns

- Skipping the seasonality check and diagnosing December as a problem.
- Accepting the premise without verifying the change happened.
- Reporting the total move without decomposing it.
- Citing a document whose dates do not overlap the affected period.
- Presenting a correlation as a cause when the decomposition is broad based.
- Inventing a cause because "no isolable cause" feels like a weak answer.
- Recommending an action the data does not support.
