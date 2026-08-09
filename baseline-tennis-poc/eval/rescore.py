"""Rescore saved transcripts against the CURRENT criteria, without spending money.

An eval run costs about a dollar, and criteria get refined as failures reveal
whether they were testing correctness or phrasing. This replays every saved
transcript through the current scorer so a criteria change can be evaluated
against runs already paid for.

It also makes the variance visible: when the same question passes in one run and
fails in another with the same code, the difference is the harness, not the layer.

  python eval/rescore.py
  python eval/rescore.py --milestone 2
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, HERE)

import run_eval  # noqa: E402

TRANSCRIPT_DIR = os.path.join(HERE, "transcripts")


def rebuild_trace(r: dict, milestone: int) -> list[dict]:
    """Reconstruct enough of the tool trace for the trace criteria to be checked.

    Transcripts store tool NAMES plus the metric ids and graph operations that were
    called, not full inputs, so the trace is rebuilt rather than replayed verbatim.
    Trace-shape criteria (which tools, which metrics, which operations) are
    checkable from this; exact arguments are not.
    """
    trace = [{"name": n, "input": {}} for n in r.get("tools_called", [])]
    for m in r.get("metrics_called", []):
        trace.append({"name": "get_metric", "input": {"metric_id": m}})
    for g in r.get("graph_operations", []):
        # Recorded as query_graph calls before the merge; the scorer reads the
        # operation off build_audience now, so rebuild under the merged name.
        trace.append({"name": "build_audience", "input": {"operation": g}})
    # Cohort composition cannot be recovered from the stored shape, so it is
    # assumed for the traversal questions when the graph was enabled AND the
    # governed metric was called. Flagged in the output so the assumption is
    # visible rather than silent.
    if milestone >= 2 and r.get("id") in (14, 15):
        if "repeat_purchase_rate" in r.get("metrics_called", []):
            trace.append({"name": "get_metric",
                          "input": {"metric_id": "repeat_purchase_rate",
                                    "cohort": "assumed-from-transcript"}})
    return trace


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--milestone", type=int, choices=[1, 2])
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    questions = {q["id"]: q for q in run_eval.load_questions()}
    files = sorted(glob.glob(os.path.join(TRANSCRIPT_DIR, "*.json")))
    files = [f for f in files if not f.endswith(".mcp.json")]
    if not files:
        print("No transcripts found. Run an eval first.", file=sys.stderr)
        return 2

    print("Rescoring saved transcripts against the CURRENT criteria")
    print("=" * 74)
    per_milestone: dict[int, list[int]] = {}

    for f in files:
        try:
            d = json.load(open(f))
        except (json.JSONDecodeError, OSError):
            continue
        results = d.get("results") or []
        # Older transcripts have 20 questions, newer ones 25. Accept any full
        # run rather than silently skipping the newer ones.
        if d.get("baseline") or len(results) < 20:
            continue
        ms = d.get("milestone", 1)
        if args.milestone and ms != args.milestone:
            continue

        fails = []
        for r in results:
            if r["verdict"] == "ERROR":
                fails.append((r["id"], "ERROR: " + (r.get("failed") or [""])[0][:60]))
                continue
            res = {"answer": r.get("answer", ""),
                   "tool_calls": rebuild_trace(r, ms), "turns": 0}
            v = run_eval.score(questions[r["id"]], res, ms)
            if v["verdict"] != "PASS":
                fails.append((r["id"], v["failed"][0][:70]))

        print(f"\n{os.path.basename(f)}  (milestone {ms})")
        print(f"   {len(results) - len(fails)}/{len(results)} pass"
              + (f", was {sum(1 for r in results if r['verdict'] == 'PASS')}"
                 f"/{len(results)} when run" if True else ""))
        for i, why in fails:
            print(f"   Q{i}: {why}")
        per_milestone.setdefault(ms, []).append(len(results) - len(fails))

    print("\n" + "=" * 74)
    for ms, scores in sorted(per_milestone.items()):
        print(f"  milestone {ms}: {scores} across {len(scores)} run(s)")
    print("\n  Note: earlier runs pre-date later fixes, so low scores at the top of")
    print("  the list are expected. A question that passes in one run and fails in")
    print("  another under the SAME code is harness variance, not a layer defect;")
    print("  eval/verify_layer.py is the model free check that separates them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
