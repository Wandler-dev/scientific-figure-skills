from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_ROOT / "scripts"
F001 = SKILL_ROOT / "examples" / "F001-evidence-traceable-reconstruction.md"
sys.path.insert(0, str(SCRIPTS))

import diagram_plan
import drawio_backend


SCIENTIFIC_FIELDS = (
    "figure_spec",
    "spec_coverage",
    "canvas",
    "final_size",
    "theme",
    "elements",
    "connectors",
    "semantic_assertions",
)


class SharedDiagramPlanTests(unittest.TestCase):
    def test_drawio_compatibility_wrapper_is_exact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "F001.render-plan.json"
            shared = diagram_plan.build_render_plan(F001, path, backend="drawio", strict=True)
            compatibility = drawio_backend.build_render_plan(
                F001, path, backend="drawio", strict=True
            )
        self.assertEqual(shared, compatibility)

    def test_drawio_and_svg_plans_share_scientific_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drawio = diagram_plan.build_render_plan(
                F001, root / "drawio.json", backend="drawio", strict=True
            )
            svg = diagram_plan.build_render_plan(
                F001, root / "svg.json", backend="svg", strict=True
            )
        for field in SCIENTIFIC_FIELDS:
            if field == "figure_spec":
                self.assertEqual(
                    {key: value for key, value in drawio[field].items() if key != "path"},
                    {key: value for key, value in svg[field].items() if key != "path"},
                )
            else:
                self.assertEqual(drawio[field], svg[field], field)
        self.assertEqual(".drawio", Path(drawio["outputs"]["source"]).suffix)
        self.assertEqual(".svg", Path(svg["outputs"]["source"]).suffix)

    def test_f001_coverage_remains_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = diagram_plan.build_render_plan(
                F001, Path(tmp) / "plan.json", backend="svg", strict=True
            )
        summary = plan["spec_coverage"]["summary"]
        self.assertEqual("COMPLETE", plan["spec_coverage"]["status"])
        self.assertEqual(7, summary["must_show_mapped"])
        self.assertEqual(6, summary["relationships_mapped"])
        self.assertEqual(0, summary["unresolved_total"])

    def test_shared_planner_contains_no_backend_markup(self) -> None:
        source = (SCRIPTS / "diagram_plan.py").read_text(encoding="utf-8")
        for backend_token in ("mxCell", "mxGraphModel", "SVG marker", "<svg"):
            self.assertNotIn(backend_token, source)


if __name__ == "__main__":
    unittest.main()
