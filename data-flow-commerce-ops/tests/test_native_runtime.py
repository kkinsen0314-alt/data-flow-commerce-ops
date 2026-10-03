import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from commerce_ops.miniclaw_client import MiniClawClientError
from commerce_ops.native_models import NativeRunRequest
from commerce_ops.native_runtime import (
    NativeAuditReader,
    NativeInputError,
    NativeRunConflict,
    NativeRunStore,
    NativeRuntime,
)


WORKSPACE_JID = "web:native-workspace"
PROFILE_NAME = "电商运营多 Agent 工作流总控"


class FakeMiniClawClient:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(
            base_url="http://127.0.0.1:3017",
            credentials_configured=True,
        )
        self.create_calls = 0
        self.send_calls = 0
        self.get_sessions_calls = 0
        self.get_messages_calls = 0
        self.send_error: MiniClawClientError | None = None
        self.platform_status = "running"
        self.messages: list[dict] = []

    async def aclose(self) -> None:
        pass

    async def get_groups(self):
        return {
            "groups": {
                WORKSPACE_JID: {
                    "execution_mode": "host",
                    "custom_cwd": self.project_root,
                    "agent_profile_id": "profile-1",
                    "agent_profile_name": PROFILE_NAME,
                }
            }
        }

    async def get_agent_profiles(self):
        return {
            "profiles": [
                {
                    "id": "profile-1",
                    "agents_prompt": (
                        "必须完全省略 isolation 参数；不得再次调用 Agent；"
                        "最终尝试账本必须合并；strategy_input JSON"
                    ),
                    "tools_prompt": "使用 project017 兼容桥",
                }
            ]
        }

    async def get_sessions(self, workspace_jid: str):
        self.get_sessions_calls += 1
        sessions = []
        if self.create_calls:
            sessions.append(
                {
                    "id": "session-1",
                    "name": "native",
                    "status": self.platform_status,
                }
            )
        return {"sessions": sessions}

    async def get_messages(self, workspace_jid: str, session_id: str, *, limit=200):
        self.get_messages_calls += 1
        return {"messages": self.messages}

    async def create_session(self, workspace_jid: str, *, name: str, description: str):
        self.create_calls += 1
        return {"session": {"id": "session-1", "name": name}}

    async def send_message_once(self, workspace_jid: str, session_id: str, content: str):
        self.send_calls += 1
        if self.send_error:
            raise self.send_error
        self.last_prompt = content
        return {
            "success": True,
            "messageId": "message-1",
            "disposition": "started",
            "runId": "platform-run-1",
        }


class NativeRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project_root = self.root / "project017"
        self.data_root = self.project_root / "data" / "fixtures"
        self.data_root.mkdir(parents=True)
        self.fixture = self.data_root / "short-video.csv"
        self.fixture.write_text("video_id_hash,impressions\nv_1,100\n", encoding="utf-8")
        self.lead_fixture = self.data_root / "leads.csv"
        self.lead_fixture.write_text("lead_id_hash\nl_1\n", encoding="utf-8")
        self.run_root = self.project_root / "runtime" / "data" / "native-runs"
        self.audit_root = self.project_root / "runtime" / "data" / "native-audit"
        self.client = FakeMiniClawClient()
        self.client.project_root = str(self.project_root.resolve())
        self.runtime = NativeRuntime(
            project_root=self.project_root,
            data_root=self.data_root,
            workspace_jid=WORKSPACE_JID,
            client=self.client,
            store=NativeRunStore(self.run_root),
            audit_reader=NativeAuditReader(self.audit_root),
            final_settle_grace_seconds=0,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def request(self, **updates) -> NativeRunRequest:
        payload = {
            "idempotency_key": "native-request-0001",
            "requested_domains": ["content_growth"],
            "datasets": [
                {
                    "dataset_type": "short_video",
                    "file_path": str(self.fixture),
                }
            ],
            "objective": "分析合成短视频漏斗。",
            "include_strategy": True,
            "authorized_model_execution": True,
        }
        payload.update(updates)
        return NativeRunRequest.model_validate(payload)

    async def test_start_is_durable_and_idempotent(self):
        first = await self.runtime.start(self.request())
        second = await self.runtime.start(self.request())

        self.assertEqual(first.workflow_run_id, second.workflow_run_id)
        self.assertEqual(first.submission_state, "accepted")
        self.assertEqual(first.phase, "submitted")
        self.assertEqual(self.client.create_calls, 1)
        self.assertEqual(self.client.send_calls, 1)
        self.assertIn(first.workflow_run_id, self.client.last_prompt)
        self.assertIn("run_in_background=false", self.client.last_prompt)
        self.assertIn("每个 assistant 回合最多调用一次 Agent", self.client.last_prompt)
        self.assertIn("禁止并行或后台派发", self.client.last_prompt)
        self.assertIn("默认禁止专业 Agent 钻取", self.client.last_prompt)
        self.assertIn("drilldown_metric", self.client.last_prompt)
        self.assertIn("白名单之外", self.client.last_prompt)
        self.assertIn("channel_lead、sales_followup 和 order", self.client.last_prompt)
        self.assertIn("strategy_input JSON", self.client.last_prompt)
        self.assertIn("完整 AnalysisPacket", self.client.last_prompt)
        self.assertIn('"operator_result"', self.client.last_prompt)
        self.assertIn("不得包含 workflow_run_id", self.client.last_prompt)
        self.assertTrue((self.run_root / f"{first.workflow_run_id}.json").is_file())

    async def test_operator_catalog_excludes_internal_runs(self):
        internal = await self.runtime.start(self.request())
        operator = await self.runtime.start(
            self.request(
                idempotency_key="native-request-operator-0002",
                objective="运营页面创建的任务。",
            ),
            operator_visible=True,
        )

        listed = self.runtime.list_operator_runs(limit=20)

        self.assertFalse(internal.operator_visible)
        self.assertTrue(operator.operator_visible)
        self.assertEqual(
            [record.workflow_run_id for record in listed],
            [operator.workflow_run_id],
        )

    async def test_attribution_requires_all_three_dataset_types(self):
        request = self.request(
            requested_domains=["attribution_leads"],
            datasets=[
                {
                    "dataset_type": "channel_lead",
                    "file_path": str(self.lead_fixture),
                }
            ],
        )

        with self.assertRaises(NativeInputError) as raised:
            await self.runtime.start(request)

        self.assertIn("order", str(raised.exception))
        self.assertIn("sales_followup", str(raised.exception))
        self.assertEqual(self.client.create_calls, 0)
        self.assertEqual(self.client.send_calls, 0)

    async def test_reusing_key_for_different_request_is_rejected(self):
        await self.runtime.start(self.request())
        with self.assertRaises(NativeRunConflict):
            await self.runtime.start(self.request(objective="不同分析目标"))
        self.assertEqual(self.client.send_calls, 1)

    async def test_uncertain_submission_is_persisted_and_never_retried(self):
        self.client.send_error = MiniClawClientError(
            "MINICLAW_TRANSPORT_ERROR",
            "unknown",
            mutation_uncertain=True,
        )
        first = await self.runtime.start(self.request())
        second = await self.runtime.start(self.request())

        self.assertEqual(first.terminal_status, "uncertain")
        self.assertEqual(first.submission_state, "uncertain")
        self.assertEqual(second.workflow_run_id, first.workflow_run_id)
        self.assertEqual(self.client.send_calls, 1)

    async def test_refresh_requires_merged_observed_ledger_for_completed(self):
        started = await self.runtime.start(self.request(include_strategy=False))
        self.client.platform_status = "idle"
        self.client.messages = [
            {
                "id": "reply-1",
                "is_from_me": True,
                "sender": "assistant",
                "source_kind": "sdk_final",
                "timestamp": "2026-09-03T00:00:06Z",
                "content": (
                    "结果已生成。password: super-secret\n"
                    "PROJECT017_NATIVE_RESULT_JSON\n```json\n"
                    + json.dumps(
                        {
                            "schema_version": "1.0",
                            "result_type": "project017_native_agent_result",
                            "workflow_run_id": started.workflow_run_id,
                            "terminal_status": "completed",
                            "reported_parent_agent_attempts": 1,
                            "reported_specialist_tool_attempts": 2,
                            "reported_total_attempts": 3,
                            "service_run_ids": ["srv_inspect_1", "srv_video_1"],
                            "analysis_run_ids": ["analysis_video_1"],
                            "unresolved_items": ["cookie=private-cookie"],
                        },
                        ensure_ascii=False,
                    )
                    + "\n```"
                ),
            }
        ]
        missing_audit_result = self.runtime._reconcile_observation(
            started,
            {
                "sessions": [
                    {
                        "id": started.session_id,
                        "status": "idle",
                    }
                ]
            },
            {"messages": self.client.messages},
        )
        self.assertEqual(missing_audit_result.terminal_status, "partial")
        self.assertIsNone(missing_audit_result.authoritative_result)
        self.assertIn(
            "runtime_audit_missing",
            missing_audit_result.reconciliation.warnings,
        )
        self._write_audit(started.workflow_run_id, include_proposals=True)

        result = await self.runtime.refresh(started.workflow_run_id)

        self.assertEqual(result.terminal_status, "completed")
        self.assertEqual(result.ledger.parent_agent_attempts, 1)
        self.assertEqual(result.ledger.specialist_tool_attempts, 2)
        self.assertEqual(result.ledger.total_attempts, 3)
        self.assertEqual(result.proposal_summary.total_proposals, 4)
        self.assertEqual(result.proposal_summary.admitted_proposals, 3)
        self.assertEqual(result.proposal_summary.coalesced_proposals, 1)
        self.assertEqual(result.proposal_summary.rejected_proposals, 0)
        self.assertEqual(len(result.provider_proposals), 4)
        self.assertEqual(
            result.provider_proposals[-1].canonical_tool_call_id,
            "video-1",
        )
        self.assertTrue(result.reconciliation.merged_ledger_accurate)
        self.assertTrue(result.reconciliation.service_run_ids_match)
        self.assertTrue(result.reconciliation.analysis_run_ids_match)
        self.assertEqual(result.reconciliation.warnings, [])
        self.assertEqual(result.observed_execution_state, "settled")
        self.assertEqual(
            result.authoritative_result.service_run_ids,
            ["srv_inspect_1", "srv_video_1"],
        )
        self.assertEqual(
            result.authoritative_result.analysis_run_ids,
            ["analysis_video_1"],
        )
        self.assertNotIn("super-secret", result.final_response)
        self.assertIn("password: [REDACTED]", result.final_response)
        self.assertNotIn("private-cookie", result.unresolved_items[0])
        self.assertEqual(result.unresolved_items[0], "cookie=[REDACTED]")

        lifecycle_result = self.runtime._reconcile_observation(
            started,
            {
                "sessions": [
                    {
                        "id": started.session_id,
                        "status": "running",
                    }
                ]
            },
            {"messages": self.client.messages},
        )
        self.assertEqual(lifecycle_result.terminal_status, "completed")
        self.assertEqual(lifecycle_result.observed_execution_state, "settled")
        self.assertNotIn(
            "final_reply_recorded_before_platform_settled",
            lifecycle_result.reconciliation.warnings,
        )
        stale_settled_result = lifecycle_result.model_copy(
            update={"terminal_status": "completed"}
        )
        self.runtime.store.save(stale_settled_result)
        attempts_before_refresh = stale_settled_result.attempts
        ledger_before_refresh = stale_settled_result.ledger
        sessions_reads_before_refresh = self.client.get_sessions_calls
        messages_reads_before_refresh = self.client.get_messages_calls
        self.client.platform_status = "idle"

        settled_result = await self.runtime.refresh(started.workflow_run_id)

        self.assertEqual(settled_result.terminal_status, "completed")
        self.assertEqual(settled_result.platform_status, "idle")
        self.assertNotIn(
            "final_reply_recorded_before_platform_settled",
            settled_result.reconciliation.warnings,
        )
        self.assertNotIn(
            "final_reply_recorded_before_platform_settled",
            settled_result.unresolved_items,
        )
        self.assertEqual(settled_result.attempts, attempts_before_refresh)
        self.assertEqual(settled_result.ledger, ledger_before_refresh)
        self.assertEqual(
            self.client.get_sessions_calls,
            sessions_reads_before_refresh + 1,
        )
        self.assertEqual(
            self.client.get_messages_calls,
            messages_reads_before_refresh + 1,
        )
        self.assertEqual(self.client.create_calls, 1)
        self.assertEqual(self.client.send_calls, 1)

        sessions_reads_after_settle = self.client.get_sessions_calls
        messages_reads_after_settle = self.client.get_messages_calls
        cached_result = await self.runtime.refresh(started.workflow_run_id)

        self.assertEqual(cached_result.platform_status, "idle")
        self.assertEqual(self.client.get_sessions_calls, sessions_reads_after_settle)
        self.assertEqual(self.client.get_messages_calls, messages_reads_after_settle)

    async def test_refresh_downgrades_duplicate_analysis_cardinality(self):
        started = await self.runtime.start(self.request(include_strategy=False))
        self.client.platform_status = "idle"
        self.client.messages = [
            {
                "id": "reply-duplicate",
                "is_from_me": True,
                "sender": "assistant",
                "source_kind": "sdk_final",
                "timestamp": "2026-09-03T00:00:07Z",
                "content": (
                    "PROJECT017_NATIVE_RESULT_JSON\n```json\n"
                    + json.dumps(
                        {
                            "schema_version": "1.0",
                            "result_type": "project017_native_agent_result",
                            "workflow_run_id": started.workflow_run_id,
                            "terminal_status": "completed",
                            "reported_parent_agent_attempts": 1,
                            "reported_specialist_tool_attempts": 3,
                            "reported_total_attempts": 4,
                            "service_run_ids": [
                                "srv_inspect_1",
                                "srv_video_1",
                                "srv_video_2",
                            ],
                            "analysis_run_ids": [
                                "analysis_video_1",
                                "analysis_video_2",
                            ],
                            "unresolved_items": [],
                        }
                    )
                    + "\n```"
                ),
            }
        ]
        self._write_audit(started.workflow_run_id, duplicate_analysis=True)

        result = await self.runtime.refresh(started.workflow_run_id)

        self.assertEqual(result.terminal_status, "partial")
        self.assertIn(
            "specialist_tool_cardinality_mismatch",
            result.reconciliation.warnings,
        )
        self.assertEqual(result.ledger.total_attempts, 4)

    async def test_audit_ids_remain_authoritative_when_model_report_disagrees(self):
        started = await self.runtime.start(self.request(include_strategy=False))
        self.client.platform_status = "running"
        self.client.messages = [
            {
                "id": "reply-id-mismatch",
                "is_from_me": True,
                "sender": "assistant",
                "source_kind": "sdk_final",
                "timestamp": "2026-09-03T00:00:08Z",
                "content": (
                    "PROJECT017_NATIVE_RESULT_JSON\n```json\n"
                    + json.dumps(
                        {
                            "schema_version": "1.0",
                            "result_type": "project017_native_agent_result",
                            "workflow_run_id": started.workflow_run_id,
                            "terminal_status": "completed",
                            "reported_parent_agent_attempts": 1,
                            "reported_specialist_tool_attempts": 2,
                            "reported_total_attempts": 3,
                            "service_run_ids": ["srv_invented"],
                            "analysis_run_ids": ["analysis_video_1"],
                            "unresolved_items": [],
                        }
                    )
                    + "\n```"
                ),
            }
        ]
        self._write_audit(started.workflow_run_id)

        result = await self.runtime.refresh(started.workflow_run_id)

        self.assertEqual(result.terminal_status, "completed")
        self.assertEqual(result.platform_status, "running")
        self.assertEqual(result.observed_execution_state, "settled")
        self.assertFalse(result.reconciliation.service_run_ids_match)
        self.assertIn(
            "service_run_id_ledger_mismatch",
            result.reconciliation.warnings,
        )
        self.assertEqual(
            result.reconciliation.reported_service_run_ids,
            ["srv_invented"],
        )
        self.assertEqual(
            result.authoritative_result.service_run_ids,
            ["srv_inspect_1", "srv_video_1"],
        )
        self.assertEqual(result.authoritative_result.total_attempts, 3)

    async def test_strategy_reference_failure_is_blocking_and_public(self):
        started = await self.runtime.start(self.request(include_strategy=True))
        self.client.platform_status = "idle"
        self.client.messages = [
            {
                "id": "reply-strategy-reference-failure",
                "is_from_me": True,
                "sender": "assistant",
                "source_kind": "sdk_final",
                "timestamp": "2026-09-06T00:00:08Z",
                "content": (
                    "PROJECT017_NATIVE_RESULT_JSON\n```json\n"
                    + json.dumps(
                        {
                            "schema_version": "1.0",
                            "result_type": "project017_native_agent_result",
                            "workflow_run_id": started.workflow_run_id,
                            "terminal_status": "completed",
                            "reported_parent_agent_attempts": 2,
                            "reported_specialist_tool_attempts": 2,
                            "reported_total_attempts": 4,
                            "service_run_ids": ["srv_inspect_1", "srv_video_1"],
                            "analysis_run_ids": ["analysis_video_1"],
                            "unresolved_items": [],
                        }
                    )
                    + "\n```"
                ),
            }
        ]
        self._write_audit(started.workflow_run_id)
        self._append_strategy_attempt(
            started.workflow_run_id,
            validation="failed",
            status="failed",
        )

        result = await self.runtime.refresh(started.workflow_run_id)

        self.assertEqual(result.terminal_status, "partial")
        self.assertFalse(
            result.reconciliation.strategy_cross_packet_references_valid
        )
        self.assertIn(
            "strategy_cross_packet_reference_validation_failed",
            result.reconciliation.warnings,
        )
        self.assertEqual(result.ledger.failed_or_blocked_attempts, 1)
        strategy_attempt = next(
            item
            for item in result.attempts
            if item.subagent_type == "commerce-review-strategist"
        )
        self.assertEqual(strategy_attempt.strategy_reference_validation, "failed")
        self.assertEqual(
            strategy_attempt.strategy_reference_error_codes,
            ["strategy_finding_id_not_in_catalog"],
        )

    async def test_strategy_failure_projects_without_specialist_catalog(self):
        started = await self.runtime.start(self.request(include_strategy=True))
        self.client.platform_status = "idle"
        self.client.messages = [{
            "id": "reply-strategy-only-failure",
            "is_from_me": True,
            "sender": "assistant",
            "source_kind": "sdk_final",
            "timestamp": "2026-09-06T00:00:08Z",
            "content": "PROJECT017_NATIVE_RESULT_JSON\n```json\n" + json.dumps({
                "schema_version": "1.0",
                "result_type": "project017_native_agent_result",
                "workflow_run_id": started.workflow_run_id,
                "terminal_status": "completed",
                "reported_parent_agent_attempts": 1,
                "reported_specialist_tool_attempts": 0,
                "reported_total_attempts": 1,
                "service_run_ids": [],
                "analysis_run_ids": [],
                "unresolved_items": [],
            }) + "\n```",
        }]
        self.audit_root.mkdir(parents=True, exist_ok=True)
        self._append_strategy_attempt(
            started.workflow_run_id,
            validation="failed",
            status="failed",
        )

        result = await self.runtime.refresh(started.workflow_run_id)

        self.assertFalse(result.reconciliation.strategy_cross_packet_references_valid)
        self.assertIn(
            "strategy_cross_packet_reference_validation_failed",
            result.reconciliation.warnings,
        )

    def _write_audit(
        self,
        workflow_run_id: str,
        *,
        duplicate_analysis: bool = False,
        include_proposals: bool = False,
    ) -> None:
        self.audit_root.mkdir(parents=True)
        rows = []
        attempts = [
            ("parent:agent-1", "parent_dispatch", "commerce_ops_supervisor", "Agent", "agent-1", 1, None, None),
            ("child:inspect-1", "specialist_tool", "content_growth_analyst", "commerce_ops_inspect_commerce_data", "inspect-1", 1, "srv_inspect_1", None),
            ("child:video-1", "specialist_tool", "content_growth_analyst", "commerce_ops_analyze_short_video_data", "video-1", 2, "srv_video_1", "analysis_video_1"),
        ]
        if duplicate_analysis:
            attempts.append(
                ("child:video-2", "specialist_tool", "content_growth_analyst", "commerce_ops_analyze_short_video_data", "video-2", 3, "srv_video_2", "analysis_video_2")
            )
        for index, attempt in enumerate(attempts, start=1):
            attempt_id, layer, actor, tool, call_id, number, service_id, analysis_id = attempt
            common = {
                "schema_version": "1.0",
                "attempt_id": attempt_id,
                "workflow_run_id": workflow_run_id,
                "layer": layer,
                "actor": actor,
                "tool_name": tool,
                "tool_call_id": call_id,
                "attempt_number": number,
            }
            if layer == "parent_dispatch":
                common.update(
                    {
                        "subagent_type": "content-growth-analyst",
                        "isolation_argument_present": False,
                        "run_in_background_argument_present": True,
                        "run_in_background_value": False,
                    }
                )
            rows.append(
                {
                    **common,
                    "event_type": "attempt_started",
                    "status": "started",
                    "observed_at": f"2026-09-03T00:00:0{index}Z",
                }
            )
            rows.append(
                {
                    **common,
                    "event_type": "attempt_finished",
                    "status": "completed",
                    "service_run_id": service_id,
                    "analysis_run_id": analysis_id,
                    "observed_at": f"2026-09-03T00:00:0{index + 3}Z",
                }
            )
        if include_proposals:
            proposals = [
                (
                    "parent-proposal:agent-1",
                    "parent_dispatch",
                    "commerce_ops_supervisor",
                    "Agent",
                    "agent-1",
                    1,
                    "content-growth-analyst",
                    "admitted",
                    "agent-1",
                    None,
                ),
                (
                    "child-proposal:inspect-1",
                    "specialist_tool",
                    "content_growth_analyst",
                    "commerce_ops_inspect_commerce_data",
                    "inspect-1",
                    2,
                    None,
                    "admitted",
                    "inspect-1",
                    None,
                ),
                (
                    "child-proposal:video-1",
                    "specialist_tool",
                    "content_growth_analyst",
                    "commerce_ops_analyze_short_video_data",
                    "video-1",
                    3,
                    None,
                    "admitted",
                    "video-1",
                    None,
                ),
                (
                    "child-proposal:video-duplicate",
                    "specialist_tool",
                    "content_growth_analyst",
                    "commerce_ops_analyze_short_video_data",
                    "video-duplicate",
                    4,
                    None,
                    "coalesced",
                    "video-1",
                    "duplicate_phase_provider_proposal_coalesced",
                ),
            ]
            for index, proposal in enumerate(proposals, start=1):
                (
                    proposal_id,
                    layer,
                    actor,
                    tool,
                    call_id,
                    number,
                    subagent_type,
                    disposition,
                    canonical_call_id,
                    reason_code,
                ) = proposal
                common = {
                    "schema_version": "2.0",
                    "proposal_id": proposal_id,
                    "workflow_run_id": workflow_run_id,
                    "layer": layer,
                    "actor": actor,
                    "tool_name": tool,
                    "tool_call_id": call_id,
                    "proposal_number": number,
                    "subagent_type": subagent_type,
                }
                rows.append(
                    {
                        **common,
                        "event_type": "provider_proposal_received",
                        "disposition": "pending",
                        "observed_at": f"2026-09-03T00:01:0{index}Z",
                    }
                )
                rows.append(
                    {
                        **common,
                        "event_type": "provider_proposal_disposition",
                        "disposition": disposition,
                        "canonical_tool_call_id": canonical_call_id,
                        "reason_code": reason_code,
                        "observed_at": f"2026-09-03T00:01:1{index}Z",
                    }
                )
        (self.audit_root / f"{workflow_run_id}.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )

    def _append_strategy_attempt(
        self,
        workflow_run_id: str,
        *,
        validation: str,
        status: str,
    ) -> None:
        common = {
            "schema_version": "1.0",
            "attempt_id": "parent:strategy-1",
            "workflow_run_id": workflow_run_id,
            "layer": "parent_dispatch",
            "actor": "commerce_ops_supervisor",
            "tool_name": "Agent",
            "tool_call_id": "strategy-1",
            "attempt_number": 2,
            "subagent_type": "commerce-review-strategist",
            "isolation_argument_present": False,
            "run_in_background_argument_present": True,
            "run_in_background_value": False,
        }
        rows = [
            {
                **common,
                "event_type": "attempt_started",
                "status": "started",
                "observed_at": "2026-09-06T00:00:04Z",
            },
            {
                **common,
                "event_type": "attempt_finished",
                "status": status,
                "reason_code": (
                    "strategy_cross_packet_reference_validation_failed"
                    if validation == "failed"
                    else None
                ),
                "strategy_reference_validation": validation,
                "strategy_reference_error_codes": [
                    "strategy_finding_id_not_in_catalog"
                ] if validation == "failed" else [],
                "observed_at": "2026-09-06T00:00:05Z",
            },
        ]
        with (self.audit_root / f"{workflow_run_id}.jsonl").open(
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write("".join(json.dumps(row) + "\n" for row in rows))


if __name__ == "__main__":
    unittest.main()
