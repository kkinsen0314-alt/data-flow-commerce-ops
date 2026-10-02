"""Build and verify the public GitHub source preview from an explicit allowlist."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import zipfile
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = PROJECT_ROOT / "contracts" / "github-source-preview-v1.json"
EVAL_PLAN_PATH = PROJECT_ROOT / "evals" / "real-run-plan-v1.json"
RELEASE_PARENT = PROJECT_ROOT / "release"
DEFAULT_TARGET = RELEASE_PARENT / "miniclaw-commerce-ops"
DEFAULT_VALIDATION = (
    PROJECT_ROOT / "artifacts" / "github-source-preview-validation-v1.json"
)
TEXT_SUFFIXES = {
    ".cjs",
    ".css",
    ".csv",
    ".html",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".ps1",
    ".py",
    ".svg",
    ".ts",
    ".tsx",
    ".txt",
    ".webmanifest",
}
SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "provider_token": re.compile(r"\b(?:sk|ak)-[A-Za-z0-9_-]{16,}\b"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "bearer_token": re.compile(
        r"(?i)\b(?:authorization|proxy-authorization)\s*:\s*bearer\s+"
        r"(?!example\b|<)[A-Za-z0-9._~+/=-]{16,}"
    ),
    "cookie_value": re.compile(
        r"(?i)\b(?:cookie|set-cookie)[\"']?\s*:\s*[\"']?"
        r"(?!<)[A-Za-z0-9_.-]+\s*=\s*(?!<)[A-Za-z0-9._~+/=-]{16,}"
    ),
    "user_profile_path": re.compile(r"(?i)\bC:\\Users\\[^\\\s]+"),
}


class PreviewBuildError(ValueError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PreviewBuildError(f"JSON root must be an object: {path}")
    return value


def _relative_text(path: Path) -> str:
    return str(path).replace("\\", "/")


def _normalized_relative(value: str) -> Path:
    candidate = Path(value.replace("\\", "/"))
    if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
        raise PreviewBuildError(f"unsafe relative path: {value}")
    return candidate


def _validate_managed_path(path: Path) -> Path:
    resolved = path.resolve()
    release_root = RELEASE_PARENT.resolve()
    if resolved == release_root or release_root not in resolved.parents:
        raise PreviewBuildError(f"managed release path is outside release/: {path}")
    return resolved


def _is_forbidden(relative: Path, contract: dict[str, Any]) -> bool:
    lowered_parts = {part.lower() for part in relative.parts}
    if lowered_parts.intersection(
        part.lower() for part in contract["forbidden_path_parts"]
    ):
        return True
    if relative.name.lower() in {
        name.lower() for name in contract["forbidden_file_names"]
    }:
        return True
    return relative.suffix.lower() in {
        suffix.lower() for suffix in contract["forbidden_suffixes"]
    }


def collect_source_files(
    contract: dict[str, Any] | None = None,
) -> dict[str, Path]:
    contract = contract or _load_json(CONTRACT_PATH)
    collected: dict[str, Path] = {}

    def add(destination_text: str, source_text: str) -> None:
        destination = _normalized_relative(destination_text)
        source_relative = _normalized_relative(source_text)
        source = PROJECT_ROOT / source_relative
        if not source.is_file() or source.is_symlink():
            raise PreviewBuildError(f"missing or unsupported source file: {source_text}")
        if _is_forbidden(destination, contract) or _is_forbidden(
            source_relative, contract
        ):
            raise PreviewBuildError(f"allowlist includes forbidden path: {source_text}")
        destination_key = _relative_text(destination)
        if destination_key in collected:
            if collected[destination_key] != source:
                raise PreviewBuildError(f"duplicate destination: {destination_key}")
            return
        collected[destination_key] = source

    for destination, source in contract["root_file_mappings"].items():
        add(destination, source)
    for root_text in contract["recursive_roots"]:
        root_relative = _normalized_relative(root_text)
        root = PROJECT_ROOT / root_relative
        if not root.is_dir() or root.is_symlink():
            raise PreviewBuildError(f"missing or unsupported source root: {root_text}")
        for source in sorted(path for path in root.rglob("*") if path.is_file()):
            relative = source.relative_to(PROJECT_ROOT)
            if source.is_symlink() or _is_forbidden(relative, contract):
                continue
            add(_relative_text(relative), _relative_text(relative))
    for source_text in contract["included_docs"]:
        add(source_text, source_text)
    for source_text in contract["included_scripts"]:
        add(source_text, source_text)
    for source_text in contract["included_artifacts"]:
        add(source_text, source_text)
    for pattern in contract["test_globs"]:
        matches = sorted(PROJECT_ROOT.glob(pattern))
        if not matches:
            raise PreviewBuildError(f"test glob matched no files: {pattern}")
        for source in matches:
            relative = source.relative_to(PROJECT_ROOT)
            add(_relative_text(relative), _relative_text(relative))
    return dict(sorted(collected.items()))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _scan_text_secrets(files: dict[str, Path]) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    for relative, path in files.items():
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name != ".gitignore":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise PreviewBuildError(f"public text is not UTF-8: {relative}") from exc
        for pattern_name, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                matches.append({"path": relative, "pattern": pattern_name})
    return matches


def validate_source_contract(
    files: dict[str, Path],
    contract: dict[str, Any],
) -> dict[str, Any]:
    eval_plan = _load_json(EVAL_PLAN_PATH)
    required = eval_plan.get("github_delivery", {}).get(
        "required_current_paths", []
    )
    missing = sorted(path for path in required if path not in files)
    forbidden = sorted(
        relative
        for relative in files
        if _is_forbidden(Path(relative), contract)
    )
    secret_matches = _scan_text_secrets(files)
    readme = files["README.md"].read_text(encoding="utf-8")
    missing_disclosures = [
        phrase
        for phrase in contract["required_disclosures"]
        if phrase not in readme
    ]
    if missing or forbidden or secret_matches or missing_disclosures:
        raise PreviewBuildError(
            "source preview contract failed: "
            f"missing={missing}, forbidden={forbidden}, "
            f"secret_matches={secret_matches}, "
            f"missing_disclosures={missing_disclosures}"
        )
    return {
        "required_paths_present": True,
        "forbidden_path_matches": [],
        "secret_pattern_matches": [],
        "required_disclosures_present": True,
    }


def _copy_to_staging(files: dict[str, Path], staging: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for relative, source in files.items():
        destination = staging / Path(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix.lower() in TEXT_SUFFIXES or source.name == ".gitignore":
            destination.write_bytes(source.read_text(encoding="utf-8").encode("utf-8"))
        else:
            shutil.copy2(source, destination)
        entries.append(
            {
                "path": relative,
                "size_bytes": destination.stat().st_size,
                "sha256": _sha256(destination),
            }
        )
    return entries


def _write_public_manifests(
    staging: Path,
    entries: list[dict[str, Any]],
    contract: dict[str, Any],
) -> None:
    evidence = contract["evidence_snapshot"]
    manifest = {
        "schema_version": "1.0",
        "record_type": "commerce_ops_github_source_preview_manifest",
        "release_type": "source_preview_not_evaluated_release",
        "release_date": contract["release_date"],
        "file_count_excluding_generated_manifests": len(entries),
        "fixture_preflight": evidence["fixture_preflight"],
        "real_agent_evaluation": evidence["real_agent_evaluation"],
        "semantic_review": evidence["semantic_review"],
        "quality_release_status": evidence["quality_release_status"],
        "model_called_by_builder": False,
        "judge_called_by_builder": False,
        "github_published_by_builder": False,
        "synthetic_data_only": True,
        "forbidden_path_matches": [],
        "secret_pattern_matches": [],
        "files": entries,
    }
    (staging / "PUBLIC-PREVIEW-MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    manifest_paths = [entry["path"] for entry in entries]
    manifest_paths.extend(
        ["FILE-MANIFEST.txt", "PUBLIC-PREVIEW-MANIFEST.json"]
    )
    (staging / "FILE-MANIFEST.txt").write_text(
        "\n".join(sorted(manifest_paths)) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def validate_package(package_root: Path) -> dict[str, Any]:
    root = package_root.resolve()
    manifest_path = root / "PUBLIC-PREVIEW-MANIFEST.json"
    manifest = _load_json(manifest_path)
    if manifest.get("release_type") != "source_preview_not_evaluated_release":
        raise PreviewBuildError("package release_type is not a source preview")
    real_eval = manifest.get("real_agent_evaluation")
    if not isinstance(real_eval, str) or not re.fullmatch(
        r"(?:0/30|(?:[1-9]|[12][0-9]|30)/30 executed)", real_eval
    ):
        raise PreviewBuildError("package real evaluation disclosure is invalid")
    errors: list[str] = []
    for entry in manifest.get("files", []):
        relative = _normalized_relative(entry["path"])
        path = root / relative
        if not path.is_file():
            errors.append(f"missing:{entry['path']}")
            continue
        if path.stat().st_size != entry["size_bytes"]:
            errors.append(f"size:{entry['path']}")
        if _sha256(path) != entry["sha256"]:
            errors.append(f"sha256:{entry['path']}")
    actual_paths = sorted(
        _relative_text(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file()
    )
    declared_paths = sorted(
        [entry["path"] for entry in manifest["files"]]
        + ["FILE-MANIFEST.txt", "PUBLIC-PREVIEW-MANIFEST.json"]
    )
    if actual_paths != declared_paths:
        errors.append("file_set")
    if errors:
        raise PreviewBuildError(f"package verification failed: {errors}")
    return {
        "status": "pass",
        "package_root": str(root),
        "file_count": len(actual_paths),
        "manifest_entries_verified": len(manifest["files"]),
        "real_agent_evaluation": manifest["real_agent_evaluation"],
        "quality_release_status": manifest["quality_release_status"],
    }


def _create_zip(package_root: Path, zip_path: Path) -> str:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(
        zip_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in sorted(item for item in package_root.rglob("*") if item.is_file()):
            relative = path.relative_to(package_root)
            info = zipfile.ZipInfo(
                f"{package_root.name}/{_relative_text(relative)}",
                date_time=(2026, 9, 11, 0, 0, 0),
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    return _sha256(zip_path)


def validate_zip(zip_path: Path, package_root: Path) -> dict[str, Any]:
    expected = {
        f"{package_root.name}/{_relative_text(path.relative_to(package_root))}": path
        for path in package_root.rglob("*")
        if path.is_file()
    }
    with zipfile.ZipFile(zip_path) as archive:
        names = sorted(info.filename for info in archive.infolist() if not info.is_dir())
        if names != sorted(expected):
            raise PreviewBuildError("ZIP file set does not match package directory")
        for name, source in expected.items():
            if hashlib.sha256(archive.read(name)).hexdigest() != _sha256(source):
                raise PreviewBuildError(f"ZIP content hash mismatch: {name}")
    return {
        "status": "pass",
        "entry_count": len(expected),
        "file_set_matches_package": True,
        "content_hashes_match_package": True,
    }


def build_preview(
    target: Path = DEFAULT_TARGET,
    validation_output: Path = DEFAULT_VALIDATION,
) -> dict[str, Any]:
    target = _validate_managed_path(target)
    validation_output = validation_output.resolve()
    if PROJECT_ROOT.resolve() not in validation_output.parents:
        raise PreviewBuildError("validation output must stay inside project root")
    contract = _load_json(CONTRACT_PATH)
    if contract.get("record_type") != "commerce_ops_github_source_preview_contract":
        raise PreviewBuildError("unexpected source preview contract")
    files = collect_source_files(contract)
    source_checks = validate_source_contract(files, contract)
    RELEASE_PARENT.mkdir(parents=True, exist_ok=True)
    staging = _validate_managed_path(
        RELEASE_PARENT / f".{contract['release_name']}-staging"
    )
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    archived_previous: str | None = None
    try:
        entries = _copy_to_staging(files, staging)
        _write_public_manifests(staging, entries, contract)
        validate_package(staging)
        if target.exists():
            archive_root = RELEASE_PARENT / "archive"
            archive_root.mkdir(parents=True, exist_ok=True)
            suffix = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            archive_target = _validate_managed_path(
                archive_root / f"{target.name}-{suffix}"
            )
            if archive_target.exists():
                raise PreviewBuildError(f"archive target already exists: {archive_target}")
            target.replace(archive_target)
            archived_previous = _relative_text(
                archive_target.relative_to(PROJECT_ROOT)
            )
        staging.replace(target)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    package_validation = validate_package(target)
    zip_path = RELEASE_PARENT / (
        f"{contract['release_name']}-source-preview-{contract['release_date']}.zip"
    )
    zip_sha256 = _create_zip(target, zip_path)
    zip_validation = validate_zip(zip_path, target)
    sha_path = zip_path.with_suffix(".sha256.txt")
    sha_path.write_text(
        f"{zip_sha256}  {zip_path.name}\n",
        encoding="utf-8",
    )
    report = {
        "schema_version": "1.0",
        "record_type": "commerce_ops_github_source_preview_validation",
        "generated_at": datetime.now(UTC).astimezone().isoformat(),
        "status": "pass",
        "execution_mode": "deterministic_no_model_no_judge_no_publish",
        "source_contract": _relative_text(CONTRACT_PATH.relative_to(PROJECT_ROOT)),
        "source_checks": source_checks,
        "package": {
            "root": _relative_text(target.relative_to(PROJECT_ROOT)),
            "file_count": package_validation["file_count"],
            "manifest_entries_verified": package_validation[
                "manifest_entries_verified"
            ],
            "real_agent_evaluation": package_validation[
                "real_agent_evaluation"
            ],
            "quality_release_status": package_validation[
                "quality_release_status"
            ],
        },
        "archive": archived_previous,
        "zip": {
            "path": _relative_text(zip_path.relative_to(PROJECT_ROOT)),
            "size_bytes": zip_path.stat().st_size,
            "sha256": zip_sha256,
            "sha256_file": _relative_text(sha_path.relative_to(PROJECT_ROOT)),
            "validation": zip_validation,
        },
        "model_called": False,
        "judge_called": False,
        "github_published": False,
    }
    validation_output.parent.mkdir(parents=True, exist_ok=True)
    validation_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or validate the MiniClaw GitHub source preview."
    )
    parser.add_argument("--validate-only", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = (
            validate_package(args.validate_only)
            if args.validate_only
            else build_preview()
        )
        print(json.dumps(report, ensure_ascii=False))
        return 0
    except (OSError, json.JSONDecodeError, PreviewBuildError) as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "safe_message": str(exc),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
