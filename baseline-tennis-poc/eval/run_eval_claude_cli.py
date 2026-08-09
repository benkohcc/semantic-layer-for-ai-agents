"""Run the scored eval through the Claude Code CLI instead of the Anthropic API.

Same questions, same gold criteria, same scorer as run_eval.py. The difference is
who drives the tools: this runner shells out to `claude -p`, pointing it at the
MCP server with --mcp-config, so the model comes from your Claude Code login and
no separate ANTHROPIC_API_KEY is needed.

Usage is billed to your Claude Code account. Each question is a fresh session with
its own tool trace, and the run prints the cost it accumulated.

  python eval/run_eval_claude_cli.py                  milestone 1 gate
  python eval/run_eval_claude_cli.py --milestone 2     milestone 2 gate
  python eval/run_eval_claude_cli.py --only 1,4,16 -v
  python eval/run_eval_claude_cli.py --baseline        raw-SQL comparison run

Requires the `claude` CLI on PATH and an active Claude Code login.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, HERE)

import run_eval  # the scorer and question loader are shared  # noqa: E402

PY = os.path.join(ROOT, ".venv", "bin", "python")
SERVER = os.path.join(ROOT, "mcp_server.py")
TRANSCRIPT_DIR = os.path.join(HERE, "transcripts")

# Must stay in step with tools.SEMANTIC_TOOLS. A tool missing from this list is
# BLOCKED by claude -p, and the agent stops to ask permission instead of
# answering, which looks exactly like a layer failure and is not one.
SEMANTIC_TOOLS = ["get_started", "list_metrics", "get_playbook",
                  "discover_assets", "search_knowledge", "get_metric",
                  "search_campaigns", "category_affinity",
                  "build_audience"]
GRAPH_TOOLS = SEMANTIC_TOOLS + ["query_graph"]
BASELINE_TOOLS = ["run_sql", "naive_search"]

# Timeout per question. Diagnosis and traversal questions make many tool calls.
PER_QUESTION_TIMEOUT = 600

# `claude -p` is tuned for piping: it answers tersely, and left alone it will
# reduce a metric question to the bare figure. That is a property of the CLI
# harness, not of the semantic layer, and it would fail criteria that require the
# caveats to be surfaced. Claude Desktop, the actual demo surface, is
# conversational by default and needs no such nudge. This restores comparable
# verbosity so the eval measures the layer rather than the harness.
#
# It deliberately adds NO domain knowledge and NO procedure: everything about how
# to answer still has to come from the server instructions, tool descriptions, and
# playbooks.
VERBOSITY_NUDGE = (
    "Answer as you would in a normal analytical conversation, in prose, not as a "
    "terse CLI reply. A one line answer is WRONG here even when the number is "
    "right. The tool payloads carry required caveats, the governed definition, "
    "band judgments, confidence notes, and companion metrics; every one of those "
    "that the payload supplied belongs in your answer. In particular, when you "
    "report a metric, state what the governed definition includes and excludes."
)


def _assert_allowlist_current() -> None:
    """The allow-list must cover every semantic tool, or runs fail spuriously."""
    import tools as T
    missing = set(T.SEMANTIC_TOOLS) - set(SEMANTIC_TOOLS)
    if missing:
        raise SystemExit(
            f"eval/run_eval_claude_cli.py SEMANTIC_TOOLS is out of date: "
            f"{sorted(missing)} would be BLOCKED by claude -p, producing fake "
            "failures. Add them to the list.")


def mcp_config(server_name: str, extra_args: list[str]) -> str:
    cfg = {"mcpServers": {server_name: {"command": PY,
                                       "args": [SERVER] + extra_args}}}
    path = os.path.join(TRANSCRIPT_DIR, f"mcp-{server_name}.json")
    os.makedirs(TRANSCRIPT_DIR, exist_ok=True)
    with open(path, "w") as f:
        json.dump(cfg, f)
    return path


def parse_stream(lines: list[str]) -> tuple[str, list[dict], float, int]:
    """Pull the answer, the tool trace, cost, and turn count out of stream-json.

    Tool names arrive namespaced as mcp__<server>__<tool>; they are stripped back
    to bare names so the shared scorer sees the same trace shape it would from
    the in-process agent.
    """
    answer, trace, cost, turns = "", [], 0.0, 0
    pending: dict[str, dict] = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = d.get("type")
        if t == "assistant":
            for b in d.get("message", {}).get("content", []):
                if b.get("type") == "tool_use":
                    name = b.get("name", "")
                    bare = name.split("__")[-1] if name.startswith("mcp__") else name
                    entry = {"name": bare, "input": b.get("input") or {},
                             "output": None}
                    pending[b.get("id", "")] = entry
                    trace.append(entry)
        elif t == "user":
            for b in d.get("message", {}).get("content", []):
                if b.get("type") == "tool_result":
                    entry = pending.get(b.get("tool_use_id", ""))
                    if entry is not None:
                        content = b.get("content")
                        if isinstance(content, list):
                            content = " ".join(c.get("text", "")
                                               for c in content
                                               if isinstance(c, dict))
                        entry["output"] = content
        elif t == "result":
            answer = d.get("result") or ""
            cost = d.get("total_cost_usd") or 0.0
            turns = d.get("num_turns") or 0
    return answer, trace, cost, turns


def ask(question: str, cfg_path: str, server_name: str, tool_names: list[str],
        model: str, verbose: bool) -> dict:
    allowed = ",".join(f"mcp__{server_name}__{t}" for t in tool_names)
    cmd = [
        "claude", "-p", question,
        "--model", model,
        "--mcp-config", cfg_path,
        "--strict-mcp-config",
        "--allowed-tools", allowed,
        "--append-system-prompt", VERBOSITY_NUDGE,
        "--output-format", "stream-json",
        "--verbose",
    ]
    try:
        # stdin MUST be closed. `claude -p` inherits the parent's stdin and will
        # block forever waiting on it if that stdin is a live terminal, which is
        # what happens when this runner is itself launched from a shell session.
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL,
                              timeout=PER_QUESTION_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"answer": "", "tool_calls": [], "cost": 0.0, "turns": 0,
                "error": f"timed out after {PER_QUESTION_TIMEOUT}s"}

    answer, trace, cost, turns = parse_stream(proc.stdout.splitlines())
    if not answer and proc.returncode != 0:
        return {"answer": "", "tool_calls": trace, "cost": cost, "turns": turns,
                "error": (proc.stderr or proc.stdout or "").strip()[:500]}
    if verbose:
        for c in trace:
            shown = json.dumps(c["input"], default=str)
            if len(shown) > 220:
                shown = shown[:220] + "...}"
            print(f"      -> {c['name']}({shown})")
    return {"answer": answer, "tool_calls": trace, "cost": cost, "turns": turns}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--milestone", type=int, default=1, choices=[1, 2])
    ap.add_argument("--only", help="comma separated question ids, e.g. 1,4,16")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--baseline", action="store_true",
                    help="raw SQL tools only, for the comparison transcript")
    ap.add_argument("--model", default="sonnet",
                    help="model alias passed to claude -p (default: sonnet)")
    args = ap.parse_args()

    if not shutil.which("claude"):
        print("The 'claude' CLI is not on PATH. Install Claude Code, or use "
              "'cli.py eval' with an ANTHROPIC_API_KEY instead.", file=sys.stderr)
        return 2

    _assert_allowlist_current()
    questions = run_eval.load_questions()
    if args.only:
        wanted = {int(x.strip()) for x in args.only.split(",") if x.strip()}
        questions = [q for q in questions if q["id"] in wanted]

    enable_graph = args.milestone >= 2
    # One server, three ways to run it. Milestone 1 WITHHOLDS the graph so the
    # layer must decline traversal questions; milestone 2 is the default build.
    if args.baseline:
        server_name, extra, tool_names = ("semantic-layer-baseline",
                                          ["--baseline"], BASELINE_TOOLS)
    elif enable_graph:
        server_name, extra, tool_names = ("semantic-layer", [], GRAPH_TOOLS)
    else:
        server_name, extra, tool_names = ("semantic-layer", ["--no-graph"],
                                          SEMANTIC_TOOLS)
    cfg_path = mcp_config(server_name, extra)

    label = ("BASELINE MODE (no semantic layer)" if args.baseline else
             f"MILESTONE {args.milestone} GATE "
             f"(graph {'ENABLED' if enable_graph else 'disabled'})")
    print("=" * 74)
    print(f"  {label}")
    print(f"  driver: claude -p  |  model: {args.model}  |  server: {server_name}")
    print(f"  {len(questions)} questions. Billed to your Claude Code account.")
    print("=" * 74)

    results, total_cost = [], 0.0
    for q in questions:
        tag = ""
        if q.get("milestone") == 2:
            tag = " [graph]" if enable_graph else " [expects graceful decline]"
        if q.get("honesty"):
            tag = " [honesty]"
        print(f"\n--- Q{q['id']}{tag}: {q['question']}")

        res = ask(q["question"], cfg_path, server_name, tool_names, args.model,
                  args.verbose)
        total_cost += res.get("cost", 0.0)

        if res.get("error"):
            print(f"    ERROR: {res['error'][:300]}")
            results.append({"id": q["id"], "question": q["question"],
                            "verdict": "ERROR", "failed": [res["error"][:300]],
                            "passed": [], "tools_called": [], "answer": ""})
            continue

        if args.baseline:
            print(f"    tools: {[c['name'] for c in res['tool_calls']]}")
            print(f"    answer: {res['answer'][:400]}")
            results.append({"id": q["id"], "question": q["question"],
                            "verdict": "TRANSCRIPT", "passed": [], "failed": [],
                            "tools_called": [c["name"] for c in res["tool_calls"]],
                            "answer": res["answer"]})
            continue

        v = run_eval.score(q, res, args.milestone)
        v["cost_usd"] = res.get("cost", 0.0)
        results.append(v)
        print(f"    {v['verdict']}  tools={v['tools_called']}")
        if v["metrics_called"]:
            print(f"          metrics={v['metrics_called']}")
        if v["graph_operations"]:
            print(f"          graph={v['graph_operations']}")
        for f in v["failed"]:
            print(f"          - {f}")
        if args.verbose:
            print(f"          answer: {v['answer'][:500]}")

    print("\n" + "=" * 74)
    if args.baseline:
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
        print(f"\n  MILESTONE {args.milestone} GATE: {gate}")
    print(f"  total cost: ${total_cost:.4f}")

    os.makedirs(TRANSCRIPT_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = (f"cli-baseline-{stamp}.json" if args.baseline
            else f"cli-milestone{args.milestone}-{stamp}.json")
    path = os.path.join(TRANSCRIPT_DIR, name)
    with open(path, "w") as f:
        json.dump({"milestone": args.milestone, "baseline": args.baseline,
                   "driver": "claude-cli", "model": args.model,
                   "total_cost_usd": total_cost, "results": results}, f,
                  indent=2, default=str)
    print(f"  transcript: {os.path.relpath(path, ROOT)}")

    if args.baseline:
        return 0
    return 0 if all(r["verdict"] == "PASS" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
