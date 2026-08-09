"""Evaluation harness.

Scores the TOOL TRACE as well as the answer text. A correct number reached the
wrong way is a FAIL: raw SQL where a governed metric exists, or a metric
recomputed outside the metrics engine. The trace is what proves the mechanism,
and the mechanism is the thing being demonstrated.

For honesty questions, a confident fabricated answer is the worst outcome and is
scored below a wrong-but-caveated one.

  python cli.py eval                  milestone 1 gate (20 questions)
  python cli.py eval --milestone 2    milestone 2 gate (20 questions, graph on)
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

QUESTIONS_PATH = os.path.join(HERE, "questions.yaml")
TRANSCRIPT_DIR = os.path.join(HERE, "transcripts")


def _seed_facts() -> dict:
    """Values published by the seeder, so gold figures follow the data."""
    path = os.path.join(ROOT, "data", "seed_facts.json")
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def load_questions() -> list[dict]:
    """Load questions, resolving any {{fact}} placeholders against seed_facts.

    A hardcoded expected value tests "the data has not changed", which is not what
    these questions are for. A placeholder like {{gold.net_revenue_last_month}}
    keeps the assertion about the ANSWER while the figure follows the seed.
    """
    with open(QUESTIONS_PATH) as f:
        raw = f.read()
    facts = _seed_facts()

    def resolve(m):
        path = m.group(1).strip().split(".")
        cur = facts
        for key in path:
            if not isinstance(cur, dict) or key not in cur:
                return m.group(0)  # leave unresolved rather than invent a value
            cur = cur[key]
        return str(cur)

    raw = re.sub(r"\{\{([a-z_.]+)\}\}", resolve, raw)
    return yaml.safe_load(raw)["questions"]


# ---------------------------------------------------------------- number checks

# A leading minus only counts when it is not glued to a word: "etc.)-then"
# was being parsed as the number -1.0 and flagged as a fabricated figure.
NUMBER_RE = re.compile(r"(?<![A-Za-z])-?\$?\d[\d,]*\.?\d*\s*%?")


def extract_numbers(text: str) -> list[float]:
    out = []
    for m in NUMBER_RE.finditer(text):
        raw = m.group(0).replace(",", "").replace("$", "").replace("%", "").strip()
        try:
            out.append(float(raw))
        except ValueError:
            continue
    return out


def number_present(text: str, target: float, tol: float) -> bool:
    """Match the target directly, or as a percentage of a 0-1 rate."""
    nums = extract_numbers(text)
    for n in nums:
        if abs(n - target) <= tol:
            return True
        # A rate reported as 0.2332 when the gold is 23.32, or the reverse.
        if target > 1 and abs(n * 100 - target) <= tol:
            return True
        if target < 1 and abs(n / 100 - target) <= tol:
            return True
    return False


# ---------------------------------------------------------------- scoring


def score(q: dict, result: dict, milestone: int) -> dict:
    """Return a verdict dict with pass/fail and the reasons."""
    answer = (result.get("answer") or "")
    low = answer.lower()
    trace = result.get("tool_calls", [])
    called = [c["name"] for c in trace]

    # Milestone-1 behavior for graph questions is a graceful decline, which has
    # its own criteria block.
    is_m2_question = q.get("milestone") == 2
    use_m1_criteria = is_m2_question and milestone == 1
    crit = q.get("criteria_m1" if use_m1_criteria else "criteria") or {}

    passed: list[str] = []
    failed: list[str] = []

    # ---- tool trace -------------------------------------------------
    for t in crit.get("tools_required", []):
        if t in called:
            passed.append(f"called {t}")
        else:
            failed.append(f"MISSING required tool call: {t}")
    any_of = crit.get("tools_required_any") or []
    if any_of:
        hit = [t for t in any_of if t in called]
        if hit:
            passed.append(f"reached the content via {hit[0]}")
        else:
            failed.append(f"MISSING any of these tool calls: {any_of}")
    for t in crit.get("tools_forbidden", []):
        if t in called:
            failed.append(f"FORBIDDEN tool call used: {t}")
        else:
            passed.append(f"avoided {t}")

    # ---- metric ids actually requested ------------------------------
    metrics_called = [c["input"].get("metric_id") for c in trace
                      if c["name"] == "get_metric"]
    for mid in crit.get("metric_required", []):
        if mid in metrics_called:
            passed.append(f"resolved metric {mid}")
        else:
            failed.append(f"MISSING get_metric call for '{mid}' "
                          f"(called: {metrics_called or 'none'})")

    wanted_any = crit.get("metric_required_any") or []
    if wanted_any:
        hit = [m for m in wanted_any if m in metrics_called]
        if hit:
            passed.append(f"resolved metric {hit[0]}")
        else:
            failed.append(f"MISSING get_metric call for any of {wanted_any} "
                          f"(called: {metrics_called or 'none'})")

    # ---- graph operations -------------------------------------------
    # Relationship operations arrive through build_audience since the merge;
    # older transcripts recorded them under query_graph. Accept both.
    graph_ops = [c["input"].get("operation") for c in trace
                 if c["name"] in ("build_audience", "build_audience")
                 and c["input"].get("operation")]
    wanted_ops = crit.get("graph_operations_any", [])
    if wanted_ops:
        if set(graph_ops) & set(wanted_ops):
            passed.append(f"graph operation {[o for o in graph_ops if o in wanted_ops]}")
        else:
            failed.append(f"MISSING graph operation, expected one of {wanted_ops} "
                          f"(used: {graph_ops or 'none'})")

    # ---- cohort composition: the number must come from the metrics engine
    if crit.get("cohort_composition_required"):
        composed = any(c["name"] == "get_metric" and c["input"].get("cohort")
                       for c in trace)
        if composed:
            passed.append("composed graph cohort through get_metric (cohort filter)")
        else:
            failed.append(
                "COMPOSITION VIOLATION: no get_metric call carried a cohort "
                "filter. A cohort metric must be computed by the metrics engine, "
                "not recomputed from the id list.")

    # ---- required text ----------------------------------------------
    for needle in crit.get("must_contain", []):
        if needle.lower() in low:
            passed.append(f"mentions '{needle}'")
        else:
            failed.append(f"MISSING required mention: '{needle}'")

    for group in crit.get("must_contain_any", []):
        if any(n.lower() in low for n in group):
            hit = next(n for n in group if n.lower() in low)
            passed.append(f"mentions '{hit}'")
        else:
            failed.append(f"MISSING any of: {group}")

    for needle in crit.get("must_not_contain", []):
        if needle.lower() in low:
            failed.append(f"FORBIDDEN content present: '{needle}'")

    # ---- numbers ----------------------------------------------------
    for spec in crit.get("numbers_expected", []):
        val, tol = spec["value"], spec.get("tolerance", 0.5)
        if number_present(answer, val, tol):
            passed.append(f"reports {val} (+/-{tol})")
        else:
            failed.append(f"MISSING expected value {val} (+/-{tol})")

    # ---- fabrication check for declines -----------------------------
    # For a capability or scope decline, any substantive figure is a fabrication.
    if crit.get("must_not_contain_numbers"):
        nums = [n for n in extract_numbers(answer)
                # Ignore years, small ordinals, and list numbering.
                if not (1900 <= n <= 2100) and n not in (0, 1, 2, 3, 4, 5, 12)]
        if nums:
            failed.append(
                f"FABRICATION RISK: answer contains figures {nums[:5]} where a "
                "clean decline was required")
        else:
            passed.append("no fabricated figures")

    verdict = "PASS" if not failed else "FAIL"
    return {
        "id": q["id"], "question": q["question"], "verdict": verdict,
        "mode": ("graceful_decline" if use_m1_criteria else "full"),
        "passed": passed, "failed": failed,
        "tools_called": called, "metrics_called": metrics_called,
        "graph_operations": graph_ops,
        "answer": answer, "turns": result.get("turns"),
    }


# ---------------------------------------------------------------- runner


def main(milestone: int = 1, only: str | None = None, verbose: bool = False,
         baseline: bool = False) -> int:
    import agent

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. The eval harness needs it; the MCP "
              "demo path does not.", file=sys.stderr)
        return 2

    questions = load_questions()
    if only:
        wanted = {int(x.strip()) for x in only.split(",") if x.strip()}
        questions = [q for q in questions if q["id"] in wanted]

    enable_graph = milestone >= 2
    label = ("BASELINE MODE (no semantic layer)" if baseline
             else f"MILESTONE {milestone} GATE (graph "
                  f"{'ENABLED' if enable_graph else 'disabled'})")

    print("=" * 74)
    print(f"  {label}")
    print(f"  {len(questions)} questions, model={agent.MODEL}")
    print("=" * 74)

    results = []
    for q in questions:
        tag = ""
        if q.get("milestone") == 2:
            tag = " [graph]" if enable_graph else " [expects graceful decline]"
        if q.get("honesty"):
            tag = " [honesty]"
        print(f"\n--- Q{q['id']}{tag}: {q['question']}")

        try:
            res = agent.answer(q["question"], enable_graph=enable_graph,
                               baseline=baseline, verbose=verbose)
        except Exception as e:
            print(f"    AGENT ERROR: {type(e).__name__}: {e}")
            results.append({"id": q["id"], "question": q["question"],
                            "verdict": "ERROR", "failed": [str(e)],
                            "passed": [], "tools_called": [], "answer": ""})
            continue

        if baseline:
            # Baseline runs are for transcript capture, not scoring: there is no
            # semantic layer to hold to these criteria.
            print(f"    tools: {[c['name'] for c in res['tool_calls']]}")
            print(f"    answer: {res['answer'][:400]}")
            results.append({"id": q["id"], "question": q["question"],
                            "verdict": "TRANSCRIPT", "passed": [], "failed": [],
                            "tools_called": [c["name"] for c in res["tool_calls"]],
                            "answer": res["answer"]})
            continue

        v = score(q, res, milestone)
        results.append(v)
        mark = "PASS" if v["verdict"] == "PASS" else "FAIL"
        print(f"    {mark}  tools={v['tools_called']}")
        if v["metrics_called"]:
            print(f"          metrics={v['metrics_called']}")
        if v["graph_operations"]:
            print(f"          graph={v['graph_operations']}")
        for f in v["failed"]:
            print(f"          - {f}")
        if verbose:
            print(f"          answer: {v['answer'][:500]}")

    # ---- summary ----------------------------------------------------
    print("\n" + "=" * 74)
    if baseline:
        print("  BASELINE TRANSCRIPTS CAPTURED (not scored)")
    else:
        n_pass = sum(1 for r in results if r["verdict"] == "PASS")
        n_fail = sum(1 for r in results if r["verdict"] == "FAIL")
        n_err = sum(1 for r in results if r["verdict"] == "ERROR")
        print(f"  RESULT: {n_pass} passed, {n_fail} failed, {n_err} errored "
              f"of {len(results)}")
        print("=" * 74)
        for r in results:
            if r["verdict"] != "PASS":
                print(f"  Q{r['id']}: {r['verdict']}")
                for f in r["failed"][:4]:
                    print(f"      {f}")
        gate = "PASSED" if n_pass == len(results) else "FAILED"
        print(f"\n  MILESTONE {milestone} GATE: {gate}")

    os.makedirs(TRANSCRIPT_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = (f"baseline-{stamp}.json" if baseline
            else f"milestone{milestone}-{stamp}.json")
    path = os.path.join(TRANSCRIPT_DIR, name)
    with open(path, "w") as f:
        json.dump({"milestone": milestone, "baseline": baseline,
                   "model": agent.MODEL, "results": results}, f, indent=2,
                  default=str)
    print(f"\n  transcript: {os.path.relpath(path, ROOT)}")

    if baseline:
        return 0
    return 0 if all(r["verdict"] == "PASS" for r in results) else 1


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--milestone", type=int, default=1, choices=[1, 2])
    ap.add_argument("--only")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--baseline", action="store_true")
    a = ap.parse_args()
    sys.exit(main(a.milestone, a.only, a.verbose, a.baseline))
