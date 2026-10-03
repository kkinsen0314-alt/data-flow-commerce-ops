"""Validated file input passed to the upstream analysis service."""

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Literal


ALLOWED_SUFFIXES = {".csv", ".xls", ".xlsx", ".xlsm"}


class InputValidationError(ValueError):
    def __init__(self, code: str, safe_message: str):
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


@dataclass(frozen=True)
class InputPayload:
    transport: Literal["file_upload", "shared_path"]
    file_name: str
    size_bytes: int
    sha256: str
    synthetic: bool
    content: bytes | None = field(default=None, repr=False)
    file_path: str | None = None

    @classmethod
    def from_upload(
        cls,
        file_name: str,
        content: bytes,
        synthetic: bool,
        max_upload_bytes: int,
    ) -> "InputPayload":
        normalized_name = Path(file_name).name
        _validate_name_and_size(normalized_name, len(content), max_upload_bytes)
        return cls(
            transport="file_upload",
            file_name=normalized_name,
            size_bytes=len(content),
            sha256=sha256(content).hexdigest(),
            synthetic=synthetic,
            content=content,
        )

    @classmethod
    def from_shared_path(
        cls,
        file_path: str,
        synthetic: bool,
        max_upload_bytes: int,
    ) -> "InputPayload":
        resolved = Path(file_path).expanduser().resolve()
        if not resolved.exists() or not resolved.is_file():
            raise InputValidationError("INVALID_INPUT", "file_path 不存在或不是文件。")
        size_bytes = resolved.stat().st_size
        _validate_name_and_size(resolved.name, size_bytes, max_upload_bytes)
        digest = sha256(resolved.read_bytes()).hexdigest()
        return cls(
            transport="shared_path",
            file_name=resolved.name,
            file_path=str(resolved),
            size_bytes=size_bytes,
            sha256=digest,
            synthetic=synthetic,
        )


def _validate_name_and_size(
    file_name: str,
    size_bytes: int,
    max_upload_bytes: int,
) -> None:
    if not file_name or Path(file_name).suffix.lower() not in ALLOWED_SUFFIXES:
        raise InputValidationError(
            "INVALID_INPUT",
            "仅支持 CSV、XLS、XLSX 和 XLSM 文件。",
        )
    if size_bytes <= 0:
        raise InputValidationError("INVALID_INPUT", "数据文件不能为空。")
    if size_bytes > max_upload_bytes:
        raise InputValidationError(
            "PAYLOAD_TOO_LARGE",
            "数据文件超过适配层允许的大小上限。",
        )
