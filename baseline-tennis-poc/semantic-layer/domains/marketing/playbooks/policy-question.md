---
archetype: policy-question
label: Policy and Definition Question
use_when:
  - The question asks what a policy, rule, or documented process says.
  - The question asks how something is defined, or what counts as X.
  - The question asks for criteria, thresholds, or terms.
do_not_use_when:
  - The question asks for a metric value. Use metric-lookup.
  - The question asks why a number moved. Use metric-decline-diagnosis.
required_tools: [search_knowledge]
optional_tools: [discover_assets, get_metric]
---

# Playbook: Policy and Definition Question

Answer from the document that is in force, cite its effective date, and say when
a stale version exists.

The corpus deliberately contains superseded documents, and none of them admit it.
Retrieval rank is not authority, and neither is the document text.

## Step 1: Retrieve candidates

Call `search_knowledge` with the policy topic. Retrieve several candidates rather
than taking the first hit. Multiple versions of the same policy will often come
back together, which is exactly the case this playbook exists to handle.

## Step 2: Rank by the REGISTRY, not by reading the document

This is the step people get wrong, and it is worth being precise about why.

**You cannot tell whether a document is current by reading it.** Real documents do
not announce their own obsolescence. A policy written in 2024 was simply the
policy; nobody went back and stamped it when the 2025 version landed, because the
person writing the replacement had no way to reach every copy of the old one. A
superseded document reads exactly like a current one, with the same confident tone
and the same internal consistency, because it WAS current when it was written.

The governance therefore comes from outside the text. Every hit carries a `status`
and an `effective_date` resolved from the document registry, and those fields are
the ranking, in this order:

1. **Status**: `in_force` beats `draft` beats `superseded` beats `withdrawn`.
2. **Effective date**: within a lineage, the later date wins. This is what
   separates two documents that were BOTH legitimately in force at different
   times, which status alone cannot do.
3. **Similarity**: only after the first two. A stale document that scores higher
   on similarity still loses, and `similarity_rank` shows you where governance
   overrode relevance.

Do not attempt to infer currency from a date printed in the document body, from
the tone, or from whether it mentions something recent. Those signals are
unreliable and the registry is not.

## Step 3: Answer from the in force document only

Quote or paraphrase the in force document. Do not blend two versions into one
answer, and do not mix an in force clause with a superseded one because the older
version covered a detail the current one omits. If the in force document is silent on part
of the question, say it is silent.

## Step 4: Cite the effective date

State which document you answered from and when it took effect. A policy answer
without a date is not verifiable.

## Step 5: Flag superseded and draft versions that surfaced

If a draft or superseded version appeared in retrieval, say so explicitly. This
matters more than it looks: the reader may well have that document open, and
nothing in it would tell them it is out of date.

> This is from the current refund policy, effective January 1. A 2024 draft with
> a shorter 30 day window also exists in the document set; it was never adopted
> and is not in force.

Naming it and dismissing it prevents the confusion; silently ignoring it does not,
because the reader has no way to reach that conclusion on their own.

## Step 6: Cross check against governed metrics where they overlap

When a policy question touches a number that a governed metric also covers, the
metric wins for the VALUE and the document wins for the RULE.

The refund policy states the rule for refunds. The `refund_rate` metric states
what refunds actually cost. Do not quote a figure from a document when a governed
metric covers the same concept.

## Anti-patterns

- Answering from the highest similarity chunk without checking the registry.
- Trying to judge currency by reading the document. You cannot; it will not say.
- Quoting the 2024 refund policy, which was never adopted and does not say so.
- Omitting the effective date.
- Blending clauses from two versions of the same policy.
- Failing to mention that a superseded version exists when it surfaced.
- Treating a confident tone or a recent sounding date as evidence of currency.
- Presenting a figure quoted inside a document as if it were a governed metric.
- Inventing a policy detail the document does not state. If it is silent, say so.
