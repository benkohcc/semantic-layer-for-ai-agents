"""Eval-only in-process agent loop.

The demo path is Claude Desktop or Claude Code over MCP, where the model is the
client and needs no API key. This module exists so the eval harness can score the
same tools automatically, over the Anthropic API.

It deliberately mirrors the MCP server: the same system instructions, the same
tool descriptions, the same implementations from tools.py. If the eval passes
here, the MCP path is exercising identical content.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tools as T

MODEL = os.environ.get("EVAL_MODEL", "claude-sonnet-4-6")
MAX_TURNS = 14


def _server_instructions(enable_graph: bool, baseline: bool) -> str:
    """Reuse the MCP server's own instruction text, so the eval tests it."""
    import mcp_server
    if baseline:
        return mcp_server.BASELINE_INSTRUCTIONS
    return mcp_server.CORE_INSTRUCTIONS + "\n\n" + (
        mcp_server.GRAPH_ON_INSTRUCTIONS if enable_graph
        else mcp_server.GRAPH_OFF_INSTRUCTIONS)


# Tool schemas for the Anthropic API. Descriptions are pulled from the MCP server
# where practical so the two surfaces stay in step.

def _tool_schemas(enable_graph: bool, baseline: bool) -> list[dict]:
    if baseline:
        return [
            {"name": "run_sql",
             "description": ("Run a read only SQL query against the Baseline "
                             "Tennis Co. SQLite warehouse. SELECT and WITH only."
                             "\n\nSchema:\n" + T.BASELINE_SCHEMA),
             "input_schema": {"type": "object", "properties": {
                 "query": {"type": "string"},
                 "limit": {"type": "integer", "default": 200}},
                 "required": ["query"]}},
            {"name": "naive_search",
             "description": ("Search marketing documents. Returns the matching "
                             "text chunks."),
             "input_schema": {"type": "object", "properties": {
                 "query": {"type": "string"},
                 "limit": {"type": "integer", "default": 6}},
                 "required": ["query"]}},
        ]

    schemas = [
        {"name": "get_started",
         "description": ("Orientation for the Baseline Tennis Co. marketing "
                         "domain: domain overview including the 'What this layer "
                         "cannot answer' section, question archetypes, governed "
                         "metrics, and conflict resolution rules. Cheap; call it "
                         "when unsure."),
         "input_schema": {"type": "object", "properties": {}}},
        {"name": "list_metrics",
         "description": ("List every governed metric with allowed dimensions, "
                         "additivity, and direction of goodness. Returns "
                         "definitions, never values."),
         "input_schema": {"type": "object", "properties": {}}},
        {"name": "get_playbook",
         "description": ("Return the step by step procedure for a question "
                         "archetype: 'metric-lookup', "
                         "'metric-decline-diagnosis', 'policy-question'"
                         + (", 'graph-traversal'" if enable_graph else "")
                         + ". Call this after classifying the question and BEFORE "
                         "other tools. Follow the steps in order."),
         "input_schema": {"type": "object", "properties": {
             "archetype": {"type": "string"}}, "required": ["archetype"]}},
        {"name": "discover_assets",
         "description": ("Search the catalog of available assets by meaning and "
                         "keyword. If the response contains 'known_gap', the "
                         "layer DECLARES it does not have this data: that is an "
                         "authoritative answer, not a search failure. Follow the "
                         "response_rule and do not substitute a nearby metric."),
         "input_schema": {"type": "object", "properties": {
             "query": {"type": "string"},
             "limit": {"type": "integer", "default": 6}},
             "required": ["query"]}},
        {"name": "search_knowledge",
         "description": ("Search marketing documents. Returns chunks WITH "
                         "governance metadata: authority (canonical, draft, "
                         "superseded), effective_date, supersession links. "
                         "Ordered by AUTHORITY first, similarity second. Answer "
                         "from canonical only; if 'stale_versions_present' "
                         "appears, say the stale version exists and is not in "
                         "force. Never use for a metric VALUE."),
         "input_schema": {"type": "object", "properties": {
             "query": {"type": "string"},
             "limit": {"type": "integer", "default": 6}},
             "required": ["query"]}},
        {"name": "get_metric",
         "description": (
             "Compute a governed metric. THE ONLY WAY TO GET A NUMBER.\n"
             "- metric_id: from list_metrics.\n"
             "- dimensions: group by, e.g. ['channel'] or ['segment'].\n"
             "- period: 'last_month' (default, last COMPLETE month), "
             "'last_6_months', 'trailing_12m', 'YYYY-MM', "
             "'YYYY-MM..YYYY-MM', 'all_time'.\n"
             "- filters: e.g. {'segment': 'competitive'} or {'campaign_id': 23}.\n"
             + ("- cohort: a cohort HANDLE string from build_audience "
                "(\"exposed\", \"comparison\", \"traced\", \"control\", or a "
                "named audience), or a list of customer "
                "ids. Computes the governed metric on just those customers, the "
                "ONLY sanctioned way to turn a cohort into a number. Prefer the "
                "handle; do not paste id lists.\n" if enable_graph else "")
             + "\nRead the interpretation payload before answering: 'direction' "
             "(cac and refund_rate are LOWER IS BETTER), 'confidence' (surface "
             "degraded confidence with its reason), 'required_caveats' (all of "
             "them belong in your answer), 'additive' (false means never average "
             "across periods)."),
         "input_schema": {"type": "object", "properties": {
             "metric_id": {"type": "string"},
             "dimensions": {"type": "array", "items": {"type": "string"}},
             "period": {"type": "string"},
             "filters": {"type": "object"},
             **({"cohort": {"oneOf": [
                    {"type": "string",
                     "description": "cohort handle from build_audience"},
                    {"type": "array", "items": {"type": "integer"}}]}}
                if enable_graph else {}),
         }, "required": ["metric_id"]}},
    ]

    if enable_graph:
        schemas.append({
            "name": "build_audience",
            "description": (
                "Select WHICH customers. Relationship mode (pass `operation` "
                "plus `params`) traverses referrals and purchases; a CLOSED "
                "operation set.\n"
                "- 'chain_stats': chain depth/size by grouping. params: "
                "{'group_by': 'acquisition_channel'}.\n"
                "- 'referral_chain': chains from a root or channel. params: "
                "{'root': id} or {'channel': name}, optional 'max_depth'.\n"
                "- 'exposed_cohort': params: {'edge_type': 'referred_by', "
                "'condition': 'referrer_churned'}.\n"
                "- 'trace_cohort': params: {'campaign_id': int, 'product_id': int} "
                "or {'campaign_id': int, 'recalled': true}.\n\n"
                "USE ONLY for unknown depth chains, propagation, or 3+ hop "
                "tracing. Counting referred customers or revenue from referred "
                "customers are METRIC questions; use get_metric.\n\n"
                "COMPOSITION RULE, MANDATORY: this SELECTS COHORTS and returns "
                "customer ids. It does NOT compute metrics. Pass the ids to "
                "get_metric as `cohort` to get any measured quantity. A number "
                "you compute from the id list is NOT the governed metric."),
            "input_schema": {"type": "object", "properties": {
                "operation": {"type": "string"},
                "params": {"type": "object"}}, "required": ["operation"]}})
    return schemas


def answer(question: str, enable_graph: bool = False, baseline: bool = False,
           verbose: bool = False, max_turns: int = MAX_TURNS) -> dict:
    """Run the agent loop and return the answer plus the full tool trace."""
    import anthropic

    client = anthropic.Anthropic()
    registry = T.all_tools(enable_graph=enable_graph, baseline=baseline)
    schemas = _tool_schemas(enable_graph, baseline)
    system = _server_instructions(enable_graph, baseline)

    messages: list[dict] = [{"role": "user", "content": question}]
    trace: list[dict] = []

    for turn in range(max_turns):
        resp = client.messages.create(
            model=MODEL, max_tokens=4096, system=system,
            tools=schemas, messages=messages)

        blocks = resp.content
        messages.append({"role": "assistant", "content": blocks})

        tool_uses = [b for b in blocks if getattr(b, "type", "") == "tool_use"]
        if not tool_uses:
            text = "".join(getattr(b, "text", "") for b in blocks
                           if getattr(b, "type", "") == "text")
            return {"answer": text.strip(), "tool_calls": trace,
                    "turns": turn + 1}

        results = []
        for tu in tool_uses:
            fn = registry.get(tu.name)
            if verbose:
                shown = {k: (f"<{len(v)} ids>" if isinstance(v, list)
                             and len(v) > 8 else v)
                         for k, v in (tu.input or {}).items()}
                print(f"  -> {tu.name}({json.dumps(shown, default=str)[:300]})")
            if not fn:
                out = {"error": f"Unknown tool {tu.name}"}
            else:
                try:
                    out = fn(**(tu.input or {}))
                except Exception as e:  # surfaced to the model to self-correct
                    out = {"error": f"{type(e).__name__}: {e}"}
            trace.append({"name": tu.name, "input": tu.input, "output": out})
            if verbose:
                print(f"     {json.dumps(out, default=str)[:600]}")
            results.append({"type": "tool_result", "tool_use_id": tu.id,
                            "content": json.dumps(out, default=str)[:120_000]})
        messages.append({"role": "user", "content": results})

    return {"answer": "(agent did not converge within the turn limit)",
            "tool_calls": trace, "turns": max_turns}
