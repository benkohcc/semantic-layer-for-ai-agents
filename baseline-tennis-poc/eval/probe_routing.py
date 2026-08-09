"""Do the TOOL DESCRIPTIONS alone route correctly?

The eval gates test the whole system: instructions, descriptions, playbooks and
the payloads all working together. That cannot tell you whether the descriptions
are doing their job, because a playbook can rescue a vague description.

This isolates them. The agent gets the tool descriptions and NOTHING else: no
server instructions, no playbooks, no domain overview. It is asked only to name
the first tool it would call. If a description is doing its job, the right tool is
obvious from the description alone.

Deliberately includes the hard cases: questions that look like one archetype and
belong to another, which is where a vague description costs the most.
"""
import asyncio
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (question, acceptable first tools, what makes it hard)
CASES = [
    # --- unambiguous, should be trivial --------------------------------
    ("What was revenue last month?", {"get_metric"}, "plain metric"),
    ("What is our refund policy?", {"search_knowledge"}, "plain document"),
    ("List the metrics available.", {"list_metrics"}, "plain listing"),

    # --- the misroute traps: look like X, are actually Y ---------------
    ("How many customers were referred to us?",
     {"get_metric", "list_metrics"},
     "MENTIONS referrals but is a count over an attribute, NOT graph"),
    ("What revenue came from referred customers?",
     {"get_metric", "list_metrics"},
     "MENTIONS referrals but is an aggregation with a filter, NOT graph"),
    ("Which acquisition channel produced the deepest referral chains?",
     {"build_audience", "get_playbook", "get_started", "discover_assets"},
     "unbounded depth, IS graph"),
    ("How many orders did we take last month?",
     {"get_metric", "list_metrics"},
     "a count, not a search"),
    ("What do racket buyers also buy?",
     {"category_affinity", "get_playbook", "discover_assets"},
     "affinity, not a metric slice"),
    ("Which rackets sell best to competitive players?",
     {"get_metric", "list_metrics", "discover_assets"},
     "product GRAIN metric, NOT affinity and NOT audience"),
    ("Who should I send a new racket promotion to?",
     {"build_audience", "get_playbook", "discover_assets", "get_started"},
     "audience selection"),
    ("Which campaign performed best last year?",
     {"search_campaigns", "get_metric", "discover_assets", "list_metrics"},
     "campaign brief + metric, two halves"),
    ("What is our email open rate?",
     {"get_metric", "list_metrics"},
     "metric, NOT the email documents"),
    ("Why did signups drop last month?",
     {"get_playbook", "get_metric", "get_started", "list_metrics"},
     "diagnosis, multi-step"),
    ("What is our NPS?",
     {"discover_assets", "get_started", "search_knowledge", "list_metrics"},
     "declared gap, must not fabricate"),
    ("What is our stringing turnaround?",
     {"search_knowledge", "discover_assets"},
     "document with a superseded twin"),
    ("What is our margin on rackets?",
     {"get_metric", "list_metrics", "discover_assets"},
     "metric that only recently existed"),
]

ADVERSARIAL = [
  ("Trace the referral network to find how many people each customer referred.",
   {"build_audience"},
   "says 'trace the referral network' but depth is 1: a metric, not traversal"),
  ("Search the documents for our current revenue figure.",
   {"search_knowledge"},
   "explicitly says search documents, but revenue is a governed metric"),
  ("Look up the email open rate in the email program overview document.",
   {"search_knowledge"},
   "names the document, but the VALUE must come from the metric"),
  ("Give me the customer email addresses for competitive players in the west.",
   set(),
   "asks for PII that does not exist; any tool is fine, the ANSWER must decline"),
  ("Use the graph to work out revenue from referred customers.",
   {"build_audience"},
   "says 'use the graph' but it is an aggregation with a filter"),
  ("Build an audience of everyone and tell me the total revenue.",
   {"build_audience"},
   "audience of everyone is not a selection; revenue is a plain metric"),
  ("What was the revenue in the spring campaign recap deck?",
   {"search_knowledge"},
   "asks for the DECK figure, but governed metric overrides the document"),
  ("Cross-sell analysis: what is the average order value for racket buyers?",
   {"category_affinity"},
   "framed as cross-sell but asks for a metric slice"),
]

SYSTEM = (
    "You have the tools below available. For the user's question, reply with "
    "ONLY the name of the FIRST tool you would call, nothing else. No "
    "explanation, no punctuation, just the tool name."
)


def ask(question: str, cfg: str) -> str:
    allowed = ",".join(
        f"mcp__semantic-layer__{t}" for t in
        ["get_started", "list_metrics", "get_playbook", "discover_assets",
         "search_knowledge", "get_metric", "search_campaigns",
         "category_affinity", "build_audience"])
    cmd = ["claude", "-p",
           f"{question}\n\n(Reply with only the tool name you would call first.)",
           "--model", "sonnet", "--mcp-config", cfg, "--strict-mcp-config",
           "--allowed-tools", allowed,
           "--append-system-prompt", SYSTEM,
           "--output-format", "json"]
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=180)
        d = json.loads(p.stdout)
        raw = (d.get("result") or "").strip().strip(".`*").split()[-1]
        # Tools come back namespaced as mcp__<server>__<tool>.
        return raw.split("__")[-1]
    except Exception as e:
        return f"ERROR:{type(e).__name__}"


def main():
    cfg = os.path.join(ROOT, "eval", "transcripts", "mcp-semantic-layer.json")
    if not os.path.exists(cfg):
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        json.dump({"mcpServers": {"semantic-layer": {
            "command": os.path.join(ROOT, ".venv", "bin", "python"),
            "args": [os.path.join(ROOT, "mcp_server.py")]}}},
            open(cfg, "w"))

    print("=" * 78)
    print("ROUTING FROM TOOL DESCRIPTIONS ALONE")
    print("no server instructions, no playbooks, no domain overview")
    print("=" * 78)
    ok = 0
    misroutes = []
    for q, accept, why in CASES:
        got = ask(q, cfg)
        good = got in accept
        ok += good
        mark = "OK  " if good else "MISS"
        print(f"  {mark} {q[:46]:46s} -> {got}")
        if not good:
            print(f"       expected one of {sorted(accept)}")
            print(f"       ({why})")
            misroutes.append((q, got, accept, why))
    print()
    print(f"  {ok}/{len(CASES)} routed correctly from descriptions alone")

    print()
    print("=" * 78)
    print("ADVERSARIAL PHRASING: wording that points at the WRONG tool")
    print("=" * 78)
    pulled = 0
    for q, forbidden, why in ADVERSARIAL:
        got = ask(q, cfg)
        bad = got in forbidden
        pulled += bad
        print(f"  {'PULLED' if bad else 'held  '} {q[:52]:52s} -> {got}")
        if bad:
            print(f"          trap: {why}")
    print()
    print(f"  resisted {len(ADVERSARIAL)-pulled}/{len(ADVERSARIAL)} misleading phrasings")

    failed = len(CASES) - ok + pulled
    print()
    print("  NOTE: this costs a few cents per run and needs the claude CLI. It is")
    print("  the only check that isolates the DESCRIPTIONS from the instructions")
    print("  and playbooks, so a vague description cannot hide behind them.")
    return failed


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
