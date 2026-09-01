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
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if "figure_runtime" not in sys.modules:
    load_module("figure_runtime", SCRIPTS / "figure_runtime.py")
if "validate_figure_spec" not in sys.modules:
    load_module("validate_figure_spec", SCRIPTS / "validate_figure_spec.py")
if "figure_coverage" not in sys.modules:
    load_module("figure_coverage", SCRIPTS / "figure_coverage.py")
drawio = load_module("drawio_backend", SCRIPTS / "drawio_backend.py")
runtime = sys.modules["figure_runtime"]


class DrawioAuthoringTests(unittest.TestCase):
    def test_f001_generates_valid_opt_in_render_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "F001.render-plan.json"
            plan = drawio.build_render_plan(
                F001,
                plan_path,
                backend="drawio",
                strict=True,
            )

        self.assertEqual("1.0", plan["figure_spec"]["spec_version"])
        self.assertEqual("drawio", plan["backend"])
        self.assertEqual(
            "scientific-figure-skills",
            plan["metadata"]["generated_by"],
        )
        self.assertTrue(plan["metadata"]["selected_backend_is_explicit"])
        self.assertEqual([], runtime.validate_render_plan_contract(plan))
        labels = {element["label"] for element in plan["elements"]}
        self.assertIn("Candidate EPG", labels)
        self.assertIn("Reference EPG", labels)
        self.assertIn("Evidence Fidelity", labels)
        self.assertIn("Alignment / Comparison", labels)
        self.assertIn("Fidelity Diagnostics", labels)
        assertion_ids = {item["id"] for item in plan["semantic_assertions"]}
        self.assertIn("assert-no-reference-leakage", assertion_ids)

    def test_authoring_emits_native_uncompressed_editable_xml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = drawio.build_render_plan(
                F001,
                root / "plan.json",
                backend="drawio",
                strict=True,
            )
            output = drawio.write_drawio_source(plan, root / "F001.drawio")
            document = ET.parse(output)

        mxfile = document.getroot()
        self.assertEqual("mxfile", mxfile.tag)
        self.assertEqual("scientific-figure-skills", mxfile.get("agent"))
        self.assertEqual("false", mxfile.get("compressed"))
        diagram = mxfile.find("diagram")
        self.assertIsNotNone(diagram)
        model = diagram.find("mxGraphModel") if diagram is not None else None
        self.assertIsNotNone(model)
        cells = model.findall("./root/mxCell") if model is not None else []
        ids = [cell.get("id") for cell in cells]
        self.assertEqual(len(ids), len(set(ids)))
        vertices = [cell for cell in cells if cell.get("vertex") == "1"]
        self.assertTrue(vertices)
        self.assertTrue(all(cell.find("mxGeometry") is not None for cell in vertices))
        self.assertIn("Candidate EPG", {cell.get("value") for cell in vertices})
        self.assertFalse(any("image=" in (cell.get("style") or "") for cell in cells))

    def test_authoring_is_byte_deterministic_for_one_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = drawio.build_render_plan(
                F001,
                root / "plan.json",
                backend="drawio",
                strict=True,
            )
            first = drawio.drawio_bytes(plan)
            second = drawio.drawio_bytes(plan)
        self.assertEqual(first, second)

    def test_unified_cli_plans_and_authors_without_external_drawio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "F001.render-plan.json"
            source_path = root / "F001.drawio"
            plan_result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "figure.py"),
                    "plan",
                    str(F001),
                    "--backend",
                    "drawio",
                    "--strict",
                    "--output",
                    str(plan_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            author_result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "figure.py"),
                    "author",
                    str(plan_path),
                    "--output",
                    str(source_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            plan_data = json.loads(plan_path.read_text(encoding="utf-8"))

        self.assertEqual(0, plan_result.returncode, plan_result.stderr)
        self.assertEqual(0, author_result.returncode, author_result.stderr)
        self.assertEqual("drawio", plan_data["backend"])


if __name__ == "__main__":
    unittest.main()
