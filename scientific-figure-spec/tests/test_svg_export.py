from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_ROOT / "scripts"
F001 = SKILL_ROOT / "examples" / "F001-evidence-traceable-reconstruction.md"
FAKE_RENDERER = SKILL_ROOT / "tests" / "fixtures" / "fake_svg_renderer.py"
sys.path.insert(0, str(SCRIPTS))

import diagram_plan
import artifact_utils
import svg_backend
import svg_export
from figure_runtime import package_version


def fake_command() -> str:
    return f'"{sys.executable}" "{FAKE_RENDERER}"'


class SvgExportTests(unittest.TestCase):
    def test_compressed_pdf_page_dimensions_are_readable(self) -> None:
        page = b"2 << /Type /Page /MediaBox [ 0 0 960 532.5 ] >>"
        compressed = zlib.compress(page)
        payload = (
            b"%PDF-1.7\n1 0 obj\n"
            b"<< /Type /ObjStm /Filter /FlateDecode >>\nstream\n"
            + compressed
            + b"\nendstream\nendobj\n%%EOF\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "compressed.pdf"
            path.write_bytes(payload)
            dimensions = artifact_utils.inspect_artifact_dimensions(path, "pdf")
        self.assertEqual(
            {"width": 960.0, "height": 532.5, "unit": "pt"},
            dimensions,
        )

    def prepare(self, root: Path) -> tuple[Path, Path]:
        plan_path = root / "F001.render-plan.json"
        plan = diagram_plan.create_render_plan_file(
            F001, plan_path, backend="svg", strict=True
        )
        source_path = root / plan["outputs"]["source"]
        svg_backend.write_svg_source(plan, source_path)
        return plan_path, source_path

    def test_svg_only_completes_without_external_renderer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, source = self.prepare(root)
            result = svg_export.export_svg(
                plan_path=plan,
                source_path=source,
                formats=["svg"],
                manifest_path=root / "manifest.json",
                strict_lint=True,
            )
        self.assertTrue(result.success)
        self.assertEqual("COMPLETED", result.manifest["status"])
        self.assertEqual(["svg"], [item["format"] for item in result.manifest["artifacts"]])
        self.assertEqual([], result.manifest["exporter"]["command"])
        self.assertEqual(
            f"scientific-figure-skills/{package_version()}",
            result.manifest["exporter"]["version"],
        )

    def test_png_request_blocks_when_explicit_renderer_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, source = self.prepare(root)
            result = svg_export.export_svg(
                plan_path=plan,
                source_path=source,
                formats=["png"],
                renderer_command="/definitely/missing/svg-renderer",
                manifest_path=root / "manifest.json",
            )
        self.assertEqual("BLOCKED", result.manifest["status"])
        self.assertIn(
            "capability.svg_renderer.missing",
            {item["code"] for item in result.manifest["issues"]},
        )

    def test_pdf_request_blocks_when_explicit_renderer_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, source = self.prepare(root)
            result = svg_export.export_svg(
                plan_path=plan,
                source_path=source,
                formats=["pdf"],
                renderer_command="/definitely/missing/svg-renderer",
                manifest_path=root / "manifest.json",
            )
        self.assertEqual("BLOCKED", result.manifest["status"])

    def test_mixed_request_is_partial_without_renderer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, source = self.prepare(root)
            result = svg_export.export_svg(
                plan_path=plan,
                source_path=source,
                formats=["svg", "png"],
                renderer_command="/definitely/missing/svg-renderer",
                manifest_path=root / "manifest.json",
            )
        self.assertEqual("PARTIAL", result.manifest["status"])
        self.assertEqual(["svg"], [item["format"] for item in result.manifest["artifacts"]])

    def test_explicit_test_renderer_records_producer_and_valid_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, source = self.prepare(root)
            result = svg_export.export_svg(
                plan_path=plan,
                source_path=source,
                output_dir=root / "artifacts",
                formats=["svg", "png", "pdf"],
                renderer_command=fake_command(),
                manifest_path=root / "manifest.json",
                strict_lint=True,
            )
            artifacts = {item["format"]: item for item in result.manifest["artifacts"]}
        self.assertTrue(result.success, result.manifest["issues"])
        self.assertEqual("svg", result.manifest["exporter"]["backend"])
        self.assertIn(str(FAKE_RENDERER), result.manifest["exporter"]["command"])
        self.assertEqual("svg-renderer test-double 0.1", result.manifest["exporter"]["version"])
        self.assertEqual({"svg", "png", "pdf"}, set(artifacts))
        self.assertTrue(all("dimensions" in item for item in artifacts.values()))

    def test_unified_svg_render_completes_end_to_end_with_test_renderer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "figure.py"),
                    "render",
                    str(F001),
                    "--backend",
                    "svg",
                    "--work-dir",
                    tmp,
                    "--svg-renderer-command",
                    fake_command(),
                    "--json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(completed.stdout)
            qa = json.loads(Path(payload["qa_path"]).read_text(encoding="utf-8"))
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertTrue(payload["success"])
        self.assertEqual("svg", payload["backend"])
        self.assertEqual("COMPLETED", payload["export_status"])
        self.assertEqual("AUTOMATED_CHECKS_PASSED", payload["qa_outcome"])
        self.assertEqual("AUTOMATED_EXECUTION", qa["assessment_scope"])
        self.assertEqual("NOT_PERFORMED", qa["human_review_status"])


if __name__ == "__main__":
    unittest.main()
