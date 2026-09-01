from __future__ import annotations

import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_ROOT / "scripts"
F001 = SKILL_ROOT / "examples" / "F001-evidence-traceable-reconstruction.md"
sys.path.insert(0, str(SCRIPTS))

import diagram_plan
import figure_source
import svg_backend
import svg_lint


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


class NativeSvgAuthoringTests(unittest.TestCase):
    def prepare(self, root: Path) -> tuple[dict, Path]:
        plan = diagram_plan.build_render_plan(
            F001, root / "F001.render-plan.json", backend="svg", strict=True
        )
        source = root / "F001.svg"
        svg_backend.write_svg_source(plan, source)
        return plan, source

    def test_f001_native_svg_passes_strict_lint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan, source = self.prepare(Path(tmp))
            report = svg_lint.lint_svg(source, plan=plan)
        self.assertTrue(svg_lint.lint_passed(report, strict=True), report.issues)

    def test_source_has_live_text_stable_ids_and_no_forbidden_elements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan, source = self.prepare(Path(tmp))
            root = ET.parse(source).getroot()
            names = {local_name(node.tag) for node in root.iter()}
            ids = {node.get("id") for node in root.iter() if node.get("id")}
        self.assertIn("text", names)
        self.assertIn("tspan", names)
        self.assertTrue({item["id"] for item in plan["elements"]}.issubset(ids))
        self.assertTrue({item["id"] for item in plan["connectors"]}.issubset(ids))
        self.assertTrue(
            names.isdisjoint({"image", "foreignObject", "script", "iframe", "video", "audio", "canvas"})
        )

    def test_candidate_stage_episode_are_true_nested_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan, source_path = self.prepare(Path(tmp))
            source = figure_source.normalize_source(source_path, backend="svg", plan=plan)
        self.assertEqual("el-candidate-epg", source["objects"]["cue-stage"]["parent_id"])
        self.assertEqual("cue-stage", source["objects"]["cue-episode"]["parent_id"])

    def test_nested_target_connector_renders_above_ancestor_fills(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, source = self.prepare(Path(tmp))
            root = ET.parse(source).getroot()
            children = list(root)
            element_layer = next(node for node in children if node.get("id") == "svg-elements")
            connector_layer = next(node for node in children if node.get("id") == "svg-connectors")
            provenance = next(
                node
                for node in connector_layer
                if node.get("id") == "edge-fixed-evidence-candidate-epg"
            )
        self.assertLess(children.index(element_layer), children.index(connector_layer))
        self.assertEqual("cue-episode", provenance.get("data-target"))
        self.assertEqual("url(#svg-arrowhead)", provenance.get("marker-end"))

    def test_provenance_connector_docks_on_source_and_target_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan, source = self.prepare(Path(tmp))
            root = ET.parse(source).getroot()
            connector = next(
                node
                for node in root.iter()
                if node.get("id") == "edge-fixed-evidence-candidate-epg"
            )
            points = [
                tuple(float(value) for value in token.split(","))
                for token in connector.get("points", "").split()
            ]
            normalized = figure_source.normalize_source(source, backend="svg", plan=plan)
            evidence = normalized["objects"]["el-fixed-evidence"]["absolute_geometry"]
            episode = normalized["objects"]["cue-episode"]["absolute_geometry"]

        def on_boundary(point, geometry) -> bool:
            x, y = point
            return (
                abs(x - geometry["x"]) < 1e-6
                or abs(x - (geometry["x"] + geometry["width"])) < 1e-6
                or abs(y - geometry["y"]) < 1e-6
                or abs(y - (geometry["y"] + geometry["height"])) < 1e-6
            )

        start_x, start_y = points[0]
        self.assertTrue(on_boundary((start_x, start_y), evidence))
        self.assertTrue(on_boundary(points[-1], episode))

    def test_safe_detour_stays_local_to_the_blocking_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, source = self.prepare(Path(tmp))
            root = ET.parse(source).getroot()
            connector = next(
                node
                for node in root.iter()
                if node.get("id") == "edge-candidate-epg-alignment"
            )
            points = [
                tuple(float(value) for value in token.split(","))
                for token in connector.get("points", "").split()
            ]
        self.assertEqual(4, len(points))
        self.assertGreaterEqual(min(point[0] for point in points), 600.0)

    def test_unobstructed_diagonal_connector_uses_orthogonal_l_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, source = self.prepare(Path(tmp))
            root = ET.parse(source).getroot()
            connector = next(
                node
                for node in root.iter()
                if node.get("id") == "edge-fixed-evidence-candidate-epg"
            )
            points = [
                tuple(float(value) for value in token.split(","))
                for token in connector.get("points", "").split()
            ]
        self.assertEqual(3, len(points))
        self.assertTrue(
            all(
                abs(start[0] - end[0]) < 1e-6
                or abs(start[1] - end[1]) < 1e-6
                for start, end in zip(points, points[1:])
            )
        )

    def test_provenance_label_uses_visible_route_segment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, source = self.prepare(Path(tmp))
            root = ET.parse(source).getroot()
            label = next(
                node
                for node in root.iter()
                if node.get("id") == "edge-fixed-evidence-candidate-epg__label"
            )
        self.assertGreater(float(label.get("x", "0")), 400.0)
        self.assertLess(float(label.get("x", "0")), 600.0)

    def test_same_plan_authors_deterministic_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, first = self.prepare(root)
            second = root / "F001-second.svg"
            svg_backend.write_svg_source(plan, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())


if __name__ == "__main__":
    unittest.main()
