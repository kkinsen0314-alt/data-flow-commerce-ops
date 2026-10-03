from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from uuid import uuid4

from .conversation_models import ConversationRecord


class ConversationStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def save(self, record: ConversationRecord) -> ConversationRecord:
        target = self.root / f"{record.reference}.json"
        temporary = self.root / f".{record.reference}.{uuid4().hex}.tmp"
        with self._lock:
            temporary.write_text(
                record.model_dump_json(indent=2),
                encoding="utf-8",
            )
            temporary.replace(target)
        return record

    def get(self, reference: str) -> ConversationRecord | None:
        target = self.root / f"{reference}.json"
        with self._lock:
            if not target.is_file():
                return None
            return ConversationRecord.model_validate_json(
                target.read_text(encoding="utf-8")
            )

    def list_all(self) -> list[ConversationRecord]:
        records: list[ConversationRecord] = []
        with self._lock:
            for target in self.root.glob("*.json"):
                try:
                    records.append(
                        ConversationRecord.model_validate_json(
                            target.read_text(encoding="utf-8")
                        )
                    )
                except (OSError, json.JSONDecodeError, ValueError):
                    continue
        return sorted(records, key=lambda item: item.updated_at, reverse=True)

    def find_by_creation_key(self, creation_key: str) -> ConversationRecord | None:
        return next(
            (item for item in self.list_all() if item.creation_key == creation_key),
            None,
        )

    def find_by_submission_key(
        self, submission_key: str
    ) -> ConversationRecord | None:
        return next(
            (
                item
                for item in self.list_all()
                if any(
                    submission.submission_key == submission_key
                    for submission in item.submissions
                )
            ),
            None,
        )
