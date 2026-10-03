"""Reproducible validation for the commerce workflow contract bundle."""

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from .models import CommerceWorkflowBundle


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = (
    PROJECT_ROOT / "contracts" / "commerce-ops-workflow-v1.schema.json"
)
DEFAULT_SAMPLE = (
    PROJECT_ROOT / "contracts" / "synthetic-commerce-workflow-example.json"
)

FORBIDDEN_SECRET_MARKERS = (
    "x-api-key:",
    "authorization: bearer",
    "sk-live-",
    "sk-proj-",
    "provider_key=",
)
FORBIDDEN_RAW_KEYS = {
    "phone",
    "mobile",
    "phone_number",
    "id_card",
    "identity_card",
    "raw_order_id",
    "raw_lead_id",
    "api_key",
    "provider_key",
    "access_token",
    "authorization",
}


class ContractValidationError(ValueError):
    pass


def validate_contract_bundle(
    schema_path: Path = DEFAULT_SCHEMA,
    sample_path: Path = DEFAULT_SAMPLE,
) -> dict[str, int | str]:
    schema = _read_json(schema_path)
    sample = _read_json(sample_path)
    return validate_contract_data(schema, sample)


def validate_contract_data(
    schema: dict[str, Any],
    sample: dict[str, Any],
) -> dict[str, int | str]:
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(
        schema,
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )
    errors = sorted(
        validator.iter_errors(sample),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        location = "/".join(str(item) for item in first.absolute_path)
        raise ContractValidationError(
            f"JSON Schema 校验失败: {location}: {first.message}"
        )

    _scan_sensitive_tokens(sample)
    try:
        bundle = CommerceWorkflowBundle.model_validate(sample)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = "/".join(str(item) for item in first["loc"])
        raise ContractValidationError(
            f"Pydantic/引用链校验失败: {location}: {first['msg']}"
        ) from exc

    return {
        "json_schema": "pass",
        "pydantic_models": "pass",
        "reference_chain": "pass",
        "sensitive_token_scan": "pass",
        "dataset_count": len(bundle.dataset_manifests),
        "analysis_packet_count": len(bundle.analysis_packets),
        "evidence_count": sum(
            len(item.evidence) for item in bundle.analysis_packets
        ),
        "finding_count": sum(
            len(item.findings) for item in bundle.analysis_packets
        ),
        "action_count": (
            len(bundle.decision_packet.actions)
            if bundle.decision_packet is not None
            else 0
        ),
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractValidationError(f"{path.name} 顶层必须是对象")
    return value


def _scan_sensitive_tokens(value: Any, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = key.strip().lower()
            if normalized_key in FORBIDDEN_RAW_KEYS:
                location = "/".join((*path, key))
                raise ContractValidationError(
                    f"契约样例包含禁止的原始敏感字段: {location}"
                )
            _scan_sensitive_tokens(child, (*path, key))
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _scan_sensitive_tokens(child, (*path, str(index)))
        return
    if isinstance(value, str):
        lowered = value.lower()
        for marker in FORBIDDEN_SECRET_MARKERS:
            if marker in lowered:
                location = "/".join(path)
                raise ContractValidationError(
                    f"契约样例包含疑似敏感令牌特征: {location}: {marker}"
                )


def main() -> None:
    print(
        json.dumps(
            validate_contract_bundle(),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
