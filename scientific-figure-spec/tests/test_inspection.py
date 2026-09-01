from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
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
inspector = load_module("figure_inspect", SCRIPTS / "figure_inspect.py")


def fake_command() -> str:
    return f'"{sys.executable}" "{FAKE_DRAWIO}"'


def prepare_plan_source(root: Path) -> tuple[Path, dict, Path]:
    plan_path = root / "F001.render-plan.json"
    plan = backend.create_render_plan_file(
        F001,
        plan_path,
        backend="drawio",
        strict=True,
    )
    source_path = backend.write_drawio_source(plan, root / "F001.drawio")
    return plan_path, plan, source_path


def export_all(root: Path, plan_path: Path, source_path: Path) -> Path:
    manifest_path = root / "F001.manifest.json"
    result = exporter.export_drawio(
        plan_path=plan_path,
        source_path=source_path,
        output_dir=root / "artifacts",
        drawio_command=fake_command(),
        manifest_path=manifest_path,
        strict_lint=True,
    )
    if not result.success:
        raise AssertionError(result.manifest)
    return manifest_path


class FigureInspectionTests(unittest.TestCase):
    def test_f001_full_artifact_inspection_passes_without_ocr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, _, source_path = prepare_plan_source(root)
            manifest_path = export_all(root, plan_path, source_path)
            result = inspector.inspect_figure(
                plan_path=plan_path,
                source_path=source_path,
                manifest_path=manifest_path,
                qa_path=root / "F001.qa.json",
            )
            contract = runtime.validate_qa_contract(result.report)

        self.assertTrue(result.passed)
        self.assertEqual("AUTOMATED_CHECKS_PASSED", result.report["outcome"])
        self.assertEqual("AUTOMATED_EXECUTION", result.report["assessment_scope"])
        self.assertEqual("NOT_PERFORMED", result.report["human_review_status"])
        self.assertEqual([], result.report["issues"])
        self.assertEqual([], contract)
        self.assertFalse(result.report["metadata"]["ocr_used"])

    def test_forbidden_reference_leakage_blocks_semantic_qa(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, _, source_path = prepare_plan_source(root)
            document = ET.parse(source_path)
            graph_root = document.getroot().find("./diagram/mxGraphModel/root")
            assert graph_root is not None
            edge = ET.SubElement(
                graph_root,
                "mxCell",
                {
                    "id": "edge-forbidden-reference-leakage",
                    "value": "",
                    "style": "edgeStyle=orthogonalEdgeStyle;html=1;endArrow=block;endFill=1;",
                    "edge": "1",
                    "parent": "1",
                    "source": "el-reference-epg",
                    "target": "el-ai-reconstruction",
                    "data-relation": "information access",
                    "data-directed": "true",
                },
            )
            ET.SubElement(edge, "mxGeometry", {"relative": "1", "as": "geometry"})
            document.write(source_path, encoding="utf-8", xml_declaration=True)
            manifest_path = export_all(root, plan_path, source_path)
            result = inspector.inspect_figure(
                plan_path=plan_path,
                source_path=source_path,
                manifest_path=manifest_path,
                qa_path=root / "F001.qa.json",
            )
            codes = {item["code"] for item in result.report["issues"]}

        self.assertEqual("BLOCKED", result.report["outcome"])
        self.assertIn("semantic.forbidden_relation.present", codes)

    def test_final_size_inspection_reports_too_small_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan, _ = prepare_plan_source(root)
            for element in plan["elements"]:
                if element["id"] == "el-fixed-evidence":
                    element["style_tokens"]["font_size_px"] = 5
            runtime.write_json_atomic(plan_path, plan, overwrite=True)
            source_path = backend.write_drawio_source(
                plan,
                root / "F001.drawio",
                overwrite=True,
            )
            manifest_path = export_all(root, plan_path, source_path)
            result = inspector.inspect_figure(
                plan_path=plan_path,
                source_path=source_path,
                manifest_path=manifest_path,
                qa_path=root / "F001.qa.json",
            )
            codes = {item["code"] for item in result.report["issues"]}

        self.assertEqual("REVISION_REQUIRED", result.report["outcome"])
        self.assertIn("visual.text.too_small", codes)

    def test_artifact_hash_mismatch_is_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, _, source_path = prepare_plan_source(root)
            manifest_path = export_all(root, plan_path, source_path)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            svg_record = next(item for item in manifest["artifacts"] if item["format"] == "svg")
            svg_path = (manifest_path.parent / svg_record["path"]).resolve()
            with svg_path.open("ab") as handle:
                handle.write(b"\n")
            result = inspector.inspect_figure(
                plan_path=plan_path,
                source_path=source_path,
                manifest_path=manifest_path,
                qa_path=root / "F001.qa.json",
            )
            codes = {item["code"] for item in result.report["issues"]}

        self.assertEqual("BLOCKED", result.report["outcome"])
        self.assertIn("technical.artifact.hash_mismatch", codes)

    def test_unified_cli_inspect_emits_machine_readable_qa(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, _, source_path = prepare_plan_source(root)
            manifest_path = export_all(root, plan_path, source_path)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "figure.py"),
                    "inspect",
                    str(source_path),
                    "--plan",
                    str(plan_path),
                    "--manifest",
                    str(manifest_path),
                    "--qa",
                    str(root / "F001.qa.json"),
                    "--json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(completed.stdout)

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("AUTOMATED_CHECKS_PASSED", payload["report"]["outcome"])


if __name__ == "__main__":
    unittest.main()
