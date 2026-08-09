"""Verify over the real MCP protocol that get_metric accepts a cohort HANDLE.

This is the gap that let a bug through: the in-process tools accepted the string
fine, but FastMCP derives the tool's JSON schema from the Python annotation, so
the protocol layer rejected it before reaching the code. Only a real client call
catches that.
"""
import asyncio
import json
import os

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, ".venv", "bin", "python")


async def main():
    params = StdioServerParameters(
        command=PY, args=[os.path.join(ROOT, "mcp_server.py")],
        cwd=ROOT, env={**os.environ})
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()

            tools = await session.list_tools()
            gm = next(t for t in tools.tools if t.name == "get_metric")
            schema = gm.input_schema["properties"].get("cohort")
            print("get_metric cohort schema:")
            print(" ", json.dumps(schema))
            blob = json.dumps(schema)
            assert "string" in blob, "schema does not admit a string handle"
            print("PASS: the schema admits a string handle\n")

            res = await session.call_tool(
                "build_audience", {"operation": "exposed_cohort",
                                "params": {"edge_type": "referred_by",
                                           "condition": "referrer_churned"}})
            g = json.loads(res.content[0].text)
            print("relationship handles:",
                  {k: v["size"] for k, v in g["cohort_handles"].items()})

            out = {}
            for handle in ("exposed", "comparison"):
                res = await session.call_tool(
                    "get_metric", {"metric_id": "repeat_purchase_rate",
                                   "period": "last_month", "cohort": handle})
                p = json.loads(res.content[0].text)
                assert "error" not in p, f"{handle}: {p.get('error')}"
                row = p["results"][0]
                out[handle] = (row["value"], row["sample_size"])
                print(f"  cohort={handle!r} -> {row['value']:.4f} "
                      f"(n={row['sample_size']})")

            delta = (out["comparison"][0] - out["exposed"][0]) * 100
            print(f"\ndelta = {delta:.1f} points")
            assert 6 <= delta <= 22, f"planted delta not found: {delta}"
            assert out["comparison"][1] > 3000, "comparison cohort is too small"
            print("PASS: composition over the MCP protocol finds the planted delta")

            bad = await session.call_tool(
                "get_metric", {"metric_id": "repeat_purchase_rate",
                               "cohort": "nonexistent"})
            e = json.loads(bad.content[0].text)
            assert "error" in e and "exposed" in e["error"]
            print("PASS: an unknown handle is rejected with the known handles listed")


asyncio.run(main())
print("\nCOHORT HANDLE PROTOCOL PROBE: ALL CHECKS PASSED")
