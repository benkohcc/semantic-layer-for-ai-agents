"""Check the marketer question set against the layer, with no model involved.

eval/marketer_questions.yaml classifies ~70 questions a marketer would actually
ask into support levels. This script verifies each classification is still TRUE:

  supported / needs_metric / needs_access_path / needs_attribute
      -> the layer must now answer it
  must_decline
      -> the layer must DECLARE the gap, so the question gets a named refusal
         rather than falling through silently

A question that silently falls through is the worst case: it is neither answered
nor honestly declined, and the agent is left to improvise.

  python eval/verify_marketer_coverage.py
"""

from __future__ import annotations

import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

import tools as T  # noqa: E402
from catalog import get_catalog  # noqa: E402

QUESTIONS = os.path.join(HERE, "marketer_questions.yaml")


def routes(cat, q: str) -> tuple[bool, str]:
    """Does the layer route this question to an asset, a path, or a declared gap?"""
    gap = cat.resolve_absent_concept(q)
    if gap:
        return True, f"declared gap ({gap[0]['status']})"
    hits = cat.resolve_concept(q)
    if hits:
        return True, f"-> {hits[0]['resolves_to']}"
    # Retrieval is a legitimate route for document questions.
    try:
        sk = T.search_knowledge(q, limit=2)
        hits2 = sk.get("hits") or []
        if hits2 and hits2[0]["distance"] < 0.72:
            return True, f"-> document: {hits2[0]['title']}"
    except Exception:
        pass
    return False, "NOTHING"


def main() -> int:
    cat = get_catalog()
    with open(QUESTIONS) as f:
        spec = yaml.safe_load(f)

    total = ok = 0
    problems: list[tuple[str, str, str]] = []
    by_support: dict[str, list[bool]] = {}

    for cat_block in spec["categories"]:
        print(f"\n{'=' * 78}")
        print(f"{cat_block['name']}")
        print("=" * 78)
        for item in cat_block["questions"]:
            q, support = item["q"], item["support"]
            total += 1
            routed, how = routes(cat, q)
            by_support.setdefault(support, []).append(routed)

            if support == "must_decline":
                # A correctly unanswerable question must be DECLARED, so the agent
                # refuses with a reason instead of improvising.
                gap = cat.resolve_absent_concept(q)
                good = bool(gap)
                label = ("DECLARED" if good else "FALLS THROUGH")
                if not good:
                    problems.append((q, support, "no declared gap covers this"))
            else:
                good = routed
                label = ("ROUTED" if good else "UNROUTED")
                if not good:
                    problems.append((q, support, how))
            ok += 1 if good else 0
            mark = "OK  " if good else "GAP "
            print(f"  {mark} [{support:17s}] {q[:52]:52s} {label}")

    print(f"\n{'=' * 78}")
    print("SUMMARY BY SUPPORT LEVEL")
    print("=" * 78)
    for support, results in sorted(by_support.items()):
        n = len(results)
        good = sum(results)
        note = ("declared" if support == "must_decline" else "routed")
        print(f"  {support:18s} {good}/{n} {note}")

    print(f"\n  {ok}/{total} questions are either answerable or honestly declined")
    if problems:
        print("\n  Problems:")
        for q, support, why in problems:
            print(f"    [{support}] {q}")
            print(f"        {why}")
        return 1
    print("\n  Every marketer question resolves to an asset, an access path, or a")
    print("  declared gap. None fall through silently.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
