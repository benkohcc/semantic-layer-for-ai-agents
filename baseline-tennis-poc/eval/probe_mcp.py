"""Drive the MCP server over stdio like a real client, and verify gating."""
import asyncio
import json
import os
import sys

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, ".venv", "bin", "python")


async def probe(extra_args, label):
    params = StdioServerParameters(
        command=PY, args=[os.path.join(ROOT, "mcp_server.py")] + extra_args,
        cwd=ROOT, env={**os.environ})
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            init = await session.initialize()
            tools = await session.list_tools()
            names = sorted(t.name for t in tools.tools)
            print(f"\n{'='*70}\n{label}\n{'='*70}")
            print("server name:", init.server_info.name)
            instr = init.instructions or ""
            print(f"instructions: {len(instr)} chars")
            print("tools:", names)
            try:
                prompts = await session.list_prompts()
                print(f"prompts: {len(prompts.prompts)}")
            except Exception as e:
                print("prompts: error", e)
            return names, instr, session


async def call_check():
    params = StdioServerParameters(
        command=PY, args=[os.path.join(ROOT, "mcp_server.py")],
        cwd=ROOT, env={**os.environ})
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            print(f"\n{'='*70}\nLIVE TOOL CALLS (milestone 1 server)\n{'='*70}")

            res = await session.call_tool("get_metric",
                                          {"metric_id": "email_open_rate",
                                           "period": "last_month"})
            payload = json.loads(res.content[0].text)
            v = payload["results"][0]["value"]
            band = payload["interpretation"]["evaluation"]["comparison"]["reading"]
            print(f"get_metric(email_open_rate) = {v:.4f}")
            print(f"  band: {band}")
            print(f"  caveats: {len(payload['interpretation']['framing']['required_caveats'])}")

            res = await session.call_tool("get_playbook",
                                          {"archetype": "policy-question"})
            pb = json.loads(res.content[0].text)
            print(f"get_playbook(policy-question) = {len(pb['playbook'])} chars")

            res = await session.call_tool("search_knowledge",
                                          {"query": "refund policy"})
            sk = json.loads(res.content[0].text)
            print("search_knowledge(refund policy):")
            for h in sk["hits"][:5]:
                print(f"   {h['status']:11s} {h['title']}")
            stale = (sk.get("stale_versions_present") or {}).get("documents", [])
            print("   stale flagged:", [d["title"] for d in stale])

            res = await session.call_tool("discover_assets", {"query": "NPS"})
            da = json.loads(res.content[0].text)
            print("discover_assets(NPS) known_gap:",
                  da.get("known_gap", {}).get("status"))


async def main():
    n1, i1, _ = await probe(["--no-graph"], "DEMO: --no-graph, must decline traversal")
    assert "build_audience" in n1, "build_audience must exist in every semantic mode"
    assert "run_sql" not in n1, "run_sql leaked into the semantic server"
    assert "no registered access path" in i1.lower() or "no relationship traversal" in i1.lower()
    print("PASS: run_sql absent, decline instruction present")

    n2, i2, _ = await probe([], "DEFAULT: full layer, relationship ops included")
    assert "query_graph" not in n2, "query_graph should be merged into build_audience"
    assert "build_audience" in n2
    assert "run_sql" not in n2
    assert "composition rule" in i2.lower()
    print("PASS: relationship ops merged into build_audience, composition rule present")

    n3, i3, _ = await probe(["--baseline"], "BASELINE: --baseline")
    assert sorted(n3) == ["naive_search", "run_sql"], f"baseline tools wrong: {n3}"
    print("PASS: baseline exposes exactly run_sql and naive_search")

    await call_check()
    print("\n\nMCP SERVER PROBE: ALL CHECKS PASSED")


asyncio.run(main())
