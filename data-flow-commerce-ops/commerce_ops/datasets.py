"""Restricted dataset loading and manifest generation for commerce tools."""

from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

import pandas as pd

from .input import InputPayload, InputValidationError
from .models import (
    AnalysisReadiness,
    DatasetManifest,
    DatasetQuality,
    DatasetType,
    Dimension,
    FieldDefinition,
    RelationshipKey,
)
from .tool_models import DataReference


MAX_INPUT_BYTES = 25 * 1024 * 1024


ALIASES: dict[DatasetType, dict[str, str]] = {
    "short_video": {},
    "live_session": {
        "用户ID": "lead_id_hash",
        "直播场次": "live_session_id_hash",
        "直播标题": "live_title",
        "是否到课": "attended",
        "是否完课": "completed_view",
        "是否访问课程商品": "product_clicked",
        "是否领取优惠券": "coupon_claimed",
        "是否发起支付": "payment_initiated",
        "是否购买课程": "ordered",
        "是否观看回放": "watched_replay",
        "直播观看时长": "watch_seconds",
        "邀请人": "inviter",
        "线索渠道": "channel",
        "是否新用户": "is_new_user",
        "预约时间": "started_at",
    },
    "account": {},
    "channel_lead": {},
    "sales_followup": {},
    "order": {},
}

REQUIRED_FIELDS: dict[DatasetType, set[str]] = {
    "short_video": {
        "content_id_hash",
        "account_id_hash",
        "published_at",
        "impressions",
        "plays",
        "completions",
        "interactions",
        "clicks",
    },
    "live_session": {
        "live_session_id_hash",
        "started_at",
        "attended",
        "completed_view",
        "product_clicked",
        "payment_initiated",
        "ordered",
    },
    "account": {"account_id_hash", "platform", "account_group"},
    "channel_lead": {
        "lead_id_hash",
        "click_id_hash",
        "sales_owner_id_hash",
        "channel",
        "lead_source",
        "created_at",
        "lead_stage",
    },
    "sales_followup": {
        "lead_id_hash",
        "sales_owner_id_hash",
        "assigned_at",
        "first_followup_at",
        "followup_count",
        "followup_status",
    },
    "order": {
        "order_id_hash",
        "lead_id_hash",
        "ordered_at",
        "paid_amount",
        "order_status",
    },
}

DIMENSION_COLUMNS: dict[DatasetType, dict[Dimension, str]] = {
    "short_video": {
        "account": "account_id_hash",
        "content": "content_id_hash",
        "publish_time": "publish_period",
    },
    "live_session": {
        "account": "account_id_hash",
        "live_session": "live_session_id_hash",
        "channel": "channel",
    },
    "account": {"account": "account_id_hash"},
    "channel_lead": {
        "channel": "channel",
        "lead_source": "lead_source",
        "sales_owner": "sales_owner_id_hash",
    },
    "sales_followup": {"sales_owner": "sales_owner_id_hash"},
    "order": {"order_status": "order_status"},
}

RELATIONSHIP_FIELDS: dict[DatasetType, dict[str, tuple[str, list[DatasetType]]]] = {
    "short_video": {
        "content_id_hash": ("content", []),
        "account_id_hash": ("account", ["account", "live_session"]),
        "click_id_hash": ("click", ["channel_lead"]),
    },
    "live_session": {
        "live_session_id_hash": ("live_session", []),
        "account_id_hash": ("account", ["account", "short_video"]),
        "lead_id_hash": ("lead", ["channel_lead", "order"]),
    },
    "account": {
        "account_id_hash": ("account", ["short_video", "live_session"]),
    },
    "channel_lead": {
        "lead_id_hash": ("lead", ["sales_followup", "order", "live_session"]),
        "click_id_hash": ("click", ["short_video"]),
        "sales_owner_id_hash": ("sales_owner", ["sales_followup"]),
    },
    "sales_followup": {
        "lead_id_hash": ("lead", ["channel_lead", "order"]),
        "sales_owner_id_hash": ("sales_owner", ["channel_lead"]),
    },
    "order": {
        "order_id_hash": ("order", []),
        "lead_id_hash": ("lead", ["channel_lead", "sales_followup"]),
    },
}

BOOLEAN_FIELDS = {
    "attended",
    "completed_view",
    "product_clicked",
    "coupon_claimed",
    "payment_initiated",
    "ordered",
    "watched_replay",
    "is_new_user",
}
DATETIME_FIELDS = {
    "published_at",
    "started_at",
    "created_at",
    "assigned_at",
    "first_followup_at",
    "ordered_at",
    "paid_at",
}
NUMERIC_FIELDS = {
    "impressions",
    "plays",
    "completions",
    "interactions",
    "clicks",
    "viewers",
    "watch_seconds",
    "leads",
    "orders",
    "followup_count",
    "paid_amount",
    "cost_amount",
}


class DatasetAccessError(ValueError):
    def __init__(self, code: str, safe_message: str):
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


@dataclass(frozen=True)
class StoredDataset:
    workflow_run_id: str
    reference: DataReference
    path: Path
    payload: InputPayload
    frame: pd.DataFrame
    manifest: DatasetManifest


class DatasetStore:
    def __init__(
        self,
        data_root: Path,
        *,
        allow_non_synthetic: bool = False,
        max_input_bytes: int = MAX_INPUT_BYTES,
    ) -> None:
        self.data_root = data_root.expanduser().resolve()
        self.allow_non_synthetic = allow_non_synthetic
        self.max_input_bytes = max_input_bytes
        self._workflows: dict[str, dict[str, StoredDataset]] = {}
        self._lock = RLock()

    def load(
        self,
        workflow_run_id: str,
        reference: DataReference,
    ) -> StoredDataset:
        if not reference.synthetic and not self.allow_non_synthetic:
            raise DatasetAccessError(
                "INVALID_INPUT",
                "当前确定性工具层只允许 synthetic=true。",
            )
        path = self._resolve_path(reference.file_path)
        try:
            payload = InputPayload.from_shared_path(
                file_path=str(path),
                synthetic=reference.synthetic,
                max_upload_bytes=self.max_input_bytes,
            )
            frame = _read_frame(path)
        except InputValidationError as exc:
            raise DatasetAccessError(exc.code, exc.safe_message) from exc
        except (OSError, ValueError, ImportError) as exc:
            raise DatasetAccessError(
                "INVALID_INPUT",
                f"无法读取 {path.name}：{type(exc).__name__}。",
            ) from exc

        normalized, warnings = _normalize_frame(frame, reference.dataset_type)
        manifest = _build_manifest(
            workflow_run_id=workflow_run_id,
            reference=reference,
            payload=payload,
            frame=normalized,
            warnings=warnings,
        )
        stored = StoredDataset(
            workflow_run_id=workflow_run_id,
            reference=reference,
            path=path,
            payload=payload,
            frame=normalized,
            manifest=manifest,
        )
        with self._lock:
            workflow = self._workflows.setdefault(workflow_run_id, {})
            workflow[reference.dataset_id] = stored
        return stored

    def get(self, workflow_run_id: str, dataset_id: str) -> StoredDataset:
        with self._lock:
            stored = self._workflows.get(workflow_run_id, {}).get(dataset_id)
        if stored is None:
            raise DatasetAccessError(
                "ANALYSIS_UNAVAILABLE",
                f"{dataset_id} 尚未通过 inspect_commerce_data 注册。",
            )
        return stored

    def get_many(
        self,
        workflow_run_id: str,
        dataset_ids: list[str],
    ) -> list[StoredDataset]:
        return [self.get(workflow_run_id, item) for item in dataset_ids]

    def _resolve_path(self, raw_path: str) -> Path:
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = self.data_root / candidate
        resolved = candidate.resolve()
        if resolved != self.data_root and self.data_root not in resolved.parents:
            raise DatasetAccessError(
                "INVALID_INPUT",
                "file_path 必须位于 commerce_ops 数据根目录内。",
            )
        return resolved


def dimension_column(dataset_type: DatasetType, dimension: Dimension) -> str | None:
    return DIMENSION_COLUMNS.get(dataset_type, {}).get(dimension)


def _read_frame(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, encoding="utf-8-sig")
    return pd.read_excel(path)


def _normalize_frame(
    frame: pd.DataFrame,
    dataset_type: DatasetType,
) -> tuple[pd.DataFrame, list[str]]:
    normalized = frame.copy()
    normalized.columns = [str(item).strip() for item in normalized.columns]
    aliases = ALIASES[dataset_type]
    normalized = normalized.rename(
        columns={key: value for key, value in aliases.items() if key in normalized}
    )
    if len(normalized.columns) != len(set(normalized.columns)):
        raise DatasetAccessError(
            "INVALID_INPUT",
            "字段别名归一化后出现重复列。",
        )

    warnings: list[str] = []
    for field in BOOLEAN_FIELDS.intersection(normalized.columns):
        original = normalized[field].copy()
        normalized[field] = original.map(_normalize_boolean)
        invalid = int((original.notna() & normalized[field].isna()).sum())
        if invalid:
            warnings.append(f"{field} 有 {invalid} 行无法解析为布尔值")
    for field in DATETIME_FIELDS.intersection(normalized.columns):
        original = normalized[field].copy()
        normalized[field] = pd.to_datetime(original, errors="coerce")
        invalid = int((original.notna() & normalized[field].isna()).sum())
        if invalid:
            warnings.append(f"{field} 有 {invalid} 行无法解析为时间")
    for field in NUMERIC_FIELDS.intersection(normalized.columns):
        original = normalized[field].copy()
        if field == "watch_seconds" and not pd.api.types.is_numeric_dtype(
            original
        ):
            normalized[field] = pd.to_timedelta(
                original, errors="coerce"
            ).dt.total_seconds()
        else:
            normalized[field] = pd.to_numeric(original, errors="coerce")
        invalid = int((original.notna() & normalized[field].isna()).sum())
        if invalid:
            warnings.append(f"{field} 有 {invalid} 行无法解析为数值")

    if dataset_type == "short_video" and "published_at" in normalized:
        normalized["publish_period"] = normalized["published_at"].dt.strftime(
            "%Y-%m-%d %H:00"
        )
    return normalized, warnings


def _normalize_boolean(value: Any) -> bool | None:
    if pd.isna(value):
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "是", "新用户", "已支付"}:
        return True
    if normalized in {"0", "false", "no", "n", "否", "老用户", "未支付"}:
        return False
    return None


def _build_manifest(
    *,
    workflow_run_id: str,
    reference: DataReference,
    payload: InputPayload,
    frame: pd.DataFrame,
    warnings: list[str],
) -> DatasetManifest:
    columns = set(frame.columns)
    missing_required = sorted(REQUIRED_FIELDS[reference.dataset_type] - columns)
    duplicate_rows = int(frame.duplicated().sum())
    if frame.empty or missing_required:
        quality_status = "blocked"
    elif duplicate_rows or warnings:
        quality_status = "partial"
    else:
        quality_status = "pass"

    dimensions = [
        dimension
        for dimension, column in DIMENSION_COLUMNS[reference.dataset_type].items()
        if column in columns
    ]
    relationship_keys = _relationship_keys(reference.dataset_type, frame)
    cross_domain_allowed = any(
        item.stable and item.coverage_ratio > 0 and item.target_dataset_types
        for item in relationship_keys
    )
    has_cost = any(_semantic_role(item) == "cost" for item in frame.columns)
    reasons: list[str] = []
    if not cross_domain_allowed:
        reasons.append("未检测到覆盖率大于 0 的稳定脱敏跨域关联键")
    if not has_cost:
        reasons.append("未检测到成本字段，ROI 计算保持 blocked")

    return DatasetManifest(
        workflow_run_id=workflow_run_id,
        dataset_id=reference.dataset_id,
        dataset_type=reference.dataset_type,
        source_name=payload.file_name,
        sha256=payload.sha256,
        synthetic=reference.synthetic,
        fields=[
            FieldDefinition(
                name=str(column),
                data_type=_field_data_type(frame[column], str(column)),
                nullable=bool(frame[column].isna().any()),
                semantic_role=_semantic_role(str(column)),
                description=f"{reference.dataset_type} 合成数据字段 {column}",
            )
            for column in frame.columns
        ],
        available_dimensions=dimensions,
        relationship_keys=relationship_keys,
        data_quality=DatasetQuality(
            status=quality_status,
            row_count=len(frame),
            duplicate_rows=duplicate_rows,
            missing_required_fields=missing_required,
            warnings=(warnings + (["数据集为空"] if frame.empty else [])),
        ),
        analysis_readiness=AnalysisReadiness(
            cross_domain_attribution=(
                "allowed" if cross_domain_allowed else "blocked"
            ),
            roi_calculation="allowed" if has_cost else "blocked",
            reasons=reasons,
        ),
        contains_sensitive_data=False,
        redaction_applied=True,
    )


def _relationship_keys(
    dataset_type: DatasetType,
    frame: pd.DataFrame,
) -> list[RelationshipKey]:
    keys: list[RelationshipKey] = []
    for field, (entity_type, targets) in RELATIONSHIP_FIELDS[dataset_type].items():
        if field not in frame:
            continue
        coverage = float(frame[field].notna().mean()) if len(frame) else 0.0
        keys.append(
            RelationshipKey(
                field=field,
                entity_type=entity_type,
                stable=field.endswith("_hash"),
                coverage_ratio=round(coverage, 6),
                target_dataset_types=targets,
                hashed=field.endswith("_hash"),
                note="合成数据中的脱敏稳定键；只允许覆盖范围内关联。",
            )
        )
    return keys


def _semantic_role(field: str) -> str:
    if field in DATETIME_FIELDS:
        return "timestamp"
    if field in RELATIONSHIP_FIELDS.get("short_video", {}) or field.endswith(
        "_id_hash"
    ):
        return "relationship_key"
    if field in {"cost_amount", "ad_cost", "channel_cost"}:
        return "cost"
    if field in NUMERIC_FIELDS or field in BOOLEAN_FIELDS:
        return "metric"
    if field.endswith("_id"):
        return "identifier"
    return "dimension"


def _field_data_type(series: pd.Series, field: str) -> str:
    if field in DATETIME_FIELDS or pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_integer_dtype(series):
        return "integer"
    if pd.api.types.is_numeric_dtype(series):
        return "number"
    return "string"
