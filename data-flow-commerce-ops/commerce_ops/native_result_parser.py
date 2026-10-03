"""Extraction of the final structured result emitted by MiniClaw."""

import json
import re
from typing import Any


_RESULT_MARKER = "PROJECT017_NATIVE_RESULT_JSON"
_JSON_FENCE = re.compile(r"```json\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def _decode_result(candidate: str) -> dict[str, Any] | None:
    try:
        payload: Any = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != "1.0":
        return None
    if payload.get("result_type") != "project017_native_agent_result":
        return None
    return payload


def _decode_from_first_object(text: str) -> dict[str, Any] | None:
    brace_index = text.find("{")
    if brace_index < 0:
        return None
    try:
        payload, _ = json.JSONDecoder().raw_decode(text[brace_index:])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return _decode_result(json.dumps(payload))


def extract_native_result(text: str | None) -> dict[str, Any] | None:
    """Prefer the formal marker and safely fall back to typed JSON fences."""
    if not text:
        return None
    marker_index = text.rfind(_RESULT_MARKER)
    if marker_index >= 0:
        marked = _decode_from_first_object(text[marker_index + len(_RESULT_MARKER) :])
        if marked is not None:
            return marked
    for match in reversed(_JSON_FENCE.findall(text)):
        payload = _decode_result(match)
        if payload is not None:
            return payload
    return None
