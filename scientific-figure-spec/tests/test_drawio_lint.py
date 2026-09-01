from __future__ import annotations

import copy
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
validator = load_module("validate_figure_spec", SCRIPTS / "validate_figure_spec.py")
load_module("figure_coverage", SCRIPTS / "figure_coverage.py")
backend = load_module("drawio_backend", SCRIPTS / "drawio_backend.py")
linter = load_module("drawio_lint", SCRIPTS / "drawio_lint.py")


def authored_f001(root: Path) -> Path:
    plan = backend.build_render_plan(
        F001,
        root / "plan.json",
        backend="drawio",
        strict=True,
    )
    return backend.write_drawio_source(plan, root / "F001.drawio")


class DrawioLintTests(unittest.TestCase):
    def test_authored_f001_has_zero_structural_or_geometry_issues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = linter.lint_drawio(authored_f001(Path(tmp)))
        self.assertEqual([], report.errors)
        self.assertEqual([], report.warnings)

    def test_compressed_drawio_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "compressed.drawio"
            path.write_text(
                '<mxfile compressed="true"><diagram id="p">encoded</diagram></mxfile>',
                encoding="utf-8",
            )
            report = linter.lint_drawio(path)
        codes = {item.code for item in report.errors}
        self.assertIn("drawio.format.compressed", codes)
        self.assertIn("drawio.structure.graph_model_missing", codes)

    def test_lint_detects_identity_endpoint_geometry_and_raster_defects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = authored_f001(root)
            document = ET.parse(path)
            graph_root = document.getroot().find("./diagram/mxGraphModel/root")
            self.assertIsNotNone(graph_root)
            assert graph_root is not None

            candidate = graph_root.find("mxCell[@id='el-candidate-epg']")
            reference = graph_root.find("mxCell[@id='el-reference-epg']")
            edge = next(cell for cell in graph_root.findall("mxCell") if cell.get("edge") == "1")
            self.assertIsNotNone(candidate)
            self.assertIsNotNone(reference)
            assert candidate is not None and reference is not None

            duplicate = copy.deepcopy(candidate)
            graph_root.append(duplicate)
            edge.set("target", "missing-endpoint")
            candidate.set("style", (candidate.get("style") or "") + "image=data:image/png;base64,AA;")
            candidate_geometry = candidate.find("mxGeometry")
            reference_geometry = reference.find("mxGeometry")
            assert candidate_geometry is not None and reference_geometry is not None
            reference_geometry.set("x", candidate_geometry.get("x") or "0")
            reference_geometry.set("y", candidate_geometry.get("y") or "0")
            candidate_geometry.set("width", "0")
            document.write(path, encoding="utf-8", xml_declaration=True)

            report = linter.lint_drawio(path)

        codes = {item.code for item in report.issues}
        self.assertIn("drawio.structure.id_duplicate", codes)
        self.assertIn("drawio.connector.endpoint_unknown", codes)
        self.assertIn("drawio.geometry.nonpositive", codes)
        self.assertIn("drawio.editability.embedded_raster", codes)

    def test_lint_detects_out_of_bounds_and_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = authored_f001(root)
            document = ET.parse(path)
            graph_root = document.getroot().find("./diagram/mxGraphModel/root")
            assert graph_root is not None
            candidate = graph_root.find("mxCell[@id='el-candidate-epg']/mxGeometry")
            reference = graph_root.find("mxCell[@id='el-reference-epg']/mxGeometry")
            assert candidate is not None and reference is not None
            candidate.set("x", "-20")
            reference.set("x", "-20")
            reference.set("y", candidate.get("y") or "0")
            document.write(path, encoding="utf-8", xml_declaration=True)
            report = linter.lint_drawio(path)

        codes = {item.code for item in report.issues}
        self.assertIn("drawio.geometry.out_of_bounds", codes)
        self.assertIn("drawio.geometry.overlap", codes)

    def test_unified_cli_lint_supports_strict_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = authored_f001(Path(tmp))
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "figure.py"),
                    "lint",
                    str(path),
                    "--strict",
                    "--json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        result = json.loads(completed.stdout)
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertTrue(result["passed"])
        self.assertEqual(0, result["summary"]["errors"])
        self.assertEqual(0, result["summary"]["warnings"])


if __name__ == "__main__":
    unittest.main()
