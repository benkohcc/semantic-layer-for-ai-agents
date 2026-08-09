#!/usr/bin/env python
"""Development and evaluation CLI.

The MCP server is the demo surface. This is for building, debugging, and scoring.

  python cli.py seed                    generate the database, documents, benchmarks
  python cli.py index                   build the retrieval index
  python cli.py tool NAME '{"json": 1}' call any tool directly, no LLM involved
  python cli.py tools                   list callable tools
  python cli.py ask "QUESTION"          in-process agent (needs ANTHROPIC_API_KEY)
  python cli.py eval                    milestone 1 gate
  python cli.py eval --milestone 2      milestone 2 gate
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "src"))


def cmd_seed(args) -> int:
    return subprocess.call([sys.executable, os.path.join(HERE, "data", "seed.py")])


def cmd_index(args) -> int:
    import retrieval
    print("Building the retrieval index...")
    stats = retrieval.build_index()
    print(f"Done: {stats['document_chunks']} document chunks, "
          f"{stats['catalog_entries']} catalog entries.")
    return 0


def cmd_tools(args) -> int:
    import tools as T
    print("Semantic tools (always available):")
    for name in sorted(T.SEMANTIC_TOOLS):
        print(f"  {name}")
    print("\nGraph tools (--enable-graph on the server):")
    print("  query_graph")
    print("\nBaseline-only tools (--baseline on the server):")
    for name in sorted(T.BASELINE_TOOLS):
        print(f"  {name}")
    return 0


def cmd_tool(args) -> int:
    """Call a tool directly. This verifies the semantic layer with no model."""
    import tools as T
    registry = dict(T.SEMANTIC_TOOLS)
    registry.update(T.BASELINE_TOOLS)
    try:
        registry.update(T._graph_tools())
    except Exception:
        pass

    fn = registry.get(args.name)
    if not fn:
        print(f"Unknown tool '{args.name}'. Available: "
              f"{', '.join(sorted(registry))}", file=sys.stderr)
        return 2

    kwargs = {}
    if args.payload:
        try:
            kwargs = json.loads(args.payload)
        except json.JSONDecodeError as e:
            print(f"Payload is not valid JSON: {e}", file=sys.stderr)
            return 2
        if not isinstance(kwargs, dict):
            print("Payload must be a JSON object.", file=sys.stderr)
            return 2

    result = fn(**kwargs)
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_ask(args) -> int:
    import agent
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. The MCP demo path does not need it, "
              "but 'ask' and 'eval' do.", file=sys.stderr)
        return 2
    result = agent.answer(args.question, enable_graph=args.enable_graph,
                          baseline=args.baseline, verbose=args.verbose)
    print("\n" + "=" * 70)
    print("ANSWER")
    print("=" * 70)
    print(result["answer"])
    if not args.verbose:
        print(f"\n[{len(result['tool_calls'])} tool calls: "
              f"{', '.join(c['name'] for c in result['tool_calls'])}]")
    return 0


def cmd_eval(args) -> int:
    sys.path.insert(0, os.path.join(HERE, "eval"))
    if getattr(args, "driver", "api") == "claude-cli":
        # Drives the eval through `claude -p` against the MCP server, so the
        # model comes from a Claude Code login instead of an API key.
        cmd = [sys.executable, os.path.join(HERE, "eval",
                                            "run_eval_claude_cli.py"),
               "--milestone", str(args.milestone)]
        if args.only:
            cmd += ["--only", args.only]
        if args.verbose:
            cmd.append("--verbose")
        if args.baseline:
            cmd.append("--baseline")
        if getattr(args, "model", None):
            cmd += ["--model", args.model]
        return subprocess.call(cmd)
    import run_eval
    return run_eval.main(milestone=args.milestone, only=args.only,
                         verbose=args.verbose, baseline=args.baseline)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("seed", help="generate database, documents, benchmarks")
    sub.add_parser("index", help="build the retrieval index")
    sub.add_parser("tools", help="list callable tools")

    p = sub.add_parser("tool", help="call a tool directly, no LLM")
    p.add_argument("name")
    p.add_argument("payload", nargs="?", default="")

    p = sub.add_parser("ask", help="in-process agent over the tools")
    p.add_argument("question")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="show tool calls and payloads")
    p.add_argument("--enable-graph", action="store_true")
    p.add_argument("--baseline", action="store_true",
                   help="use raw SQL tools instead of the semantic layer")

    p = sub.add_parser("eval", help="run the evaluation gate")
    p.add_argument("--milestone", type=int, default=1, choices=[1, 2])
    p.add_argument("--only", help="comma separated question ids, e.g. 1,4,16")
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--baseline", action="store_true",
                   help="run in baseline mode to capture comparison transcripts")
    p.add_argument("--driver", choices=["api", "claude-cli"], default="api",
                   help="'api' uses ANTHROPIC_API_KEY; 'claude-cli' drives "
                        "`claude -p` against the MCP server and needs no key")
    p.add_argument("--model", help="model alias for the claude-cli driver")

    args = ap.parse_args()
    return {
        "seed": cmd_seed, "index": cmd_index, "tools": cmd_tools,
        "tool": cmd_tool, "ask": cmd_ask, "eval": cmd_eval,
    }[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
