from __future__ import annotations

import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_ROOT / "scripts"
F001 = SKILL_ROOT / "examples" / "F001-evidence-traceable-reconstruction.md"
TEMPLATE = SKILL_ROOT / "assets" / "figure-spec.template.md"
BENCHMARKS = SKILL_ROOT / "benchmarks"
SVG_NS = "http://www.w3.org/2000/svg"
sys.path.insert(0, str(SCRIPTS))

import diagram_plan
import drawio_backend
import figure_inspect
import figure_source
import figure_runtime
import svg_backend
import svg_export


def tag(name: str) -> str:
    return f"{{{SVG_NS}}}{name}"


class BackendParityTests(unittest.TestCase):
    def test_svg_execution_benchmark_contracts_are_present_and_parseable(self) -> None:
        expected = {
            "B05-svg-backend-parity.json": "B05",
            "B06-svg-hierarchy.json": "B06",
            "B07-svg-defects.json": "B07",
            "B08-svg-export.json": "B08",
        }
        observed = {
            name: json.loads((BENCHMARKS / name).read_text(encoding="utf-8"))[
                "benchmark_id"
            ]
            for name in expected
        }
        self.assertEqual(expected, observed)

    def test_f001_normalized_scientific_sources_are_equal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drawio_plan = diagram_plan.build_render_plan(
                F001, root / "drawio-plan.json", backend="drawio", strict=True
            )
            svg_plan = diagram_plan.build_render_plan(
                F001, root / "svg-plan.json", backend="svg", strict=True
            )
            drawio_source = root / "figure.drawio"
            svg_source = root / "figure.svg"
            drawio_backend.write_drawio_source(drawio_plan, drawio_source)
            svg_backend.write_svg_source(svg_plan, svg_source)
            normalized_drawio = figure_source.normalize_source(
                drawio_source, backend="drawio", plan=drawio_plan
            )
            normalized_svg = figure_source.normalize_source(
                svg_source, backend="svg", plan=svg_plan
            )
        self.assertEqual(
            figure_source.normalized_semantic_signature(normalized_drawio),
            figure_source.normalized_semantic_signature(normalized_svg),
        )
        self.assertEqual(drawio_plan["spec_coverage"], svg_plan["spec_coverage"])
        self.assertEqual(drawio_plan["semantic_assertions"], svg_plan["semantic_assertions"])

    def test_episode_contains_action_is_hierarchy_in_both_backends(self) -> None:
        template = TEMPLATE.read_text(encoding="utf-8")
        spec = template.replace('figure_id: "FXXX"', 'figure_id: "F777"')
        spec = spec.replace('working_title: ""', 'working_title: "Containment"')
        spec = spec.replace(
            "<!-- Required. One concise paragraph about the science, not the appearance. -->",
            "Show that an Episode structurally contains an Action.",
        )
        spec = spec.replace("-\n\n## 3.2 Exact", "- Episode\n- Action\n\n## 3.2 Exact", 1)
        spec = spec.replace(
            "-\n\n# 5. Figure Design",
            "- Episode contains Action.\n  Relation: containment / hierarchy.\n\n# 5. Figure Design",
            1,
        )
        spec = spec.replace(
            "- None specified\n\n## 6.3 Must Not Imply",
            "- Episode\n- Action\n\n## 6.3 Must Not Imply",
            1,
        )
        spec = spec.replace("**Required Outputs:**", "**Required Outputs:** SVG")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec_path = root / "F777-containment.md"
            spec_path.write_text(spec, encoding="utf-8")
            drawio_plan = diagram_plan.build_render_plan(
                spec_path, root / "drawio.json", backend="drawio"
            )
            svg_plan = diagram_plan.build_render_plan(
                spec_path, root / "svg.json", backend="svg"
            )
            drawio_path = root / "figure.drawio"
            svg_path = root / "figure.svg"
            drawio_backend.write_drawio_source(drawio_plan, drawio_path)
            svg_backend.write_svg_source(svg_plan, svg_path)
            drawio_model = figure_source.normalize_source(
                drawio_path, backend="drawio", plan=drawio_plan
            )
            svg_model = figure_source.normalize_source(svg_path, backend="svg", plan=svg_plan)
        episode_id = next(item["id"] for item in drawio_plan["elements"] if item["label"] == "Episode")
        action_id = next(item["id"] for item in drawio_plan["elements"] if item["label"] == "Action")
        self.assertEqual(episode_id, drawio_model["objects"][action_id]["parent_id"])
        self.assertEqual(episode_id, svg_model["objects"][action_id]["parent_id"])
        self.assertFalse(
            any(
                {item["source"], item["target"]} == {episode_id, action_id}
                for item in drawio_plan["connectors"]
            )
        )

    def prepare_inspection(self, root: Path) -> tuple[dict, Path, Path, Path]:
        plan_path = root / "plan.json"
        plan = diagram_plan.build_render_plan(F001, plan_path, backend="svg", strict=True)
        plan["outputs"]["formats"] = ["svg"]
        figure_runtime.write_json_atomic(plan_path, plan)
        source_path = root / plan["outputs"]["source"]
        svg_backend.write_svg_source(plan, source_path)
        manifest_path = root / "manifest.json"
        svg_export.export_svg(
            plan_path=plan_path,
            source_path=source_path,
            formats=["svg"],
            manifest_path=manifest_path,
            strict_lint=True,
        )
        return plan, plan_path, source_path, manifest_path

    def refresh_manifest(self, source_path: Path, manifest_path: Path) -> None:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        digest = figure_runtime.sha256_file(source_path)
        size = source_path.stat().st_size
        manifest["source"]["sha256"] = digest
        manifest["source"]["size_bytes"] = size
        for artifact in manifest["artifacts"]:
            if artifact["format"] == "svg":
                artifact["sha256"] = digest
                artifact["size_bytes"] = size
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    def inspect_mutation(self, mutator) -> set[str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, plan_path, source_path, manifest_path = self.prepare_inspection(root)
            tree = ET.parse(source_path)
            mutator(tree.getroot())
            tree.write(source_path, encoding="utf-8", xml_declaration=True)
            self.refresh_manifest(source_path, manifest_path)
            result = figure_inspect.inspect_figure(
                plan_path=plan_path,
                source_path=source_path,
                manifest_path=manifest_path,
                qa_path=root / "qa.json",
            )
            return {item["code"] for item in result.report["issues"]}

    def test_unplanned_label_is_blocking(self) -> None:
        def mutate(root: ET.Element) -> None:
            node = ET.SubElement(
                root,
                tag("text"),
                {"id": "rogue-label", "x": "20", "y": "20", "font-size": "17"},
            )
            node.text = "Unexpected mechanism"

        self.assertIn("semantic.unplanned_label.present", self.inspect_mutation(mutate))

    def test_unplanned_relation_is_blocking(self) -> None:
        def mutate(root: ET.Element) -> None:
            layer = next(node for node in root.iter() if node.get("id") == "svg-connectors")
            ET.SubElement(
                layer,
                tag("polyline"),
                {
                    "id": "rogue-relation",
                    "points": "10,10 20,10",
                    "data-object-kind": "connector",
                    "data-source": "el-reference-epg",
                    "data-target": "el-ai-reconstruction",
                    "data-relation": "unsupported input",
                    "data-directed": "true",
                    "marker-end": "url(#svg-arrowhead)",
                },
            )

        self.assertIn("semantic.unplanned_relation.present", self.inspect_mutation(mutate))

    def test_arrow_without_connector_metadata_is_blocking(self) -> None:
        def mutate(root: ET.Element) -> None:
            layer = next(node for node in root.iter() if node.get("id") == "svg-connectors")
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

        codes = self.inspect_mutation(mutate)
        self.assertIn("svg.connector.unplanned", codes)
        self.assertIn("semantic.unplanned_relation.present", codes)

    def test_unplanned_semantic_object_is_blocking(self) -> None:
        def mutate(root: ET.Element) -> None:
            layer = next(node for node in root.iter() if node.get("id") == "svg-elements")
            group = ET.SubElement(
                layer,
                tag("g"),
                {
                    "id": "rogue-object",
                    "transform": "translate(10 10)",
                    "data-object-kind": "element",
                    "data-element-kind": "node",
                    "data-semantic-role": "content",
                    "data-width": "20",
                    "data-height": "20",
                },
            )
            ET.SubElement(group, tag("rect"), {"width": "20", "height": "20"})

        self.assertIn(
            "semantic.unplanned_required_object.present",
            self.inspect_mutation(mutate),
        )

    def test_missing_connector_label_is_blocking_source_drift(self) -> None:
        def mutate(root: ET.Element) -> None:
            parents = {child: parent for parent in root.iter() for child in parent}
            label = next(
                node
                for node in root.iter()
                if node.get("id") == "edge-fixed-evidence-candidate-epg__label"
            )
            parents[label].remove(label)

        codes = self.inspect_mutation(mutate)
        self.assertIn("semantic.source.label_mismatch", codes)

    def test_explicit_technical_text_is_not_scientific_content(self) -> None:
        def mutate(root: ET.Element) -> None:
            node = ET.SubElement(
                root,
                tag("text"),
                {
                    "id": "technical-export-note",
                    "x": "10",
                    "y": "700",
                    "font-size": "7",
                    "data-text-role": "technical",
                },
            )
            node.text = "export metadata"

        self.assertNotIn(
            "semantic.unplanned_label.present",
            self.inspect_mutation(mutate),
        )


if __name__ == "__main__":
    unittest.main()
