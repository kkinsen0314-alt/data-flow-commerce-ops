import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";

import {
  workflowRunIdFromParams,
  withAuthoritativeWorkflowPrompt,
} from "../.pi/extensions/miniclaw-subagents-bridge/index.ts";
import {
  workflowRunIdFromDatasetIdentity,
  withAuthoritativeWorkflowIdentity,
} from "../.pi/extensions/commerce-ops-mcp/index.ts";

const datasetId = "ds_native_20260906T030000Z_identityabc_01";
const expected = "wf_native_20260906T030000Z_identityabc";
const conflicting = "wf_model_invented_value";
const parent = {
  prompt: `Use ${conflicting} with dataset ${datasetId}`,
  subagent_type: "content-growth-analyst",
  run_in_background: false,
};
assert.equal(workflowRunIdFromParams(parent), expected);
const prompted = withAuthoritativeWorkflowPrompt(parent);
assert.match(prompted.prompt, new RegExp(`PROJECT017_AUTHORITATIVE_WORKFLOW_RUN_ID=${expected}`));
const child = { workflow_run_id: conflicting, dataset_ids: [datasetId] };
assert.equal(workflowRunIdFromDatasetIdentity(child), expected);
assert.equal(withAuthoritativeWorkflowIdentity(child).workflow_run_id, expected);

const result = {
  schema_version: "1.0",
  validation_kind: "project017_workflow_identity_guards_no_model",
  status: "pass",
  checks_total: 4,
  checks_passed: 4,
  checks: [
    "parent_dataset_identity_precedes_model_workflow_text",
    "parent_prompt_receives_authoritative_workflow_literal",
    "specialist_dataset_identity_is_derived",
    "specialist_wrong_workflow_is_normalized_before_audit_and_mcp",
  ],
  model_called: false,
  agent_session_created: false,
};
const target = path.resolve("artifacts/workflow-identity-guards-v1.json");
await fs.writeFile(target, `${JSON.stringify(result, null, 2)}\n`, "utf8");
console.log(JSON.stringify(result, null, 2));
