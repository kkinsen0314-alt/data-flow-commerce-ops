from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from .conversation_models import (
    ConversationCatalog,
    ConversationContextLink,
    ConversationMessage,
    ConversationRecord,
    ConversationStatus,
    ConversationSubmissionRecord,
    ConversationSummary,
    ConversationThread,
)
from .conversation_store import ConversationStore
from .miniclaw_client import MiniClawClient, MiniClawClientError


class ConversationNotFound(RuntimeError):
    pass


class ConversationConflict(RuntimeError):
    pass


class ConversationUnavailable(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _digest(*values: str) -> str:
    return hashlib.sha256("\0".join(values).encode("utf-8")).hexdigest()


def _reference() -> str:
    return uuid4().hex[:12].upper()


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _safe_preview(value: Any, limit: int = 72) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    if not normalized:
        return None
    return normalized if len(normalized) <= limit else normalized[:limit] + "…"


class ConversationService:
    def __init__(self, client: MiniClawClient, store: ConversationStore) -> None:
        self.client = client
        self.store = store
        self._mutation_lock = asyncio.Lock()

    @staticmethod
    def scoped_key(user_id: str, workspace_jid: str, key: str) -> str:
        return _digest(workspace_jid, user_id, key)

    async def list_conversations(
        self, *, user_id: str, workspace_jid: str
    ) -> ConversationCatalog:
        records = self._owned_records(user_id, workspace_jid)
        sessions_by_id: dict[str, dict[str, Any]] = {}
        if records:
            try:
                payload = await self.client.get_sessions(workspace_jid)
                sessions_by_id = self._session_map(payload)
            except MiniClawClientError as exc:
                raise ConversationUnavailable(
                    "无法读取 Data Flow 对话，请检查 MiniClaw 服务。"
                ) from exc
        summaries = [
            self._present_summary(self._sync_session(record, sessions_by_id))
            for record in records
        ]
        return ConversationCatalog(conversations=summaries)

    async def create_conversation(
        self,
        *,
        user_id: str,
        workspace_jid: str,
        title: str,
        client_request_id: str,
    ) -> ConversationThread:
        creation_key = self.scoped_key(user_id, workspace_jid, client_request_id)
        fingerprint = _digest(title)
        async with self._mutation_lock:
            existing = self.store.find_by_creation_key(creation_key)
            if existing is not None:
                self._require_owner(existing, user_id, workspace_jid)
                if existing.creation_fingerprint != fingerprint:
                    raise ConversationConflict(
                        "同一创建编号已用于不同会话，请保留原会话。"
                    )
                return self._present_thread(existing, [])

            now = _now()
            record = ConversationRecord(
                reference=_reference(),
                creation_key=creation_key,
                creation_fingerprint=fingerprint,
                workspace_jid=workspace_jid,
                user_id=user_id,
                title=title,
                lifecycle="provisioning",
                created_at=now,
                updated_at=now,
            )
            self.store.save(record)
            try:
                payload = await self.client.create_session(
                    workspace_jid,
                    name=title,
                    description=(
                        "Data Flow 电商运营对话。围绕经营数据、分析任务与行动方案"
                        "回答用户问题；明确区分事实、推断和建议。"
                    ),
                )
                session = payload.get("session")
                session_id = session.get("id") if isinstance(session, dict) else None
                if not isinstance(session_id, str) or not session_id:
                    raise ValueError("MiniClaw session id missing")
                record = record.model_copy(
                    update={
                        "session_id": session_id,
                        "lifecycle": "ready",
                        "updated_at": _now(),
                    }
                )
                self.store.save(record)
                return self._present_thread(record, [])
            except MiniClawClientError as exc:
                lifecycle = (
                    "creation_uncertain" if exc.mutation_uncertain else "creation_failed"
                )
                self.store.save(
                    record.model_copy(
                        update={"lifecycle": lifecycle, "updated_at": _now()}
                    )
                )
                if exc.mutation_uncertain:
                    return self._present_thread(
                        record.model_copy(
                            update={"lifecycle": lifecycle, "updated_at": _now()}
                        ),
                        [],
                    )
                raise ConversationUnavailable(
                    "会话创建未被 MiniClaw 接受，请检查服务后新建会话。"
                ) from exc
            except ValueError as exc:
                record = record.model_copy(
                    update={"lifecycle": "creation_uncertain", "updated_at": _now()}
                )
                self.store.save(record)
                return self._present_thread(record, [])

    async def get_thread(
        self,
        *,
        reference: str,
        user_id: str,
        workspace_jid: str,
    ) -> ConversationThread:
        record = self._record(reference, user_id, workspace_jid)
        if record.session_id is None:
            return self._present_thread(record, [])
        try:
            sessions_payload, messages_payload = await asyncio.gather(
                self.client.get_sessions(workspace_jid),
                self.client.get_messages(workspace_jid, record.session_id, limit=200),
            )
        except MiniClawClientError as exc:
            raise ConversationUnavailable(
                "无法读取对话内容，请检查 MiniClaw 服务。"
            ) from exc
        record = self._sync_session(record, self._session_map(sessions_payload))
        raw_messages = messages_payload.get("messages")
        if not isinstance(raw_messages, list):
            raise ConversationUnavailable("MiniClaw 对话消息格式不受支持。")
        record = self._reconcile(record, raw_messages)
        messages = self._project_messages(record, raw_messages)
        return self._present_thread(record, messages)

    async def send_message(
        self,
        *,
        reference: str,
        user_id: str,
        workspace_jid: str,
        content: str,
        transport_content: str,
        context: ConversationContextLink | None,
        idempotency_key: str,
    ) -> ConversationThread:
        submission_key = self.scoped_key(user_id, workspace_jid, idempotency_key)
        content_hash = _digest(transport_content)
        request_fingerprint = _digest(
            reference,
            content,
            context.model_dump_json() if context else "",
        )
        async with self._mutation_lock:
            record = self._record(reference, user_id, workspace_jid)
            existing_record = self.store.find_by_submission_key(submission_key)
            if existing_record is not None:
                existing = next(
                    item
                    for item in existing_record.submissions
                    if item.submission_key == submission_key
                )
                if (
                    existing_record.reference != reference
                    or existing.request_fingerprint != request_fingerprint
                ):
                    raise ConversationConflict(
                        "同一发送编号已绑定不同消息；不会再次调用模型。"
                    )
                return await self.get_thread(
                    reference=reference,
                    user_id=user_id,
                    workspace_jid=workspace_jid,
                )

            thread = await self.get_thread(
                reference=reference,
                user_id=user_id,
                workspace_jid=workspace_jid,
            )
            record = self._record(reference, user_id, workspace_jid)
            if not thread.can_send or record.session_id is None:
                raise ConversationConflict(
                    "当前会话仍有消息待确认，请先查询原发送状态。"
                )

            attempted_at = _now()
            submission = ConversationSubmissionRecord(
                submission_key=submission_key,
                request_fingerprint=request_fingerprint,
                content_hash=content_hash,
                display_content=content,
                context=context,
                state="reserved",
                attempted_at=attempted_at,
            )
            record = record.model_copy(
                update={
                    "submissions": [*record.submissions, submission],
                    "updated_at": attempted_at,
                }
            )
            self.store.save(record)
            try:
                payload = await self.client.send_message_once(
                    workspace_jid, record.session_id, transport_content
                )
                message_id = payload.get("messageId")
                if payload.get("success") is not True or not isinstance(
                    message_id, str
                ):
                    raise ValueError("MiniClaw send acknowledgement missing")
                submitted_at = payload.get("timestamp")
                if not isinstance(submitted_at, str) or not submitted_at:
                    submitted_at = attempted_at
                run_id = payload.get("runId")
                updated_submission = submission.model_copy(
                    update={
                        "state": "accepted",
                        "submitted_at": submitted_at,
                        "message_id": message_id,
                        "run_id": run_id if isinstance(run_id, str) else None,
                    }
                )
                record = self._replace_submission(record, updated_submission)
                self.store.save(record)
                return self._present_thread(
                    record,
                    [
                        ConversationMessage(
                            message_reference=self._message_reference(
                                record.reference, message_id
                            ),
                            role="user",
                            content=content,
                            timestamp=submitted_at,
                            context=context,
                        )
                    ],
                )
            except MiniClawClientError as exc:
                state = "uncertain" if exc.mutation_uncertain else "rejected"
                record = self._replace_submission(
                    record, submission.model_copy(update={"state": state})
                )
                self.store.save(record)
                if exc.mutation_uncertain:
                    return self._present_thread(record, [])
                raise ConversationUnavailable(
                    "消息未被 MiniClaw 接受；本次不会自动重试。"
                ) from exc
            except ValueError:
                record = self._replace_submission(
                    record, submission.model_copy(update={"state": "uncertain"})
                )
                self.store.save(record)
                return self._present_thread(record, [])

    async def recover_submission(
        self,
        *,
        idempotency_key: str,
        user_id: str,
        workspace_jid: str,
    ) -> ConversationThread:
        submission_key = self.scoped_key(user_id, workspace_jid, idempotency_key)
        record = self.store.find_by_submission_key(submission_key)
        if record is None:
            raise ConversationNotFound(
                "尚未查到原发送记录；系统不会自动重新发送。"
            )
        self._require_owner(record, user_id, workspace_jid)
        return await self.get_thread(
            reference=record.reference,
            user_id=user_id,
            workspace_jid=workspace_jid,
        )

    def _owned_records(
        self, user_id: str, workspace_jid: str
    ) -> list[ConversationRecord]:
        return [
            item
            for item in self.store.list_all()
            if item.user_id == user_id and item.workspace_jid == workspace_jid
        ]

    def _record(
        self, reference: str, user_id: str, workspace_jid: str
    ) -> ConversationRecord:
        record = self.store.get(reference)
        if record is None:
            raise ConversationNotFound("没有找到对应的 Data Flow 对话。")
        self._require_owner(record, user_id, workspace_jid)
        return record

    @staticmethod
    def _require_owner(
        record: ConversationRecord, user_id: str, workspace_jid: str
    ) -> None:
        if record.user_id != user_id or record.workspace_jid != workspace_jid:
            raise ConversationNotFound("没有找到对应的 Data Flow 对话。")

    @staticmethod
    def _session_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        sessions = payload.get("sessions")
        if not isinstance(sessions, list):
            raise ConversationUnavailable("MiniClaw 会话列表格式不受支持。")
        return {
            item["id"]: item
            for item in sessions
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }

    def _sync_session(
        self,
        record: ConversationRecord,
        sessions_by_id: dict[str, dict[str, Any]],
    ) -> ConversationRecord:
        if record.session_id is None:
            return record
        session = sessions_by_id.get(record.session_id)
        if session is None:
            return record
        title = session.get("name")
        updates: dict[str, Any] = {}
        if isinstance(title, str) and title.strip() and title.strip() != record.title:
            updates["title"] = title.strip()[:40]
        status = session.get("status")
        if (
            status in {"error", "failed", "interrupted", "stopped"}
            and record.submissions
            and record.submissions[-1].state in {"reserved", "accepted"}
        ):
            failed = record.submissions[-1].model_copy(update={"state": "failed"})
            updates["submissions"] = [*record.submissions[:-1], failed]
        if updates:
            updates["updated_at"] = _now()
            updated = record.model_copy(update=updates)
            self.store.save(updated)
            return updated
        return record

    def _project_messages(
        self, record: ConversationRecord, raw_messages: list[Any]
    ) -> list[ConversationMessage]:
        projected: list[ConversationMessage] = []
        submissions_by_message = {
            item.message_id: item
            for item in record.submissions
            if item.message_id is not None
        }
        for raw in raw_messages:
            if not isinstance(raw, dict):
                continue
            content = raw.get("content")
            message_id = raw.get("id")
            timestamp = raw.get("timestamp")
            if not all(isinstance(value, str) and value for value in [content, message_id, timestamp]):
                continue
            if raw.get("is_from_me") is False and raw.get("sender") == record.user_id:
                role = "user"
                submission = submissions_by_message.get(message_id)
                if submission is not None and submission.display_content:
                    content = submission.display_content
                    context = submission.context
                else:
                    context = None
            elif self._is_safe_assistant(raw):
                role = "assistant"
                context = None
            else:
                continue
            truncated = len(content) > 20000
            projected.append(
                ConversationMessage(
                    message_reference=self._message_reference(
                        record.reference, message_id
                    ),
                    role=role,
                    content=content[:20000],
                    timestamp=timestamp,
                    truncated=truncated,
                    context=context,
                )
            )
        projected.sort(key=lambda item: (item.timestamp, item.message_reference))
        return projected

    def _reconcile(
        self,
        record: ConversationRecord,
        raw_messages: list[Any],
    ) -> ConversationRecord:
        if not record.submissions:
            return record
        submission = record.submissions[-1]
        if submission.state in {"completed", "rejected", "failed"}:
            return record
        attempted = _parse_timestamp(submission.attempted_at)
        submitted = _parse_timestamp(submission.submitted_at) or attempted
        matched_user: dict[str, Any] | None = None
        if submission.state == "uncertain":
            floor = attempted - timedelta(seconds=2) if attempted else None
            for raw in raw_messages:
                if not isinstance(raw, dict):
                    continue
                raw_time = _parse_timestamp(raw.get("timestamp"))
                if (
                    raw.get("is_from_me") is False
                    and raw.get("sender") == record.user_id
                    and isinstance(raw.get("content"), str)
                    and _digest(raw["content"].strip()) == submission.content_hash
                    and (floor is None or (raw_time is not None and raw_time >= floor))
                ):
                    matched_user = raw
                    break
            if matched_user is not None:
                submitted = _parse_timestamp(matched_user.get("timestamp")) or submitted
                submission = submission.model_copy(
                    update={
                        "state": "accepted",
                        "submitted_at": matched_user.get("timestamp"),
                        "message_id": matched_user.get("id"),
                    }
                )

        assistant_after = any(
            isinstance(raw, dict)
            and self._is_safe_assistant(raw)
            and (
                submitted is None
                or (
                    _parse_timestamp(raw.get("timestamp")) is not None
                    and _parse_timestamp(raw.get("timestamp")) > submitted
                )
            )
            for raw in raw_messages
        )
        if submission.state == "accepted" and assistant_after:
            submission = submission.model_copy(update={"state": "completed"})

        if submission != record.submissions[-1]:
            record = self._replace_submission(record, submission)
            self.store.save(record)
        return record

    @staticmethod
    def _is_safe_assistant(raw: dict[str, Any]) -> bool:
        safe_kinds = {
            "sdk_final",
            "proactive_sdk_fallback",
            "input_rejection_warning",
            "interrupt_partial",
            "overflow_partial",
            "compact_partial",
            "legacy",
        }
        return raw.get("is_from_me") is True and (
            raw.get("source_kind") in safe_kinds
            or raw.get("sender") == "miniclaw-agent"
        )

    @staticmethod
    def _replace_submission(
        record: ConversationRecord, submission: ConversationSubmissionRecord
    ) -> ConversationRecord:
        submissions = [
            submission if item.submission_key == submission.submission_key else item
            for item in record.submissions
        ]
        return record.model_copy(
            update={"submissions": submissions, "updated_at": _now()}
        )

    @staticmethod
    def _message_reference(conversation_reference: str, message_id: str) -> str:
        return _digest(conversation_reference, message_id)[:12].upper()

    def _status(self, record: ConversationRecord) -> ConversationStatus:
        if record.lifecycle == "creation_uncertain":
            return "uncertain"
        if record.lifecycle != "ready" or record.session_id is None:
            return "unavailable"
        if not record.submissions:
            return "ready"
        state = record.submissions[-1].state
        if state in {"reserved", "accepted"}:
            return "processing"
        if state == "uncertain":
            return "uncertain"
        if state in {"rejected", "failed"}:
            return "unavailable"
        return "ready"

    def _present_summary(self, record: ConversationRecord) -> ConversationSummary:
        status = self._status(record)
        status_labels = {
            "ready": "可以继续对话",
            "processing": "Data Flow 正在回复",
            "uncertain": "发送状态待确认",
            "unavailable": "会话需要检查",
        }
        return ConversationSummary(
            conversation_reference=record.reference,
            title=record.title,
            status=status,
            status_label=status_labels[status],
            latest_preview=None,
            created_at=record.created_at,
            updated_at=record.updated_at,
            can_send=status == "ready",
        )

    def _present_thread(
        self,
        record: ConversationRecord,
        messages: list[ConversationMessage],
    ) -> ConversationThread:
        summary = self._present_summary(record)
        preview = _safe_preview(messages[-1].content) if messages else None
        return ConversationThread(
            **summary.model_dump(exclude={"latest_preview"}),
            latest_preview=preview,
            messages=messages,
            pending_submission=summary.status == "processing",
            query_original_submission_only=summary.status == "uncertain",
        )
