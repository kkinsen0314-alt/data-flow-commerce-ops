import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from commerce_ops.mcp_server import (
    analyze_short_video_data,
    drilldown_commerce_metric,
    inspect_commerce_data,
)
from test_service import all_references


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data" / "fixtures"
EXPECTED_TOOLS = {
    "inspect_commerce_data",
    "analyze_short_video_data",
    "analyze_live_commerce_data",
    "analyze_attribution_and_leads",
    "drilldown_commerce_metric",
}


def mcp_environment() -> dict[str, str]:
    return {
        "COMMERCE_OPS_DATA_ROOT": str(DATA_ROOT),
    }


def serialized_references() -> list[dict]:
    return [item.model_dump(mode="json") for item in all_references()]


class McpHandlerTests(unittest.TestCase):
    def test_direct_handlers_complete_read_only_synthetic_chain(self):
        with patch.dict(os.environ, mcp_environment()):
            inspection = inspect_commerce_data(
                workflow_run_id="wf_mcp_direct",
                caller_role="content_growth_analyst",
                data_refs=all_references(),
                requested_domains=[
                    "content_growth",
                    "live_conversion",
                    "attribution_leads",
                ],
            )
            analysis = analyze_short_video_data(
                workflow_run_id="wf_mcp_direct",
                dataset_ids=["ds_video", "ds_lead"],
                requested_dimensions=["content"],
            )
            packet = analysis["analysis_packet"]
            drilldown = drilldown_commerce_metric(
                workflow_run_id="wf_mcp_direct",
                caller_role="content_growth_analyst",
                base_analysis_run_id=packet["analysis_run_id"],
                evidence_id=packet["evidence"][0]["evidence_id"],
                dimension="content",
                top_n=3,
            )

        self.assertEqual(inspection["terminal_status"], "completed")
        self.assertEqual(analysis["terminal_status"], "completed")
        self.assertEqual(drilldown["terminal_status"], "completed")
        self.assertEqual(len(drilldown["rows"]), 3)

    def test_path_outside_mcp_data_root_is_blocked(self):
        with patch.dict(os.environ, mcp_environment()):
            result = inspect_commerce_data(
                workflow_run_id="wf_mcp_path",
                caller_role="content_growth_analyst",
                data_refs=[
                    {
                        "dataset_id": "ds_outside",
                        "dataset_type": "short_video",
                        "file_path": "../README.md",
                        "synthetic": True,
                    }
                ],
                requested_domains=["content_growth"],
            )

        self.assertEqual(result["terminal_status"], "blocked")
        self.assertEqual(result["workflow_error"]["code"], "INVALID_INPUT")


class McpStdioIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_official_client_discovers_and_calls_stdio_server(self):
        server = StdioServerParameters(
            command=sys.executable,
            args=["-B", "-m", "commerce_ops.mcp_server"],
            cwd=PROJECT_ROOT,
            env=mcp_environment(),
        )

        async with stdio_client(server) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                listed = await session.list_tools()
                tools = {tool.name: tool for tool in listed.tools}
                self.assertEqual(set(tools), EXPECTED_TOOLS)
                self.assertTrue(
                    all(tool.annotations.readOnlyHint for tool in tools.values())
                )
                self.assertTrue(
                    all(tool.annotations.idempotentHint for tool in tools.values())
                )

                inspection = await session.call_tool(
                    "inspect_commerce_data",
                    {
                        "workflow_run_id": "wf_mcp_stdio",
                        "caller_role": "content_growth_analyst",
                        "data_refs": serialized_references(),
                        "requested_domains": [
                            "content_growth",
                            "live_conversion",
                            "attribution_leads",
                        ],
                    },
                )
                self.assertFalse(inspection.isError)
                self.assertEqual(
                    inspection.structuredContent["terminal_status"],
                    "completed",
                )

                analysis = await session.call_tool(
                    "analyze_short_video_data",
                    {
                        "workflow_run_id": "wf_mcp_stdio",
                        "dataset_ids": ["ds_video", "ds_lead"],
                        "requested_dimensions": ["content"],
                        "top_n": 5,
                        "synthetic": True,
                    },
                )
                self.assertFalse(analysis.isError)
                body = analysis.structuredContent
                self.assertEqual(body["terminal_status"], "completed")
                packet = body["analysis_packet"]

                drilldown = await session.call_tool(
                    "drilldown_commerce_metric",
                    {
                        "workflow_run_id": "wf_mcp_stdio",
                        "caller_role": "content_growth_analyst",
                        "base_analysis_run_id": packet["analysis_run_id"],
                        "evidence_id": packet["evidence"][0]["evidence_id"],
                        "dimension": "content",
                        "top_n": 3,
                        "synthetic": True,
                    },
                )
                self.assertFalse(drilldown.isError)
                self.assertEqual(
                    drilldown.structuredContent["terminal_status"],
                    "completed",
                )
                self.assertEqual(len(drilldown.structuredContent["rows"]), 3)


if __name__ == "__main__":
    unittest.main()
