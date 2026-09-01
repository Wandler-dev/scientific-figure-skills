from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_ROOT / "scripts"
F001 = SKILL_ROOT / "examples" / "F001-evidence-traceable-reconstruction.md"
FAKE_DRAWIO = SKILL_ROOT / "tests" / "fixtures" / "fake_drawio_cli.py"


def load_module(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runtime = load_module("figure_runtime", SCRIPTS / "figure_runtime.py")
load_module("validate_figure_spec", SCRIPTS / "validate_figure_spec.py")
load_module("figure_coverage", SCRIPTS / "figure_coverage.py")
backend = load_module("drawio_backend", SCRIPTS / "drawio_backend.py")
load_module("drawio_lint", SCRIPTS / "drawio_lint.py")
exporter = load_module("drawio_export", SCRIPTS / "drawio_export.py")


def prepare(root: Path) -> tuple[Path, Path]:
    plan_path = root / "F001.render-plan.json"
    plan = backend.create_render_plan_file(
        F001,
        plan_path,
        backend="drawio",
        strict=True,
    )
    source_path = backend.write_drawio_source(plan, root / "F001.drawio")
    return plan_path, source_path


def fake_command() -> str:
    return f'"{sys.executable}" "{FAKE_DRAWIO}"'


class DrawioExportTests(unittest.TestCase):
    def test_cli_export_records_hashes_dimensions_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, source_path = prepare(root)
            manifest_path = root / "F001.manifest.json"
            result = exporter.export_drawio(
                plan_path=plan_path,
                source_path=source_path,
                output_dir=root / "artifacts",
                formats=["svg", "pdf", "png"],
                drawio_command=fake_command(),
                manifest_path=manifest_path,
                strict_lint=True,
            )
            manifest_contract = runtime.validate_manifest_contract(result.manifest)
            artifacts = list(result.manifest["artifacts"])

        self.assertTrue(result.success)
        self.assertEqual([], manifest_contract)
        self.assertEqual("COMPLETED", result.manifest["status"])
        self.assertEqual({"svg", "pdf", "png"}, {item["format"] for item in artifacts})
        self.assertTrue(all(len(item["sha256"]) == 64 for item in artifacts))
        self.assertTrue(all(item["size_bytes"] > 0 for item in artifacts))
        self.assertTrue(all("dimensions" in item for item in artifacts))

    def test_missing_cli_writes_blocked_manifest_without_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, source_path = prepare(root)
            result = exporter.export_drawio(
                plan_path=plan_path,
                source_path=source_path,
                output_dir=root / "artifacts",
                formats=["svg"],
                drawio_command="/definitely/missing/drawio",
                manifest_path=root / "blocked.manifest.json",
                strict_lint=True,
            )
            codes = {item["code"] for item in result.manifest["issues"]}

        self.assertFalse(result.success)
        self.assertEqual("BLOCKED", result.manifest["status"])
        self.assertEqual([], result.manifest["artifacts"])
        self.assertIn("export.cli.missing", codes)

    def test_invalid_source_blocks_export_before_cli_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, source_path = prepare(root)
            source_path.write_text(
                '<mxfile compressed="true"><diagram>encoded</diagram></mxfile>',
                encoding="utf-8",
            )
            result = exporter.export_drawio(
                plan_path=plan_path,
                source_path=source_path,
                output_dir=root / "artifacts",
                formats=["svg"],
                drawio_command=fake_command(),
                manifest_path=root / "blocked.manifest.json",
                strict_lint=True,
            )
            codes = {item["code"] for item in result.manifest["issues"]}

        self.assertFalse(result.success)
        self.assertEqual([], result.manifest["metadata"]["invocations"])
        self.assertIn("drawio.format.compressed", codes)
        self.assertIn("export.source.lint_failed", codes)

    def test_unified_cli_export_uses_injected_test_double(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, source_path = prepare(root)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "figure.py"),
                    "export",
                    str(source_path),
                    "--plan",
                    str(plan_path),
                    "--output-dir",
                    str(root / "artifacts"),
                    "--format",
                    "svg",
                    "--drawio-command",
                    fake_command(),
                    "--manifest",
                    str(root / "manifest.json"),
                    "--strict-lint",
                    "--json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(completed.stdout)

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("COMPLETED", payload["manifest"]["status"])
        self.assertEqual("svg", payload["manifest"]["artifacts"][0]["format"])


if __name__ == "__main__":
    unittest.main()
