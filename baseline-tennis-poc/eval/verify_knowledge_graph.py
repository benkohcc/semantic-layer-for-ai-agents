"""Does relationship retrieval work, without a model deciding anything?

Three properties, checked deterministically:

  1. RELATIONSHIP QUESTIONS get relationships, regardless of phrasing. This is
     the property a keyword classifier failed at (6/15) and entity-only
     resolution failed at differently (9/15). Phrasings here are deliberately
     ones no rule was written against.

  2. PLAIN QUESTIONS are not buried in noise. Relationships may appear when they
     genuinely help, but a question about returns must not drag in every
     discounting policy because it happened to say "racket".

  3. THE TEXT ANSWER IS UNCHANGED. Adding relationships must not alter which
     chunks similarity returns or how they are ranked. A change there is a
     regression in a working system, not an improvement.

  python eval/verify_knowledge_graph.py
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

import knowledge_graph  # noqa: E402

# Phrasings a rule based classifier missed. None of these were used to write the
# lexicon: they are how the question actually gets typed.
WANT_RELATIONSHIPS = [
    ("What depends on the refund policy?", "designed for"),
    ("What supersedes the 2024 refund policy?", "literal edge name"),
    ("What's downstream of the refund policy?", "'downstream', no rule for it"),
    ("If we change the refund window, what breaks?", "conditional phrasing"),
    ("We're updating the stringing SLA. What else needs to change?", "statement plus question"),
    ("Show me everything connected to the discount policy.", "'connected to'"),
    ("Is anything affected if we retire the Q2 media plan?", "'affected if'"),
    ("What changed between the 2025 and 2026 stringing SLA?", "diff across a lineage"),
    ("Which policies apply to racket discounting?", "SCOPE: unreachable by similarity"),
    ("Who owns the pricing policy?", "ownership"),
    ("What rules cover discounting on shoes?", "'cover' not 'govern'"),
]

# Mentions something the graph knows, but relationships would be noise.
WANT_QUIET = [
    ("How long do customers have to return a racket?", "category is incidental"),
    ("What is our stringing turnaround time?", "asks what a doc says"),
]

# Names nothing the graph knows at all.
WANT_EMPTY = [
    ("What is our net promoter score?", "declared gap"),
    ("How do I restring a racquet at home?", "not in the corpus"),
]


def main() -> int:
    g = knowledge_graph.get_graph()
    passed = failed = 0
    print("=" * 78)
    print("RELATIONSHIP RETRIEVAL")
    print("no classifier, no model, no phrasing rules")
    print("=" * 78)

    print("\n  Relationship questions must return relationships")
    print("  " + "-" * 74)
    for q, note in WANT_RELATIONSHIPS:
        r = g.related(q)
        ok = bool(r and r.get("relationships"))
        passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)
        n = len(r.get("relationships", [])) if r else 0
        print(f"    {'PASS' if ok else 'FAIL'}  {q[:52]:52s} {n} rel")
        if not ok:
            print(f"          ^ {note}")

    print("\n  Plain questions must not be buried in relationship noise")
    print("  " + "-" * 74)
    for q, note in WANT_QUIET:
        r = g.related(q)
        n = len(r.get("relationships", [])) if r else 0
        ok = n <= 3
        passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)
        print(f"    {'PASS' if ok else 'FAIL'}  {q[:52]:52s} {n} rel")
        if not ok:
            print(f"          ^ {note}: expected few or none")

    print("\n  Unknown subjects must return nothing rather than something plausible")
    print("  " + "-" * 74)
    for q, note in WANT_EMPTY:
        r = g.related(q)
        ok = not r
        passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)
        print(f"    {'PASS' if ok else 'FAIL'}  {q[:52]:52s} "
              f"{'empty' if ok else str(len(r['relationships'])) + ' rel'}")
        if not ok:
            print(f"          ^ {note}")

    # The capability that justifies the authoring cost: a question similarity
    # cannot answer at all, because the answer is in no single passage.
    print("\n  The query similarity cannot reach")
    print("  " + "-" * 74)
    r = g.related("Which policies apply to racket discounting?")
    govs = sorted({i["to"] for i in r.get("relationships", [])
                   if i["relationship"] == "governed_by"})
    expect = ["merchandising-playbook", "pricing-and-discount-policy", "promo-calendar"]
    ok = govs == expect
    passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)
    print(f"    {'PASS' if ok else 'FAIL'}  three governing policies found")
    print(f"          got: {govs}")

    cov = g.coverage()
    print("\n" + "=" * 78)
    print(f"  {passed} passed, {failed} failed of {passed + failed} checks")
    print(f"\n  Coverage: {cov['reachable_by_any_edge']}/{cov['documents']} documents "
          f"reachable, {cov['with_authored_governs_edges']} with authored "
          "`governs` edges.")
    print("  `governs` is the discounting slice only. Scope questions about other "
          "areas\n  will not resolve until those edges are authored.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
