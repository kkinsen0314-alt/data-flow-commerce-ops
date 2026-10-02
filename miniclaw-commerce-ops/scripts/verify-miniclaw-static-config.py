from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
from typing import Any


PLATFORM_COMMIT = "3ff1c8d6a0707f4a9f0957ff411758e5e141583a"
PLATFORM_ROOT = Path(
    "D:/Workspace/project014-miniclaw-deployment/upstream/miniclaw"
)
EXTENSION_NAME = "commerce-ops-mcp"
EXTENSION_PATH = (
    "D:/Workspace/project017-miniclaw-commerce-ops/"
    ".pi/extensions/commerce-ops-mcp/index.ts"
)
PI_TOOLS = {
    "commerce_ops_inspect_commerce_data",
    "commerce_ops_analyze_short_video_data",
    "commerce_ops_analyze_live_commerce_data",
    "commerce_ops_analyze_attribution_and_leads",
    "commerce_ops_drilldown_commerce_metric",
}
ROLE_TOOL_SCOPES = {
    "content-growth-analyst.md": {
        "commerce_ops_inspect_commerce_data",
        "commerce_ops_analyze_short_video_data",
        "commerce_ops_drilldown_commerce_metric",
    },
    "live-conversion-analyst.md": {
        "commerce_ops_inspect_commerce_data",
        "commerce_ops_analyze_live_commerce_data",
        "commerce_ops_drilldown_commerce_metric",
    },
    "attribution-lead-analyst.md": {
        "commerce_ops_inspect_commerce_data",
        "commerce_ops_analyze_attribution_and_leads",
        "commerce_ops_drilldown_commerce_metric",
    },
}
ROLE_CALLERS = {
    "content-growth-analyst.md": "content_growth_analyst",
    "live-conversion-analyst.md": "live_conversion_analyst",
    "attribution-lead-analyst.md": "attribution_lead_analyst",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{path} 缺少 YAML frontmatter")
    try:
        end = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        )
    except StopIteration as exc:
        raise ValueError(f"{path} frontmatter 未闭合") from exc
    values: dict[str, Any] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        key, separator, raw_value = line.partition(":")
        if not separator:
            raise ValueError(f"{path} frontmatter 行无法解析：{line}")
        value = raw_value.strip()
        if value.startswith(("\"", "[")):
            values[key.strip()] = json.loads(value)
        elif value in {"true", "false"}:
            values[key.strip()] = value == "true"
        elif value.isdigit():
            values[key.strip()] = int(value)
        else:
            values[key.strip()] = value
    return values, "\n".join(lines[end + 1 :]).strip()


def split_tool_scope(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def git_output(*args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(PLATFORM_ROOT), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def validate(project_root: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(check_id: str, condition: bool, detail: str) -> None:
        checks.append(
            {
                "check_id": check_id,
                "status": "pass" if condition else "fail",
                "detail": detail,
            }
        )

    expected_files = [
        ".pi/agents/attribution-lead-analyst.md",
        ".pi/agents/commerce-review-strategist.md",
        ".pi/agents/content-growth-analyst.md",
        ".pi/agents/live-conversion-analyst.md",
        ".pi/extensions/commerce-ops-mcp/index.ts",
        ".pi/extensions/commerce-ops-mcp/package-lock.json",
        ".pi/extensions/commerce-ops-mcp/package.json",
        ".pi/extensions/commerce-ops-mcp/validate-pi-resource-loader.mjs",
        ".pi/extensions/commerce-ops-mcp/validate-runtime.mjs",
        ".pi/extensions/commerce-ops-mcp/validation-shared.mjs",
        ".pi/extensions/miniclaw-subagents-bridge/index.ts",
        ".pi/subagents.json",
        "config/agent-profile-create.template.json",
        "config/workspace-create.template.json",
        "docs/AGENT-SPEC-v2.md",
        "docs/EVIDENCE-BOUNDARY.md",
        "docs/MINICLAW-INTEGRATION-v2.md",
        "docs/RUNTIME-OBSERVABILITY-v1.md",
        "docs/TOOL-CONTRACTS-v1.md",
        "integrations/miniclaw-plugin-marketplace/.claude-plugin/marketplace.json",
        "integrations/miniclaw-plugin-marketplace/plugins/commerce-ops/.claude-plugin/plugin.json",
        "integrations/miniclaw-plugin-marketplace/plugins/commerce-ops/.mcp.json",
        "artifacts/runtime/smoke-content-v2-dispatch-guard-redacted-trace.json",
        "artifacts/runtime/smoke-content-v2-dispatch-guard-assessment.json",
        "runtime/setup-helper/index.html",
        "runtime/setup-helper/serve.mjs",
        "runtime/setup-helper/smoke-content.html",
        "runtime/setup-helper/smoke.html",
        "scripts/start-native-runtime.ps1",
        "scripts/verify-miniclaw-subagent-bridge.mjs",
        "scripts/verify-provider-request-chain.mjs",
        "artifacts/provider-request-chain-validation-v1.json",
        "artifacts/runtime/native-full-v4-root-cause-diagnosis-v1.json",
        "artifacts/runtime/native-profile-sync-assessment.json",
        "artifacts/runtime/native-full-v2-redacted-trace.json",
        "artifacts/runtime/native-full-v2-assessment.json",
        "artifacts/runtime/native-full-v3-redacted-trace.json",
        "artifacts/runtime/native-full-v3-assessment.json",
        "artifacts/miniclaw-subagent-bridge-validation-v11.json",
        "artifacts/miniclaw-subagent-bridge-validation-v12.json",
        "artifacts/pi-extension-runtime-v5.json",
        "artifacts/pi-extension-runtime-v6.json",
        "artifacts/pi-default-resource-loader-v4.json",
    ]
    for relative in expected_files:
        check(
            f"file:{relative}",
            (project_root / relative).is_file(),
            "required phase-4 static asset exists",
        )

    profile = load_json(project_root / "config/agent-profile-create.template.json")
    check(
        "profile:schema-v2",
        profile.get("prompt_schema_version") == 2,
        "four-part prompt schema is explicit",
    )
    check(
        "profile:append-mode",
        profile.get("prompt_mode") == "append",
        "MiniClaw preset remains enabled",
    )
    check(
        "profile:preset-compatible",
        profile.get("include_claude_preset") is True,
        "append mode and preset flag are compatible",
    )
    check(
        "profile:provider-placeholder",
        profile.get("model_config_id") is None,
        "authored template does not embed the isolated runtime Provider ID",
    )
    check(
        "profile:four-prompts",
        all(
            profile.get(key)
            for key in (
                "identity_prompt",
                "soul_prompt",
                "agents_prompt",
                "tools_prompt",
            )
        ),
        "all four prompt sections are non-empty",
    )
    runtime_policy = profile.get("runtime_policy", {})
    check(
        "profile:managed-context",
        runtime_policy.get("context", {}).get("source") == "managed",
        "host Claude context is not inherited",
    )
    check(
        "profile:skills-disabled",
        runtime_policy.get("skills", {}).get("mode") == "disabled"
        and runtime_policy.get("skills", {}).get("ids") == []
        and runtime_policy.get("skills", {}).get("host", {}).get("mode")
        == "disabled"
        and runtime_policy.get("skills", {}).get("host", {}).get("ids") == [],
        "Profile does not import user or host skills",
    )
    check(
        "profile:mcp-disabled",
        runtime_policy.get("mcp", {}).get("mode") == "disabled"
        and runtime_policy.get("mcp", {}).get("ids") == [],
        "Plugin MCP is not selected as a Supervisor capability",
    )
    agents_prompt = profile.get("agents_prompt", "")
    tools_prompt = profile.get("tools_prompt", "")
    check(
        "profile:supervisor-dispatch-only",
        all(
            token in tools_prompt
            for token in (
                "Agent",
                "get_subagent_result",
                "steer_subagent",
                "不直接调用 commerce_ops",
            )
        ),
        "Supervisor prompt limits work to subagent dispatch and forbids direct business tools",
    )
    check(
        "profile:tool-attempt-audit",
        all(
            token in agents_prompt + tools_prompt
            for token in (
                "所有工具尝试",
                "Schema 参数校验失败",
                "全部 service_run_id",
                "不得报告 completed/pass",
                "成功调用数不能冒充总尝试数",
            )
        ),
        "Supervisor audits failed attempts, total attempts, and every available service run ID",
    )
    check(
        "profile:non-git-isolation-policy",
        all(
            token in agents_prompt
            for token in (
                "本项目不是 Git 仓库",
                "必须完全省略 isolation 参数",
                '禁止传 isolation="worktree"',
            )
        ),
        "Supervisor must omit worktree isolation for the non-Git project017 workspace",
    )
    check(
        "profile:parent-dispatch-fail-closed",
        all(
            token in agents_prompt + tools_prompt
            for token in (
                "父级 Agent 工具尝试",
                "当前分支立即 blocked",
                "不得再次调用 Agent",
                "父级 Agent 派发尝试与子级业务工具尝试",
            )
        ),
        "a parent dispatch failure blocks the branch and the final ledger merges parent and child attempts",
    )
    check(
        "profile:provider-proposal-admission",
        all(
            token in agents_prompt + tools_prompt
            for token in (
                "按原顺序串行处理",
                "coalesced",
                "不产生第二次父级 Agent 工具尝试",
                "executionMode=sequential",
                "Provider 提议",
            )
        ),
        "the authored Profile separates provider proposals from admitted attempts and documents deterministic coalescing",
    )
    check(
        "profile:domain-data-ref-allocation",
        all(
            token in agents_prompt
            for token in (
                "内容角色至少接收全部 short_video",
                "直播角色至少接收全部 live_session",
                "渠道归因角色必须在唯一一次 inspect 中同时接收全部 channel_lead、sales_followup 和 order",
            )
        ),
        "Supervisor must pass every domain-required dataset to the specialist's single inspect attempt",
    )
    check(
        "profile:strategy-reference-envelope",
        all(
            token in agents_prompt
            for token in (
                "strategy_input JSON",
                "完整 AnalysisPacket",
                "analysis_run_id、dataset_ids、evidence、findings",
                "finding→evidence 引用",
                "禁止只传指标摘要或自然语言结论",
                "缺失完整 ID 目录时不得生成行动",
            )
        ),
        "Supervisor must pass complete machine-readable analysis packets into the strategy task",
    )

    workspace = load_json(project_root / "config/workspace-create.template.json")
    check(
        "workspace:host",
        workspace.get("execution_mode") == "host",
        "Windows project path uses host execution",
    )
    check(
        "workspace:assistant",
        workspace.get("interaction_mode") == "assistant",
        "Workspace remains manually initiated",
    )
    check(
        "workspace:cwd",
        workspace.get("custom_cwd") == str(project_root),
        "custom cwd points to project017",
    )
    check(
        "workspace:profile-placeholder",
        workspace.get("agent_profile_id")
        == "REPLACE_WITH_CREATED_AGENT_PROFILE_ID",
        "database ID is not fabricated",
    )

    subagents = load_json(project_root / ".pi/subagents.json")
    check(
        "subagents:strict-files",
        subagents.get("strictAgentFiles") is True,
        "broken custom agent files fail startup",
    )
    check(
        "subagents:no-fallback",
        subagents.get("fallbackSubagent") == "none",
        "unknown roles fail closed",
    )
    check(
        "subagents:no-defaults",
        subagents.get("disableDefaultAgents") is True,
        "default full-tool roles are disabled",
    )
    check(
        "subagents:no-nesting",
        subagents.get("maxSubagentDepth") == 1,
        "specialists cannot create nested children",
    )
    check(
        "subagents:no-scheduling",
        subagents.get("schedulingEnabled") is False,
        "scheduled subagent runs remain disabled",
    )
    check(
        "subagents:foreground",
        subagents.get("widgetMode") == "background",
        "widget preference does not authorize background execution",
    )

    for filename, allowed_tools in ROLE_TOOL_SCOPES.items():
        meta, body = parse_frontmatter(project_root / ".pi/agents" / filename)
        actual_tools = split_tool_scope(str(meta.get("tools", "")))
        expected_tools = {"none"} | {
            f"ext:{EXTENSION_NAME}/{name}" for name in allowed_tools
        }
        denied_tools = split_tool_scope(str(meta.get("disallowed_tools", "")))
        other_domain_tools = PI_TOOLS - allowed_tools
        role_id = filename.removesuffix(".md")
        check(
            f"agent:{role_id}:tool-scope",
            actual_tools == expected_tools,
            "only the role-local inspect, domain analysis, and drilldown tools are exposed",
        )
        check(
            f"agent:{role_id}:extension-path",
            meta.get("extensions") == [EXTENSION_PATH],
            "role loads the project017 extension by explicit path",
        )
        check(
            f"agent:{role_id}:deny-scope",
            {"bash", "powershell", "write", "edit"}.issubset(denied_tools)
            and other_domain_tools.issubset(denied_tools),
            "write tools and other-domain analysis tools are denied",
        )
        check(
            f"agent:{role_id}:no-nesting",
            meta.get("allowed_subagents") == "none",
            "specialist cannot delegate",
        )
        check(
            f"agent:{role_id}:no-context-inheritance",
            meta.get("inherit_context") is False,
            "only the explicit task packet enters the child",
        )
        check(
            f"agent:{role_id}:prompt-replace",
            meta.get("prompt_mode") == "replace",
            "specialist prompt does not inherit the Supervisor system prompt",
        )
        caller = ROLE_CALLERS[filename]
        check(
            f"agent:{role_id}:inspect-first",
            ("先且只调用一次" in body or "先且只允许一次" in body)
            and "commerce_ops_inspect_commerce_data" in body
            and caller in body,
            "role-local MCP state is established before domain analysis",
        )
        check(
            f"agent:{role_id}:inspect-parameter-boundary",
            all(
                token in body
                for token in (
                    "workflow_run_id`、`caller_role`、`data_refs`、`requested_domains",
                    "根对象不得传 `synthetic`",
                    "`synthetic=true` 只能放在每个 `data_refs[]` 项内",
                )
            ),
            "inspect root fields and nested synthetic placement are explicit",
        )
        check(
            f"agent:{role_id}:inspect-validation-stop",
            all(
                token in body
                for token in (
                    "Schema 参数校验失败",
                    "也计为一次 inspect 尝试",
                    "停止当前分支并返回 `blocked`",
                    "不得主动发起第二次 inspect",
                )
            ),
            "a schema validation failure consumes the only inspect attempt and stops the branch",
        )
        check(
            f"agent:{role_id}:attempt-reporting",
            all(
                token in body
                for token in (
                    "所有工具尝试（含失败尝试）",
                    "总尝试次数",
                    "全部 `service_run_id`",
                    "`analysis_run_id`",
                    "transport 自动重试与模型主动重新调用必须分开记录",
                )
            ),
            "specialist output retains failures, counts, transport distinction, and all run IDs",
        )
        check(
            f"agent:{role_id}:failure-boundary",
            all(token in body for token in ("partial", "blocked", "uncertain"))
            and "禁止自动重试" in body,
            "degraded states and no-blind-retry behavior are explicit",
        )
        check(
            f"agent:{role_id}:explicit-drilldown-gate",
            all(
                token in body
                for token in (
                    "默认禁止钻取",
                    "`drilldown_metric`",
                    "`drilldown_dimension`",
                    "才允许调用一次",
                    "不得自行决定钻取",
                    "不得自行决定钻取或发起第二次钻取",
                )
            ),
            "drilldown requires an explicit Supervisor metric-and-dimension gate and is limited to one attempt",
        )
        check(
            f"agent:{role_id}:no-unlisted-builtins",
            all(
                token in body
                for token in (
                    "`Read`",
                    "`execute_command`",
                    "`bash`",
                    "`powershell`",
                    "未列入本角色 `tools` 白名单",
                )
            ),
            "role text explicitly forbids hallucinated built-ins and every tool outside its allowlist",
        )

    review_meta, review_body = parse_frontmatter(
        project_root / ".pi/agents/commerce-review-strategist.md"
    )
    check(
        "agent:review:no-tools",
        review_meta.get("tools") == "none",
        "review role has no built-in or business tools",
    )
    check(
        "agent:review:no-extensions",
        review_meta.get("extensions") is False,
        "review role loads no extension",
    )
    check(
        "agent:review:no-nesting",
        review_meta.get("allowed_subagents") == "none",
        "review role cannot delegate",
    )
    check(
        "agent:review:action-chain",
        all(
            token in review_body
            for token in (
                "`action_id`",
                "`priority`",
                "`finding_ids`",
                "`evidence_ids`",
                "`action`",
                "owner_role",
                "due_window",
                "rationale",
                "verification_metric",
                "verification_method",
                "dataset_ids",
                "guardrails",
                "confidence",
                '字符串 `"1.0"`',
                '字符串 `"decision_packet"`',
                '字符串 `"commerce_review_strategist"`',
                "^decision_[A-Za-z0-9_-]+$",
                "^action_[A-Za-z0-9_-]+$",
                "`due_window` 必须是非空字符串",
                "`increase`、`decrease`、`maintain` 或 `observe`",
                "`blocked_reasons` 必须是字符串数组",
                "不得在 DecisionPacket 根对象增加",
                "`allowed_finding_ids`",
                "`allowed_evidence_ids`",
                "`allowed_dataset_ids`",
                "只能逐字复制这些已存在 ID",
                "真实 finding→evidence 链",
                "所有 action 引用均是输入真实 ID 的子集",
                "`strategy_input` JSON",
                "strategy_reference_catalog_missing",
            )
        ),
        "review role pins exact DecisionPacket literals, types, allowed fields, and nested VerificationMetric contract",
    )

    marketplace = load_json(
        project_root
        / "integrations/miniclaw-plugin-marketplace/.claude-plugin/marketplace.json"
    )
    plugin = load_json(
        project_root
        / "integrations/miniclaw-plugin-marketplace/plugins/commerce-ops/.claude-plugin/plugin.json"
    )
    mcp = load_json(
        project_root
        / "integrations/miniclaw-plugin-marketplace/plugins/commerce-ops/.mcp.json"
    )
    check(
        "plugin:marketplace-name",
        marketplace.get("name") == "project017-commerce-ops",
        "Catalog marketplace is project-scoped",
    )
    check(
        "plugin:single-source",
        marketplace.get("plugins")
        == [
            {
                "name": "commerce-ops",
                "source": "./plugins/commerce-ops",
                "description": "数据检查、短视频、直播、渠道线索和受限钻取 MCP 声明。",
            }
        ],
        "marketplace declares one local Plugin source",
    )
    check(
        "plugin:manifest-name",
        plugin.get("name") == "commerce-ops",
        "Plugin directory and manifest names match",
    )
    server = mcp.get("commerce_ops", {})
    check(
        "plugin:mcp-command",
        server.get("command") == "python"
        and server.get("args") == ["-B", "-m", "commerce_ops.mcp_server"],
        "Plugin declares the project017 stdio MCP Server",
    )
    check(
        "plugin:mcp-cwd",
        server.get("cwd") == str(project_root),
        "stdio cwd points to project017",
    )
    check(
        "plugin:data-root",
        server.get("env", {}).get("COMMERCE_OPS_DATA_ROOT")
        == str(project_root / "data/fixtures"),
        "MCP input is limited to project017 synthetic fixtures",
    )

    package = load_json(project_root / ".pi/extensions/commerce-ops-mcp/package.json")
    package_lock = load_json(
        project_root / ".pi/extensions/commerce-ops-mcp/package-lock.json"
    )
    lock_packages = package_lock.get("packages", {})
    check(
        "extension:pi-host-pin",
        package.get("dependencies", {}).get("@earendil-works/pi-coding-agent")
        == "0.84.2"
        and lock_packages.get(
            "node_modules/@earendil-works/pi-coding-agent", {}
        ).get("version")
        == "0.84.2",
        "Pi host package is declared and locked to 0.84.2",
    )
    check(
        "extension:sdk-pin",
        package.get("dependencies", {}).get("@modelcontextprotocol/sdk")
        == "1.30.0"
        and lock_packages.get("node_modules/@modelcontextprotocol/sdk", {}).get(
            "version"
        )
        == "1.30.0",
        "MCP SDK is declared and locked to 1.30.0",
    )
    check(
        "extension:typebox-pin",
        package.get("dependencies", {}).get("typebox") == "1.3.7"
        and lock_packages.get("node_modules/typebox", {}).get("version")
        == "1.3.7",
        "TypeBox is declared and locked to the MiniClaw version",
    )
    extension_source = (
        project_root / ".pi/extensions/commerce-ops-mcp/index.ts"
    ).read_text(encoding="utf-8")
    registered = set(
        re.findall(r'name:\s*"(commerce_ops_[a-z_]+)"', extension_source)
    )
    check(
        "extension:five-tools",
        registered == PI_TOOLS,
        "Pi extension registers exactly the five contracted tools",
    )
    check(
        "extension:stdio-client",
        "StdioClientTransport" in extension_source
        and "Client" in extension_source,
        "official MCP client and stdio transport are used",
    )
    check(
        "extension:role-local-state",
        "let activeClient" in extension_source
        and "let activeTransport" in extension_source,
        "each extension instance owns one MCP client and transport",
    )
    check(
        "extension:synthetic-only",
        extension_source.count("synthetic: true") >= 5,
        "all five Pi-to-MCP mappings force synthetic execution",
    )
    check(
        "extension:no-retry",
        "automaticRetry: false" in extension_source,
        "tool details declare no automatic retry",
    )
    check(
        "extension:inspect-parameter-description",
        all(
            token in extension_source
            for token in (
                "根对象仅允许 workflow_run_id、caller_role、data_refs、requested_domains 和可选 max_rows_for_profile",
                "根对象不得传 synthetic",
                "synthetic=true 只能放在每个 data_refs[] 项内",
                "Schema 参数校验失败也计为一次工具尝试",
                "禁止用第二次调用隐藏失败尝试",
            )
        ),
        "inspect tool description exposes the strict root argument and attempt-count contract",
    )
    check(
        "extension:deterministic-tool-cardinality",
        all(
            token in extension_source
            for token in (
                "workflowToolStates",
                'executionMode: "sequential"',
                "completedPhaseResults",
                "duplicate_phase_provider_proposal_coalesced",
                "provider_proposal_disposition",
                "analysis_dataset_not_registered_by_inspect",
                "required_inspect_dataset_types_missing",
            )
        ),
        "the role-local extension serializes provider proposals, coalesces completed phases, and still blocks invalid dataset registration",
    )
    check(
        "extension:business-terminal-audit",
        all(
            token in extension_source
            for token in (
                "resultTerminalStatus",
                'terminalStatus === "blocked"',
                "mcp_business_terminal_blocked",
                "businessError",
            )
        ),
        "structured business blocked or uncertain results are reflected in child audit status and Pi tool errors",
    )
    check(
        "extension:strategy-reference-catalog-audit",
        all(
            token in extension_source
            for token in (
                "resultReferenceMetadata",
                "dataset_ids",
                "evidence_ids",
                "finding_ids",
                "finding_evidence_links",
            )
        ),
        "completed specialist analysis audits expose a redacted ID catalog for strategy validation",
    )
    check(
        "extension:shutdown",
        'pi.on("session_shutdown"' in extension_source,
        "stdio transport cleanup is registered",
    )
    check(
        "extension:single-tool-provider-policy",
        all(
            token in extension_source
            for token in (
                'pi.on("before_provider_request"',
                "enforceSingleToolTurn",
                "disable_parallel_tool_use: true",
                'type: "auto"',
            )
        ),
        "professional specialist requests use Anthropic at-most-one tool call semantics",
    )

    bridge_source = (
        project_root / ".pi/extensions/miniclaw-subagents-bridge/index.ts"
    ).read_text(encoding="utf-8")
    check(
        "bridge:pinned-upstream-delegation",
        PLATFORM_COMMIT in bridge_source
        and "@tintinweb/pi-subagents/dist/index.js" in bridge_source
        and "new Proxy(pi" in bridge_source
        and 'property === "registerTool"' in bridge_source,
        "project-local bridge delegates to the pinned compiled extension through a minimal registration proxy",
    )
    check(
        "bridge:isolation-fail-closed",
        all(
            token in bridge_source
            for token in (
                "PROJECT017_AGENT_DISPATCH_POLICY",
                "project017_agent_dispatch_deterministic_admission_v2",
                'hasOwnProperty.call(params, "isolation")',
                "isolation_argument_forbidden_in_non_git_project",
                "duplicate_subagent_provider_proposal_coalesced",
                "project017DispatchAudit",
                'pi.on("tool_call"',
                'pi.on("tool_result"',
                "isError: true",
            )
        ),
        "bridge blocks unsafe dispatches, coalesces repeated provider proposals, and preserves both audit layers",
    )
    check(
        "bridge:deterministic-admission-boundary",
        all(
            token in bridge_source
            for token in (
                'executionMode: "sequential"',
                "completedRoleResults",
                'disposition: "coalesced"',
                "providerProposalCount",
                "canonicalToolCallId",
            )
        ),
        "Agent calls execute in source order and duplicate role proposals reuse a canonical completed result",
    )
    check(
        "bridge:single-tool-provider-policy",
        all(
            token in bridge_source
            for token in (
                'pi.on("before_provider_request"',
                "enforceSingleToolTurn",
                "disable_parallel_tool_use: true",
                'type: "auto"',
            )
        ),
        "Supervisor requests use Anthropic at-most-one Agent call semantics",
    )
    check(
        "bridge:no-spawn-source-copy",
        len(bridge_source) < 45000
        and "createAgentSession" not in bridge_source
        and "manager.spawn" not in bridge_source
        and "spawnAndWait" not in bridge_source,
        "bridge does not copy the upstream AgentSession or spawn implementation",
    )
    check(
        "bridge:strategy-cross-packet-validation",
        all(
            token in bridge_source
            for token in (
                "strategyReferenceCatalog",
                "validateStrategyReferences",
                "strategy_cross_packet_reference_validation_failed",
                "project017StrategyReferenceValidation",
            )
        ),
        "bridge rejects strategy results whose IDs are absent from the specialist audit catalog",
    )
    check(
        "bridge:redacted-native-audit",
        all(
            token in bridge_source
            for token in (
                "native-audit",
                'layer: "parent_dispatch"',
                'tool_name: "Agent"',
                "run_in_background_value",
                "automatic_retry: false",
            )
        ),
        "bridge persists a redacted parent Agent ledger for native reconciliation",
    )
    check(
        "bridge:execute-parameter-enrichment",
        all(
            token in bridge_source
            for token in (
                "startedRecorded",
                "enrichAttemptFromParams",
                "attempt.workflowRunId ??= workflowRunIdFromParams(params)",
                "enrichAttemptFromParams(attempt, params)",
                "run_in_background_false_required",
                "finishProposal",
                "provider_proposal_received",
                "provider_proposal_disposition",
            )
        ),
        "bridge enriches early provider proposals from complete execute parameters before admission",
    )

    platform_package = load_json(PLATFORM_ROOT / "package.json")
    runner_package = load_json(PLATFORM_ROOT / "container/agent-runner/package.json")
    platform_head = git_output("rev-parse", "HEAD")
    platform_status = git_output("status", "--short")
    check(
        "platform:commit",
        platform_head == PLATFORM_COMMIT,
        "read-only MiniClaw source remains at the declared commit",
    )
    check(
        "platform:clean",
        platform_status == "",
        "read-only MiniClaw source worktree remains clean",
    )
    check(
        "platform:pi-version",
        platform_package.get("dependencies", {}).get(
            "@earendil-works/pi-coding-agent"
        )
        == "0.84.2",
        "project017 Pi host pin matches the MiniClaw source",
    )
    check(
        "platform:subagents-version",
        runner_package.get("dependencies", {}).get("@tintinweb/pi-subagents")
        == "0.16.1",
        "frontmatter targets MiniClaw's pi-subagents 0.16.1 contract",
    )
    check(
        "platform:typebox-version",
        runner_package.get("dependencies", {}).get("typebox") == "1.3.7",
        "project017 schema dependency matches the MiniClaw runner",
    )
    pi_runtime_source = (
        PLATFORM_ROOT / "container/agent-runner/src/runtime/pi/pi-runtime.ts"
    ).read_text(encoding="utf-8")
    pi_index_source = (
        PLATFORM_ROOT / "container/agent-runner/src/pi-index.ts"
    ).read_text(encoding="utf-8")
    check(
        "platform:supervisor-extension-filter",
        "const selectedTools = options.allowedTools" in pi_runtime_source
        and "allowedTools: DEFAULT_ALLOWED_TOOLS" in pi_index_source
        and "commerce_ops_" not in pi_index_source,
        "MiniClaw source selects main-session tools without project017 business names",
    )

    subagent_manager_source = (
        PLATFORM_ROOT
        / "container/agent-runner/node_modules/@tintinweb/pi-subagents/src/agent-manager.ts"
    ).read_text(encoding="utf-8")
    subagent_runner_source = (
        PLATFORM_ROOT
        / "container/agent-runner/node_modules/@tintinweb/pi-subagents/src/agent-runner.ts"
    ).read_text(encoding="utf-8")
    platform_index_source = (PLATFORM_ROOT / "src/index.ts").read_text(
        encoding="utf-8"
    )
    check(
        "platform:tool-uses-activity-aggregate",
        subagent_manager_source.count(
            'if (activity.type === "end") record.toolUses++;'
        )
        >= 3
        and "tool_execution_end" in subagent_runner_source
        and "extension-error:" in subagent_runner_source,
        "pi-subagents toolUses counts activity-end events, including non-tool extension activity",
    )
    check(
        "platform:conversation-agent-idle-settlement",
        "updateAgentStatus(agentId, 'running');" in platform_index_source
        and "agent.kind === 'spawn' ? (hadError ? 'error' : 'completed') : 'idle'"
        in platform_index_source,
        "persistent conversation agents settle from running to idle in finally",
    )

    smoke_source = (
        project_root / "runtime/setup-helper/smoke.html"
    ).read_text(encoding="utf-8")
    check(
        "smoke:v3-unique-identity",
        all(
            token in smoke_source
            for token in (
                "运行验收-直播转化-v3-参数边界",
                "wf_runtime_smoke_live_v3_contract",
                "ds_live_runtime_smoke_v3_contract",
            )
        ),
        "third smoke uses unique session, workflow, and dataset identities",
    )
    check(
        "smoke:v3-attempt-contract",
        all(
            token in smoke_source
            for token in (
                "根对象禁止 synthetic",
                "Schema 参数校验失败也算一次 inspect 尝试",
                "禁止主动第二次调用 inspect",
                "失败尝试计入总次数",
                "全部 service_run_id",
            )
        ),
        "third smoke repeats the strict inspect boundary because the live Profile template is not applied",
    )
    check(
        "smoke:lifecycle-separation",
        all(
            token in smoke_source
            for token in (
                "platform_status=",
                "observed_execution_state=",
                "lifecycle_difference=",
                "不能互相改写",
            )
        ),
        "platform lifecycle and observed final reply state remain separate",
    )
    check(
        "smoke:lifecycle-settlement-grace",
        all(
            token in smoke_source
            for token in (
                "FINAL_REPLY_SETTLE_GRACE_MS = 20_000",
                "'idle'",
                "settlementGraceExpired",
                "platform_settled_after_final_reply",
                "正在只读等待平台状态",
            )
        ),
        "helper observes conversation-agent idle settlement before recording a lifecycle difference",
    )

    content_smoke_source = (
        project_root / "runtime/setup-helper/smoke-content.html"
    ).read_text(encoding="utf-8")
    check(
        "smoke:content-v2-unique-identity",
        all(
            token in content_smoke_source
            for token in (
                "运行验收-内容增长-v2-派发门控修复",
                "wf_runtime_smoke_content_v2_dispatch_guard",
                "ds_content_runtime_smoke_v2_dispatch_guard",
            )
        ),
        "post-fix content smoke uses a unique session, workflow, and dataset identity",
    )
    check(
        "smoke:content-v2-runtime-profile-guard",
        all(
            token in content_smoke_source
            for token in (
                "必须完全省略 isolation 参数",
                "不得再次调用 Agent",
                "project017 兼容桥",
                "qwen3.7-plus-2026-05-26",
            )
        ),
        "content smoke refuses submission unless the repaired Profile and authorized model are active",
    )
    check(
        "smoke:content-v2-single-submission-lock",
        all(
            token in content_smoke_source
            for token in (
                "miniclaw-content-smoke-v2-dispatch-guard-submission-started",
                "同名冒烟会话已存在且包含消息",
                "为避免不确定结果下重复计费",
                "不会自动重试",
            )
        ),
        "content smoke prevents task resubmission after a started or uncertain run",
    )

    setup_index_source = (
        project_root / "runtime/setup-helper/index.html"
    ).read_text(encoding="utf-8")
    setup_serve_source = (
        project_root / "runtime/setup-helper/serve.mjs"
    ).read_text(encoding="utf-8")
    check(
        "setup-helper:csp-allows-self-template",
        "connect-src 'self' http://127.0.0.1:3017" in setup_serve_source,
        "the setup helper can fetch its same-origin authored template and the local MiniClaw API",
    )
    check(
        "setup-helper:runtime-policy-subset-verification",
        all(
            token in setup_index_source
            for token in (
                "function isDeepSubset",
                "Object.entries(expected).every",
                "!isDeepSubset(existing.runtime_policy || null, expected.runtime_policy || null)",
            )
        ),
        "Profile verification requires authored policy fields while allowing platform-added defaults",
    )

    native_runtime_source = (
        project_root / "commerce_ops/native_runtime.py"
    ).read_text(encoding="utf-8")
    native_models_source = (
        project_root / "commerce_ops/native_models.py"
    ).read_text(encoding="utf-8")
    check(
        "native-runtime:topology-cardinality-reconciliation",
        all(
            token in native_runtime_source
            for token in (
                "parent_role_dispatch_count_mismatch",
                "specialist_tool_cardinality_mismatch",
                "strategy_dispatch_missing",
                'subagent_type=item.get("subagent_type")',
                "diagnostic_packets_available",
            )
        )
        and "subagent_type: str | None = None" in native_models_source,
        "native reconciliation verifies professional parent topology, specialist tool cardinality, and eligible strategy dispatch from observed audit data",
    )
    check(
        "native-runtime:settled-nonterminal-lifecycle-refresh",
        all(
            token in native_runtime_source
            for token in (
                "settled_lifecycle_is_stale",
                'record.platform_status not in SETTLED_PLATFORM_STATUSES',
                "and not settled_lifecycle_is_stale",
            )
        ),
        "a settled record with a nonterminal platform snapshot is re-observed without resubmitting the workflow",
    )
    check(
        "native-runtime:audit-authoritative-result",
        all(
            token in native_models_source
            for token in (
                "class NativeAuthoritativeResult",
                'result_type: Literal["project017_native_audit_result"]',
                "reported_service_run_ids: list[str] | None",
                "reported_analysis_run_ids: list[str] | None",
                "authoritative_result: NativeAuthoritativeResult | None",
            )
        )
        and all(
            token in native_runtime_source
            for token in (
                "_reported_string_list",
                "reported_services != ledger.service_run_ids",
                "_build_authoritative_result",
                "service_run_ids=ledger.service_run_ids",
                "analysis_run_ids=ledger.analysis_run_ids",
            )
        ),
        "the public final result takes ordered service and analysis IDs from the redacted project audit while retaining model-reported IDs only for reconciliation",
    )
    check(
        "native-runtime:resident-process-state-separated",
        'observed_execution_state: NativeExecutionState = "pending"'
        in native_models_source
        and all(
            token in native_runtime_source
            for token in (
                "audit_execution_settled",
                "structured_result_matches_run",
                "observed_execution_settled",
                "and not observed_execution_settled",
                '"settled" if observed_execution_settled else "unresolved"',
            )
        ),
        "a completed audited turn settles independently from the resident MiniClaw conversation process status",
    )
    check(
        "native-runtime:provider-proposal-observability",
        all(
            token in native_models_source
            for token in (
                "class NativeProviderProposal",
                "class NativeProposalSummary",
                "coalesced_proposals",
                "provider_proposals: list[NativeProviderProposal]",
            )
        )
        and all(
            token in native_runtime_source
            for token in (
                "def read_proposals",
                "provider_proposal_received",
                "provider_proposal_disposition",
                "_summarize_proposals",
            )
        ),
        "public native results expose provider proposals separately from the authoritative execution-attempt ledger",
    )
    check(
        "native-runtime:strategy-reference-reconciliation",
        all(
            token in native_models_source
            for token in (
                "strategy_reference_validation",
                "strategy_reference_error_codes",
                "strategy_cross_packet_references_valid",
            )
        )
        and all(
            token in native_runtime_source
            for token in (
                "strategy_cross_packet_reference_validation_failed",
                'strategy_reference_validation == "failed"',
                'strategy_reference_validation == "pass"',
            )
        ),
        "native reconciliation publishes explicit strategy cross-packet validation and blocks false completed states",
    )

    native_start_source = (
        project_root / "scripts/start-native-runtime.ps1"
    ).read_text(encoding="utf-8")
    check(
        "native-start:profile-sync-before-api",
        all(
            token in native_start_source
            for token in (
                '"$MiniClawBaseUrl/api/agent-profiles"',
                "Get-ProfileDifferences",
                "if ($profileDifferences.Count -gt 0)",
                "-Method Patch",
                "Get-ProfileDifferences -Existing $runtimeProfile -Expected $expectedProfile",
                "The synchronized project017 AgentProfile failed read-back verification.",
            )
        )
        and native_start_source.index('"$MiniClawBaseUrl/api/agent-profiles"')
        < native_start_source.index('$groupsPayload = Invoke-RestMethod')
        < native_start_source.index('$apiProcess = Start-Process'),
        "native startup synchronizes and reads back the authored Profile before checking the Workspace and starting the project API",
    )
    check(
        "native-start:profile-sync-fail-closed",
        all(
            token in native_start_source
            for token in (
                "Exactly one project017 AgentProfile must already exist",
                'qwen3.7-plus-2026-05-26',
                "The target Workspace is not bound to the synchronized project017 AgentProfile ID.",
                "database_ids_included = $false",
                "session_created = $false",
                "model_called = $false",
            )
        ),
        "native startup preserves the authorized Provider, refuses ambiguous Profile or Workspace state, and emits redacted no-model evidence",
    )

    profile_sync_assessment = load_json(
        project_root / "artifacts/runtime/native-profile-sync-v4-assessment.json"
    )
    check(
        "runtime-evidence:historical-profile-v4-synchronized",
        profile_sync_assessment.get("status") == "pass"
        and profile_sync_assessment.get("profile_version") == 4
        and all(
            re.fullmatch(r"[a-f0-9]{64}", value or "")
            for value in profile_sync_assessment.get("prompt_sha256", {}).values()
        )
        and all(
            profile_sync_assessment.get("checks", {}).get(key) is True
            for key in (
                "exactly_one_named_profile",
                "provider_binding_preserved",
                "authored_fields_match",
                "runtime_policy_authored_subset_matches",
                "workspace_binding_matches",
                "workspace_execution_mode_host",
                "workspace_interaction_mode_assistant",
                "workspace_custom_cwd_matches",
            )
        )
        and profile_sync_assessment.get("checks", {}).get("session_created")
        is False
        and profile_sync_assessment.get("checks", {}).get("model_called")
        is False
        and not any(profile_sync_assessment.get("redaction", {}).values()),
        "historical runtime Profile version 4 remains archived separately from the latest native startup synchronization record",
    )

    full_v3_trace = load_json(
        project_root / "artifacts/runtime/native-full-v3-redacted-trace.json"
    )
    full_v3_assessment = load_json(
        project_root / "artifacts/runtime/native-full-v3-assessment.json"
    )
    bridge_v11 = load_json(
        project_root / "artifacts/miniclaw-subagent-bridge-validation-v11.json"
    )
    bridge_v12 = load_json(
        project_root / "artifacts/miniclaw-subagent-bridge-validation-v12.json"
    )
    pi_extension_v6 = load_json(
        project_root / "artifacts/pi-extension-runtime-v6.json"
    )
    provider_chain_v1 = load_json(
        project_root / "artifacts/provider-request-chain-validation-v1.json"
    )
    root_cause_v1 = load_json(
        project_root
        / "artifacts/runtime/native-full-v4-root-cause-diagnosis-v1.json"
    )
    check(
        "runtime-evidence:full-v3-failure-preserved",
        full_v3_trace.get("workflow_run_id")
        == "wf_native_20260904T075456Z_ed8e4d4f55"
        and full_v3_trace.get("project_audit", {}).get("total_attempts") == 12
        and full_v3_trace.get("project_audit", {}).get("failed_or_blocked_attempts")
        == 3
        and full_v3_trace.get("specialist_tools", {}).get(
            "duplicate_live_analysis_blocked_before_mcp"
        )
        is True
        and full_v3_trace.get("parent_route", {}).get(
            "duplicate_strategy_dispatch_same_turn_observed"
        )
        is True
        and full_v3_assessment.get("overall_status")
        == "strict_fail_preserved_no_rerun",
        "the single full v3 run preserves its duplicate live analysis and duplicate strategy dispatch as a strict failure",
    )
    check(
        "runtime-evidence:bridge-v11-deterministic-admission-no-model",
        bridge_v11.get("status") == "pass"
        and bridge_v11.get("checks_total") == 36
        and bridge_v11.get("checks_failed") == 0
        and bridge_v11.get("guard_validation", {})
        .get("duplicate_role_proposal_result", {})
        .get("second_result_disposition")
        == "coalesced"
        and bridge_v11.get("guard_validation", {})
        .get("duplicate_role_proposal_result", {})
        .get("admitted_attempt_count")
        == 1
        and bridge_v11.get("provider_request_policy", {}).get(
            "supervisor_disable_parallel_tool_use"
        )
        is True
        and bridge_v11.get("provider_request_policy", {}).get(
            "specialist_disable_parallel_tool_use"
        )
        is True
        and bridge_v11.get("runtime", {}).get("model_called_by_this_validator")
        is False,
        "bridge v11 verifies without a model that Agent calls are serialized and duplicate role proposals coalesce to one admitted attempt",
    )
    check(
        "runtime-evidence:bridge-v12-strategy-reference-validation-no-model",
        bridge_v12.get("status") == "pass"
        and bridge_v12.get("checks_total") == 39
        and bridge_v12.get("checks_failed") == 0
        and all(
            next(
                (
                    item.get("status")
                    for item in bridge_v12.get("checks", [])
                    if item.get("check_id") == check_id
                ),
                None,
            )
            == "pass"
            for check_id in (
                "bridge:strategy-cross-packet-validation-source",
                "guard:strategy-valid-references-pass",
                "guard:strategy-invented-references-fail",
            )
        )
        and bridge_v12.get("runtime", {}).get("model_called_by_this_validator")
        is False,
        "bridge v12 proves without a model that audited strategy references pass and invented IDs fail",
    )
    check(
        "runtime-evidence:pi-extension-v6-reference-catalog",
        pi_extension_v6.get("status") == "pass"
        and pi_extension_v6.get("checks_total") == 23
        and pi_extension_v6.get("checks_failed") == 0
        and next(
            (
                item.get("status")
                for item in pi_extension_v6.get("checks", [])
                if item.get("check_id") == "audit:analysis-reference-catalog"
            ),
            None,
        )
        == "pass"
        and pi_extension_v6.get("evidence_boundary", {}).get(
            "real_model_called"
        )
        is False,
        "Pi extension v6 records only the cross-packet ID catalog needed by the strategy guard",
    )
    check(
        "runtime-evidence:provider-wire-chain-no-model",
        provider_chain_v1.get("status") == "pass"
        and provider_chain_v1.get("checks_total") == 14
        and provider_chain_v1.get("checks_failed") == 0
        and all(
            provider_chain_v1.get("observations", {})
            .get(role, {})
            .get("serialized_request", {})
            .get("tool_choice", {})
            .get("disable_parallel_tool_use")
            is True
            for role in ("supervisor", "specialist")
        )
        and provider_chain_v1.get("evidence_boundary", {}).get(
            "real_network_request_sent"
        )
        is False
        and provider_chain_v1.get("evidence_boundary", {}).get(
            "real_model_called"
        )
        is False,
        "Pi's real Anthropic serializer retains the project hook field in the outbound JSON body without network or model execution",
    )
    check(
        "runtime-evidence:v4-root-cause-diagnosis",
        root_cause_v1.get("status")
        == "local_fixes_pass_remote_semantics_unresolved"
        and root_cause_v1.get("provider_request_chain", {}).get(
            "root_cause_class"
        )
        == "provider_behavioral_contract_mismatch"
        and root_cause_v1.get("lifecycle_diagnosis", {})
        .get("project_fix", {})
        .get("platform_status_preserved_without_rewrite")
        is True
        and root_cause_v1.get("service_run_id_reconciliation", {})
        .get("project_fix", {})
        .get("model_id_mismatch_can_replace_audit_ids")
        is False
        and root_cause_v1.get("evidence_boundary", {}).get("model_called")
        is False,
        "v4 root-cause evidence excludes a local serializer bypass, separates resident process lifecycle, and makes project audit IDs authoritative",
    )

    content_v2_trace = load_json(
        project_root
        / "artifacts/runtime/smoke-content-v2-dispatch-guard-redacted-trace.json"
    )
    content_v2_assessment = load_json(
        project_root
        / "artifacts/runtime/smoke-content-v2-dispatch-guard-assessment.json"
    )
    check(
        "runtime-evidence:content-v2-provider-block-boundary",
        content_v2_trace.get("result", {}).get("terminal_status_from_sdk_trace")
        == "blocked_provider_arrearage"
        and content_v2_trace.get("route", {}).get("supervisor_agent_tool_attempts")
        == 0
        and content_v2_assessment.get("overall_verdict")
        == "not_evaluated_provider_arrearage",
        "provider rejection is preserved separately from Agent routing and contract results",
    )

    integration_doc = (
        project_root / "docs/MINICLAW-INTEGRATION-v2.md"
    ).read_text(encoding="utf-8")
    evidence_doc = (
        project_root / "docs/EVIDENCE-BOUNDARY.md"
    ).read_text(encoding="utf-8")
    runtime_observability_doc = (
        project_root / "docs/RUNTIME-OBSERVABILITY-v1.md"
    ).read_text(encoding="utf-8")
    check(
        "docs:integration-boundary",
        all(
            token in integration_doc
            for token in (
                "Provider configured in isolated runtime: `true`",
                "Plugin imported: `false`",
                "AgentSession executed: `true`",
                "Supervisor plus one specialist executed: `true`",
                "Full one-main-four-specialist workflow executed: `true`",
                "Full one-main-four-specialist strict acceptance: `false`",
                "静态/无模型 harness",
            )
        ),
        "integration guide separates harness, single-specialist runtime, and full-workflow evidence",
    )
    check(
        "docs:ownership-boundary",
        all(
            token in evidence_doc
            for token in ("本人完成", "平台整体架构", "尚待确认")
        ),
        "resume ownership categories remain explicit",
    )
    check(
        "docs:runtime-observability-authority",
        all(
            token in runtime_observability_doc
            for token in (
                "activity-end 聚合值",
                "显式 `toolCall`",
                "默认 `idleTimeout=1800000` 毫秒",
                "`observed_execution_state`",
                "`authoritative_result`",
                "不互相改写",
            )
        ),
        "runtime evidence uses explicit child calls, audit authority, and separate resident-process lifecycle state",
    )

    failed = [item for item in checks if item["status"] == "fail"]
    return {
        "schema_version": "1.0",
        "validation_kind": "project017_miniclaw_static_configuration",
        "status": "pass" if not failed else "fail",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "project_root": str(project_root),
        "source_platform_root": str(PLATFORM_ROOT),
        "source_platform_commit": PLATFORM_COMMIT,
        "checks_total": len(checks),
        "checks_passed": len(checks) - len(failed),
        "checks_failed": len(failed),
        "checks": checks,
        "evidence_boundary": {
            "scope_note": "These fields describe actions performed by this static validator, not the total runtime state of project017.",
            "static_validation_only": True,
            "provider_configured_by_this_validator": False,
            "plugin_imported_by_this_validator": False,
            "plugin_enabled_by_this_validator": False,
            "database_written_by_this_validator": False,
            "agent_session_created_by_this_validator": False,
            "agent_executed_by_this_validator": False,
            "model_called_by_this_validator": False,
            "runtime_evidence_reexecuted_by_this_validator": False,
            "real_business_data_used_by_this_validator": False,
            "real_business_outcome_claimed_by_this_validator": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    project_root = args.project_root.resolve()
    report = validate(project_root)
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    raise SystemExit(0 if report["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
