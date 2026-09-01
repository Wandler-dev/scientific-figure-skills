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
linter = load_module("drawio_lint", SCRIPTS / "drawio_lint.py")
repair = load_module("drawio_repair", SCRIPTS / "drawio_repair.py")


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


class DrawioRepairTests(unittest.TestCase):
    def test_plan_bounded_repairs_preserve_input_and_clear_lint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, source_path = prepare(root)
            original_hash = runtime.sha256_file(source_path)
            document = ET.parse(source_path)
            graph_root = document.getroot().find("./diagram/mxGraphModel/root")
            assert graph_root is not None
            reference = graph_root.find("mxCell[@id='el-reference-epg']")
            edge = graph_root.find("mxCell[@id='edge-fixed-evidence-ai-reconstruction']")
            assert reference is not None and edge is not None
            reference.set(
                "style",
                (reference.get("style") or "").replace("whiteSpace=wrap;", ""),
            )
            geometry = reference.find("mxGeometry")
            assert geometry is not None
            geometry.set("x", "-40")
            edge.set("target", "missing")
            forbidden = ET.SubElement(
                graph_root,
                "mxCell",
                {
                    "id": "edge-forbidden-reference-leakage",
                    "value": "",
                    "style": "edgeStyle=orthogonalEdgeStyle;html=1;endArrow=block;",
                    "edge": "1",
                    "parent": "1",
                    "source": "el-reference-epg",
                    "target": "el-ai-reconstruction",
                    "data-directed": "true",
                },
            )
            ET.SubElement(forbidden, "mxGeometry", {"relative": "1", "as": "geometry"})
            document.write(source_path, encoding="utf-8", xml_declaration=True)
            corrupted_hash = runtime.sha256_file(source_path)
            output = root / "F001.repaired.drawio"
            result = repair.repair_drawio(
                source_path=source_path,
                output_path=output,
                plan_path=plan_path,
            )
            action_codes = {item["code"] for item in result.actions}
            output_document = ET.parse(output)
            output_root = output_document.getroot().find("./diagram/mxGraphModel/root")
            assert output_root is not None
            preserved_hash = runtime.sha256_file(source_path)
            forbidden_absent = (
                output_root.find("mxCell[@id='edge-forbidden-reference-leakage']")
                is None
            )

        self.assertNotEqual(original_hash, corrupted_hash)
        self.assertEqual(corrupted_hash, preserved_hash)
        self.assertTrue(result.safe_complete)
        self.assertEqual([], result.after.errors)
        self.assertEqual([], result.after.warnings)
        self.assertIn("repair.style.wrap_added", action_codes)
        self.assertIn("repair.geometry.restored_from_plan", action_codes)
        self.assertIn("repair.connector.restored_from_plan", action_codes)
        self.assertIn("repair.forbidden_relation.removed", action_codes)
        self.assertTrue(forbidden_absent)

    def test_nonempty_label_conflict_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, source_path = prepare(root)
            document = ET.parse(source_path)
            candidate = document.getroot().find(
                "./diagram/mxGraphModel/root/mxCell[@id='el-candidate-epg']"
            )
            assert candidate is not None
            candidate.set("value", "Different Scientific Label")
            document.write(source_path, encoding="utf-8", xml_declaration=True)
            output = root / "F001.repaired.drawio"
            result = repair.repair_drawio(
                source_path=source_path,
                output_path=output,
                plan_path=plan_path,
            )
            repaired_candidate = ET.parse(output).getroot().find(
                "./diagram/mxGraphModel/root/mxCell[@id='el-candidate-epg']"
            )
            skip_codes = {item["code"] for item in result.skipped}

        self.assertFalse(result.safe_complete)
        self.assertIn("repair.skipped.label_conflict", skip_codes)
        self.assertEqual("Different Scientific Label", repaired_candidate.get("value"))

    def test_embedded_raster_is_reported_but_not_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, source_path = prepare(root)
            document = ET.parse(source_path)
            evidence = document.getroot().find(
                "./diagram/mxGraphModel/root/mxCell[@id='el-fixed-evidence']"
            )
            assert evidence is not None
            evidence.set("style", (evidence.get("style") or "") + "image=data:image/png;base64,AA;")
            document.write(source_path, encoding="utf-8", xml_declaration=True)
            output = root / "F001.repaired.drawio"
            result = repair.repair_drawio(
                source_path=source_path,
                output_path=output,
                plan_path=plan_path,
            )
            skip_codes = {item["code"] for item in result.skipped}
            output_evidence = ET.parse(output).getroot().find(
                "./diagram/mxGraphModel/root/mxCell[@id='el-fixed-evidence']"
            )

        self.assertFalse(result.safe_complete)
        self.assertIn("repair.skipped.unsafe_raster", skip_codes)
        self.assertIn("image=data:image/png", output_evidence.get("style") or "")

    def test_dry_run_writes_nothing_and_in_place_is_forbidden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, source_path = prepare(root)
            original_hash = runtime.sha256_file(source_path)
            result = repair.repair_drawio(
                source_path=source_path,
                output_path=None,
                plan_path=plan_path,
                dry_run=True,
            )
            self.assertEqual(original_hash, runtime.sha256_file(source_path))
            self.assertIsNone(result.output)
            with self.assertRaises(repair.DrawioRepairError):
                repair.repair_drawio(
                    source_path=source_path,
                    output_path=source_path,
                    plan_path=plan_path,
                )

    def test_unified_cli_repair_emits_json_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, source_path = prepare(root)
            document = ET.parse(source_path)
            reference = document.getroot().find(
                "./diagram/mxGraphModel/root/mxCell[@id='el-reference-epg']"
            )
            assert reference is not None
            reference.set(
                "style",
                (reference.get("style") or "").replace("whiteSpace=wrap;", ""),
            )
            document.write(source_path, encoding="utf-8", xml_declaration=True)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "figure.py"),
                    "repair",
                    str(source_path),
                    "--plan",
                    str(plan_path),
                    "--output",
                    str(root / "repaired.drawio"),
                    "--json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(completed.stdout)

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertTrue(payload["safe_complete"])
        self.assertTrue(payload["changed"])


if __name__ == "__main__":
    unittest.main()
