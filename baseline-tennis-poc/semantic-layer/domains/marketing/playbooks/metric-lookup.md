---
archetype: metric-lookup
label: Metric Lookup
use_when:
  - The question asks for a number, rate, total, count, or average.
  - The question compares across an allowed dimension (by channel, by segment, by month).
  - The question asks whether a number is good, healthy, or normal.
do_not_use_when:
  - The question asks WHY something changed. Use metric-decline-diagnosis.
  - The question asks what a policy or definition says. Use policy-question.
  - The question needs chains of unknown depth or propagation. Use graph-traversal.
required_tools: [get_metric]
optional_tools: [list_metrics, discover_assets, search_knowledge]
---

# Playbook: Metric Lookup

Resolve the concept to a governed metric, compile it, and answer with the
interpretation attached. The number alone is never the answer.

## Step 1: Resolve the concept to exactly one governed metric

Map the words in the question to a metric id. If the mapping is not obvious, call
`list_metrics` or `discover_assets` rather than guessing.

If the concept resolves to a **declared absent concept** (satisfaction, NPS,
sentiment, multi touch attribution, a forecast, competitor data), STOP. Do not
substitute a nearby metric. Go to "Handling absent concepts" below.

If the question implies a definition that differs from the governed one, use the
governed one and name the difference in the answer. "Opens" means human opens
here; the governed number is lower than a raw count and that is correct.

## Step 2: Determine period, dimensions, and filters

- Period: "last month" means the last COMPLETE month. Never report a partial
  current month as if it were complete.
- Dimensions: only those the metric allows. If the question asks for a dimension
  the metric does not support, the tool will reject it with an explanation. Read
  the explanation and either use an allowed dimension or say what is unavailable.
- Respect the minimum grain. Open rate below weekly is meaningless.

## Step 3: Call `get_metric`

Never compute a number yourself, never estimate one, and never carry a number
over from a document. One tool call per distinct metric request.

## Step 4: Read the interpretation payload before writing anything

Every result carries a payload. All of it is load bearing:

- `value` and `sample_size`
- `benchmark`: whether the value sits within, above, or below the internal band
- `direction`: which way is good. **Check this before using any evaluative word.**
  For `cac` and `refund_rate`, lower is better, so an increase is bad news.
- `seasonal_notes`: whether the period is expected to run hot or cold
- `required_caveats`: these are mandatory, not optional garnish
- `companions`: the metrics that make this one decision useful
- `confidence`: sample adequacy, coverage holes, and applicable definition caveats

## Step 5: Judge the number against the band, adjusted for season

State plainly whether the value is normal, strong, or weak. "Within the normal
band" is a real and useful answer. Do not manufacture a concern to sound
analytical, and do not call a number good just because it rose.

If the period falls in a known seasonal window, say so **before** the judgment.
A March number above band is expected. A December number below band is expected.

## Step 6: Write the answer

Include, in roughly this order:

1. The number, with the period and the governed definition in one clause.
2. The band judgment, seasonally adjusted.
3. Every required caveat. Surface them; do not bury them in a trailing sentence.
4. Any degraded confidence, stated in plain language with the reason.
5. The companion metric, with its value if it helps the decision.

Keep it short. A number, a judgment, a caveat, and a companion is usually four
sentences.

## Campaign questions: check for a recap deck

When the question is about a specific CAMPAIGN, the governed metric is only half
the answer. Campaign recap decks quote gross revenue over all rows and are almost
never restated, so a deck exists that disagrees with your number.

Use `search_campaigns` to find the campaign, follow the `check_for_recap` call it
returns, and if a deck exists report the governed figure AND name the discrepancy
with its reason (gross versus net, and the missing test and wholesale exclusions).

Reporting only the governed number is not wrong, but it leaves the reader holding
a deck that contradicts you and no explanation of which to believe.

## Handling degraded confidence

The payload tells you when a result is weak. Disclose it in the answer body, not
as a footnote.

- **Below min_sample**: give the number, state the sample size, label it
  directional. "Services AOV is 62 dollars, but on 28 orders last month that is
  below the reliability threshold, so treat it as directional."
- **Period intersects a coverage hole**: give the covered periods only and name
  the boundary. Never extrapolate into the hole, and never infer the missing
  period from the covered one.
- **A definition caveat applies**: state the definition. If the metric is churn
  adjacent, say explicitly that churn is inferred from purchase silence and not
  observed.

## Handling absent concepts

When the concept is declared absent, the decline IS the answer:

1. State clearly that the data does not exist, and why (not collected, not
   supported by the data, or out of scope).
2. Offer the nearest available signals by name.
3. State plainly what those signals do NOT measure.
4. Produce no number for the absent concept. Not an estimate, not a proxy
   presented as the thing, not a range.

## Anti-patterns

- Reporting a number with no judgment attached.
- Using "improved" or "declined" without checking `direction`.
- Averaging a non additive metric across periods instead of re deriving it.
- Dropping the required caveats because the answer felt long.
- Comparing to the adjacent month across a seasonal boundary with no prior year.
- Answering an absent concept question with the nearest available metric dressed
  up as the thing that was asked for.
