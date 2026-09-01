from __future__ import annotations

import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_ROOT / "scripts"
F001 = SKILL_ROOT / "examples" / "F001-evidence-traceable-reconstruction.md"
SVG_NS = "http://www.w3.org/2000/svg"
sys.path.insert(0, str(SCRIPTS))

import diagram_plan
import svg_backend
import svg_lint


def tag(name: str) -> str:
    return f"{{{SVG_NS}}}{name}"


class SvgLintDefectTests(unittest.TestCase):
    def prepare(self, root: Path) -> tuple[dict, Path, ET.ElementTree]:
        plan = diagram_plan.build_render_plan(
            F001, root / "plan.json", backend="svg", strict=True
        )
        source = root / "figure.svg"
        svg_backend.write_svg_source(plan, source)
        return plan, source, ET.parse(source)

    def codes(self, source: Path, plan: dict) -> set[str]:
        return {item.code for item in svg_lint.lint_svg(source, plan=plan).issues}

    def save(self, tree: ET.ElementTree, source: Path) -> None:
        tree.write(source, encoding="utf-8", xml_declaration=True)

    def test_duplicate_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan, source, tree = self.prepare(Path(tmp))
            nodes = [node for node in tree.getroot().iter() if node.get("id")]
            nodes[-1].set("id", nodes[0].get("id", "duplicate"))
            self.save(tree, source)
            self.assertIn("svg.structure.duplicate_id", self.codes(source, plan))

    def test_broken_marker_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan, source, tree = self.prepare(Path(tmp))
            connector = next(node for node in tree.getroot().iter() if node.get("data-directed") == "true")
            connector.set("marker-end", "url(#missing-marker)")
            self.save(tree, source)
            self.assertIn("svg.reference.broken_marker", self.codes(source, plan))

    def test_external_image_embedded_raster_and_foreign_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan, source, tree = self.prepare(Path(tmp))
            root = tree.getroot()
            ET.SubElement(root, tag("image"), {"id": "remote-image", "href": "https://example.invalid/a.png"})
            ET.SubElement(root, tag("image"), {"id": "data-image", "href": "data:image/png;base64,AA=="})
            ET.SubElement(root, tag("foreignObject"), {"id": "foreign"})
            self.save(tree, source)
            codes = self.codes(source, plan)
        self.assertIn("svg.asset.external_uri", codes)
        self.assertIn("svg.asset.embedded_raster", codes)
        self.assertIn("svg.editability.forbidden_element", codes)

    def test_missing_required_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan, source, tree = self.prepare(Path(tmp))
            label = next(node for node in tree.getroot().iter() if node.get("id") == "el-fixed-evidence__label")
            for child in list(label):
                label.remove(child)
            label.text = None
            self.save(tree, source)
            self.assertIn("svg.text.plan_label_missing", self.codes(source, plan))

    def test_missing_required_relation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan, source, tree = self.prepare(Path(tmp))
            root = tree.getroot()
            parents = {child: parent for parent in root.iter() for child in parent}
            connector = next(node for node in root.iter() if node.get("id") == "edge-fixed-evidence-ai-reconstruction")
            parents[connector].remove(connector)
            self.save(tree, source)
            self.assertIn("svg.connector.object_missing", self.codes(source, plan))

    def test_missing_connector_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan, source, tree = self.prepare(Path(tmp))
            root = tree.getroot()
            parents = {child: parent for parent in root.iter() for child in parent}
            label = next(
                node
                for node in root.iter()
                if node.get("id") == "edge-fixed-evidence-candidate-epg__label"
            )
            parents[label].remove(label)
            self.save(tree, source)
            self.assertIn("svg.text.connector_label_missing", self.codes(source, plan))

    def test_relative_and_css_url_assets_are_external(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan, source, tree = self.prepare(Path(tmp))
            root = tree.getroot()
            ET.SubElement(root, tag("use"), {"id": "external-use", "href": "assets/icon.svg#x"})
            root.set("style", "fill: url(https://example.invalid/palette.svg#blue)")
            stylesheet = ET.SubElement(root, tag("style"), {"id": "remote-font"})
            stylesheet.text = "@font-face { src: url('https://example.invalid/font.woff2'); }"
            self.save(tree, source)
            codes = self.codes(source, plan)
        self.assertIn("svg.asset.external_uri", codes)

    def test_wrong_parent_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan, source, tree = self.prepare(Path(tmp))
            root = tree.getroot()
            parents = {child: parent for parent in root.iter() for child in parent}
            episode = next(node for node in root.iter() if node.get("id") == "cue-episode")
            element_layer = next(node for node in root.iter() if node.get("id") == "svg-elements")
            parents[episode].remove(episode)
            element_layer.append(episode)
            self.save(tree, source)
            self.assertIn("svg.structure.parent_mismatch", self.codes(source, plan))

    def test_outside_viewbox_and_undersized_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan, source, tree = self.prepare(Path(tmp))
            object_node = next(node for node in tree.getroot().iter() if node.get("id") == "el-fixed-evidence")
            object_node.set("transform", "translate(-200 -200)")
            label = next(node for node in tree.getroot().iter() if node.get("id") == "el-fixed-evidence__label")
            label.set("font-size", "1")
            self.save(tree, source)
            codes = self.codes(source, plan)
        self.assertIn("svg.geometry.outside_viewbox", codes)
        self.assertIn("svg.text.final_size_below_threshold", codes)

    def test_unplanned_directed_relation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan, source, tree = self.prepare(Path(tmp))
            layer = next(node for node in tree.getroot().iter() if node.get("id") == "svg-connectors")
            ET.SubElement(
                layer,
                tag("polyline"),
                {
                    "id": "rogue-relation",
                    "points": "10,10 20,10",
                    "data-object-kind": "connector",
                    "data-source": "el-fixed-evidence",
                    "data-target": "el-reference-epg",
                    "data-relation": "unsupported causal input",
                    "data-directed": "true",
                    "marker-end": "url(#svg-arrowhead)",
                },
            )
            self.save(tree, source)
            self.assertIn("svg.connector.unplanned", self.codes(source, plan))

    def test_arrow_without_connector_metadata_is_unplanned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan, source, tree = self.prepare(Path(tmp))
            layer = next(
                node
                for node in tree.getroot().iter()
                if node.get("id") == "svg-connectors"
            )
            ET.SubElement(
                layer,
                tag("line"),
                {
                    "id": "rogue-arrow",
                    "x1": "400",
                    "y1": "100",
                    "x2": "520",
                    "y2": "100",
                    "stroke": "#000000",
                    "marker-end": "url(#svg-arrowhead)",
                },
            )
            self.save(tree, source)
            self.assertIn("svg.connector.unplanned", self.codes(source, plan))


if __name__ == "__main__":
    unittest.main()
