import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "build-github-source-preview.py"
CONTRACT_PATH = PROJECT_ROOT / "contracts" / "github-source-preview-v1.json"
PLAN_PATH = PROJECT_ROOT / "evals" / "real-run-plan-v1.json"


def load_builder_module():
    spec = importlib.util.spec_from_file_location(
        "build_github_source_preview",
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 GitHub source preview 构建器")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load_builder_module()


class GithubSourcePreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (PROJECT_ROOT / "tmp").mkdir(parents=True, exist_ok=True)

    def test_allowlist_covers_delivery_plan_and_excludes_private_roots(self):
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
        files = builder.collect_source_files(contract)

        required = plan["github_delivery"]["required_current_paths"]
        self.assertEqual([path for path in required if path not in files], [])
        self.assertFalse(any("node_modules" in Path(path).parts for path in files))
        self.assertFalse(any("runtime" in Path(path).parts for path in files))
        self.assertNotIn("skills-lock.json", files)
        self.assertFalse(any(path.startswith(".agents/") for path in files))

    def test_public_readme_is_formal_native_preview(self):
        files = builder.collect_source_files()
        readme = files["README.md"].read_text(encoding="utf-8")

        self.assertIn("http://127.0.0.1:3022/native", readme)
        self.assertIn("真实 Agent 评测已执行 5/30", readme)
        self.assertIn("source preview", readme)
        self.assertNotIn("http://127.0.0.1:3022/demo", readme)

    def test_allowlist_includes_current_data_flow_entrypoints(self):
        files = builder.collect_source_files()
        required = [
            "native_app/src/main.tsx",
            "native_app/src/pages/DataFlowLoginPage.tsx",
            "native_app/src/pages/OperationsEntryPage.tsx",
            "native_app/src/pages/ConversationsPage.tsx",
            "native_app/src/pages/VisualizationsPage.tsx",
            "scripts/build-data-flow-web.mjs",
            "tests/operations_browser_harness.py",
            "tests/verify_data_flow_design.mjs",
            "tests/verify_data_flow_operations.mjs",
            "tests/verify_data_flow_conversations.mjs",
            "tests/verify_data_flow_visualizations.mjs",
            "docs/DATA-FLOW-AUTHENTICATED-API-v1.md",
            "docs/DATA-FLOW-CONVERSATIONS-v1.md",
            "docs/DATA-FLOW-VISUALIZATIONS-v1.md",
            "docs/DATA-FLOW-DESIGN-SYSTEM-v1.md",
        ]

        self.assertEqual([path for path in required if path not in files], [])

    def test_secret_scan_covers_react_page_files(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "tmp") as folder:
            page = Path(folder) / "Leak.tsx"
            page.write_text(
                'const key = "' + "sk-" + "a" * 24 + '";\n',
                encoding="utf-8",
            )
            matches = builder._scan_text_secrets({"native_app/src/Leak.tsx": page})

        self.assertEqual(
            matches,
            [{"path": "native_app/src/Leak.tsx", "pattern": "provider_token"}],
        )

    def test_current_package_manifest_is_complete_and_truthful(self):
        package_root = (
            PROJECT_ROOT
            if (PROJECT_ROOT / "PUBLIC-PREVIEW-MANIFEST.json").is_file()
            else PROJECT_ROOT / "release" / "data-flow-commerce-ops"
        )
        manifest = json.loads(
            (package_root / "PUBLIC-PREVIEW-MANIFEST.json").read_text(encoding="utf-8")
        )
        public_paths = [entry["path"] for entry in manifest["files"]]
        public_paths.extend(["FILE-MANIFEST.txt", "PUBLIC-PREVIEW-MANIFEST.json"])
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "tmp") as folder:
            snapshot = Path(folder)
            for relative_text in public_paths:
                relative = builder._normalized_relative(relative_text)
                target = snapshot / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(package_root / relative, target)
            report = builder.validate_package(snapshot)

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["real_agent_evaluation"], "5/30 executed")
        self.assertEqual(report["quality_release_status"], "blocked")

    def test_cookie_scan_does_not_mistake_type_annotations_for_headers(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "tmp") as folder:
            source = Path(folder) / "auth.py"
            source.write_text(
                "def authorize(cookie: str, required_permissions: list[str]):\n    pass\n",
                encoding="utf-8",
            )
            matches = builder._scan_text_secrets({"commerce_ops/auth.py": source})

        self.assertEqual(matches, [])

    def test_cookie_scan_rejects_literal_session_header(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "tmp") as folder:
            source = Path(folder) / "headers.txt"
            source.write_text(
                "Cookie: " + "miniclaw_session=" + "a" * 24 + "\n",
                encoding="utf-8",
            )
            matches = builder._scan_text_secrets({"headers.txt": source})

        self.assertEqual(
            matches,
            [{"path": "headers.txt", "pattern": "cookie_value"}],
        )

    def test_public_package_normalizes_text_but_preserves_binary_bytes(self):
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "tmp") as folder:
            root = Path(folder)
            text_source = root / "example.json"
            text_source.write_bytes(b'{\r\n  "synthetic": true\r\n}\r\n')
            binary_source = root / "example.pdf"
            binary_bytes = b"%PDF\r\n\x00synthetic fixture\r\n"
            binary_source.write_bytes(binary_bytes)
            staging = root / "staging"
            staging.mkdir()
            entries = builder._copy_to_staging({
                "config/example.json": text_source,
                "fixture.pdf": binary_source,
            }, staging)
            builder._write_public_manifests(staging, entries, contract)

            self.assertEqual(
                (staging / "config/example.json").read_bytes(),
                b'{\n  "synthetic": true\n}\n',
            )
            self.assertEqual((staging / "fixture.pdf").read_bytes(), binary_bytes)
            for name in ("FILE-MANIFEST.txt", "PUBLIC-PREVIEW-MANIFEST.json"):
                self.assertNotIn(b"\r\n", (staging / name).read_bytes())

    def test_managed_path_guard_rejects_outside_release_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            outside = Path(temp_dir) / "preview"
            with self.assertRaises(builder.PreviewBuildError):
                builder._validate_managed_path(outside)

    def test_default_cli_build_uses_data_flow_package_and_archive_names(self):
        result = subprocess.run(
            [sys.executable, "-X", "utf8", str(SCRIPT_PATH)],
            cwd=PROJECT_ROOT,
            capture_output=True,
            encoding="utf-8",
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["package"]["root"], "release/data-flow-commerce-ops")
        archive = PROJECT_ROOT / report["zip"]["path"]
        self.assertTrue(archive.name.startswith("data-flow-commerce-ops-source-preview-"))
        with zipfile.ZipFile(archive) as handle:
            names = handle.namelist()
        self.assertTrue(names)
        self.assertTrue(all(name.startswith("data-flow-commerce-ops/") for name in names))


if __name__ == "__main__":
    unittest.main()
