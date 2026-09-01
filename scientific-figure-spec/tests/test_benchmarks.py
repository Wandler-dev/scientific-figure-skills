from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_ROOT / "scripts"
BENCHMARKS = SKILL_ROOT / "benchmarks"
FIXTURE_SPEC = BENCHMARKS / "F901-execution-coverage-harness.md"
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
repairer = load_module("drawio_repair", SCRIPTS / "drawio_repair.py")


SCENARIOS = {
    "B01": BENCHMARKS / "B01-simple-workflow.json",
    "B02": BENCHMARKS / "B02-reference-isolation.json",
    "B03": BENCHMARKS / "B03-geometry-repair.json",
    "B04": BENCHMARKS / "B04-final-size.json",
}

ROLE_COLORS = {
    "evidence": ("#FFF5D9", "#C28A24"),
    "system": ("#E5F6F3", "#2C8A7D"),
    "candidate": ("#E7F0FF", "#2F6FB6"),
    "reference": ("#F1EAFE", "#7655A6"),
    "diagnostic": ("#F4F7FB", "#7890A8"),
    "content": ("#FFFFFF", "#6B7F93"),
}


def fake_command() -> str:
    return f'"{sys.executable}" "{FAKE_DRAWIO}"'


def read_scenario(benchmark_id: str) -> dict:
    return json.loads(SCENARIOS[benchmark_id].read_text(encoding="utf-8"))


def build_plan(scenario: dict, plan_path: Path) -> dict:
    elements = []
    assertions = []
    for item in scenario["elements"]:
        fill, stroke = ROLE_COLORS[item["role"]]
        elements.append(
            {
                "id": item["id"],
                "kind": "diagnostic" if item["role"] == "diagnostic" else "node",
                "label": item["label"],
                "semantic_role": item["role"],
                "parent_id": None,
                "representation_origin": "SPEC_CONTENT",
                "geometry": {
                    "x": item["x"],
                    "y": item["y"],
                    "width": item["width"],
                    "height": item["height"],
                },
                "style_tokens": {
                    "fill": fill,
                    "stroke": stroke,
                    "font_color": "#17324D",
                    "font_size_px": item["font_size_px"],
                    "bold": item["role"] in {"system", "candidate", "reference"},
                    "rounded": True,
                    "align": "center",
                    "vertical_align": "middle",
                },
                "source_ref": "F900 benchmark fixture",
            }
        )
        assertions.append(
            {
                "id": f"assert-label-{item['id']}",
                "kind": "required_label",
                "severity": "BLOCKING",
                "params": {"element_id": item["id"], "label": item["label"]},
                "why": "The benchmark label is plan-bound.",
            }
        )
        if item["role"] in {"evidence", "candidate", "reference"}:
            assertions.append(
                {
                    "id": f"assert-color-{item['id']}",
                    "kind": "role_color",
                    "severity": "MAJOR",
                    "params": {
                        "element_id": item["id"],
                        "expected_fill": fill,
                        "expected_stroke": stroke,
                    },
                    "why": "The benchmark semantic color is plan-bound.",
                }
            )

    connectors = []
    for item in scenario["connectors"]:
        connectors.append(
            {
                "id": item["id"],
                "source": item["source"],
                "target": item["target"],
                "relation": item["relation"],
                "directed": item["directed"],
                "label": "",
                "representation_origin": "SPEC_RELATIONSHIP",
                "source_ref": "4.1 Relationships[1]",
                "style_tokens": {
                    "stroke": "#6B7F93",
                    "font_color": "#607286",
                    "font_size_px": 13,
                    "dashed": not item["directed"],
                },
            }
        )
        assertions.append(
            {
                "id": f"assert-relation-{item['id']}",
                "kind": "required_relation",
                "severity": "BLOCKING",
                "params": {
                    "source": item["source"],
                    "target": item["target"],
                    "directed": item["directed"],
                    "relation": item["relation"],
                },
                "why": "The benchmark relation is plan-bound.",
            }
        )
    for item in scenario["forbidden_relations"]:
        assertions.append(
            {
                "id": f"assert-forbidden-{item['id']}",
                "kind": "forbidden_relation",
                "severity": "BLOCKING",
                "params": {
                    "source": item["source"],
                    "target": item["target"],
                    "directed": item["directed"],
                },
                "why": "Reference must remain outside the AI System input path.",
            }
        )
    assertions.extend(
        [
            {
                "id": "assert-no-raster",
                "kind": "no_embedded_raster",
                "severity": "BLOCKING",
                "params": {},
                "why": "The source must remain natively editable.",
            },
            {
                "id": "assert-within-canvas",
                "kind": "within_canvas",
                "severity": "MAJOR",
                "params": {},
                "why": "Required cells must not be clipped.",
            },
            {
                "id": "assert-minimum-text-size",
                "kind": "minimum_text_size",
                "severity": "MAJOR",
                "params": {},
                "why": "Required labels must remain readable.",
            },
        ]
    )
    benchmark_id = scenario["benchmark_id"]
    plan = {
        "schema_version": "1.1",
        "plan_id": f"{benchmark_id}-drawio-v1",
        "backend": "drawio",
        "figure_spec": {
            "path": os.path.relpath(FIXTURE_SPEC, plan_path.parent),
            "sha256": runtime.sha256_file(FIXTURE_SPEC),
            "spec_version": "1.0",
            "figure_id": "F901",
        },
        "spec_coverage": {
            "status": "COMPLETE",
            "must_show": [
                {
                    "id": "must-show-001",
                    "source_ref": "3.1 Must Show[1]",
                    "source_text": "The active scenario's declared plan-owned elements.",
                    "status": "MAPPED",
                    "representations": [
                        {"kind": "element", "ids": [item["id"]]}
                        for item in elements
                    ],
                },
                {
                    "id": "must-show-002",
                    "source_ref": "3.1 Must Show[2]",
                    "source_text": "The active scenario's declared plan-owned relationships.",
                    "status": "MAPPED",
                    "representations": [
                        {"kind": "connector", "ids": [item["id"]]}
                        for item in connectors
                    ],
                },
                {
                    "id": "must-show-003",
                    "source_ref": "3.1 Must Show[3]",
                    "source_text": "Editable geometry and labels readable at the declared final size.",
                    "status": "MAPPED",
                    "representations": [
                        {"kind": "element", "ids": [item["id"]]}
                        for item in elements
                    ],
                },
            ],
            "relationships": [
                {
                    "id": "relationship-001",
                    "source_ref": "4.1 Relationships[1]",
                    "source_text": "The active scenario relationships remain attached to their declared endpoints. Relation: scenario-owned execution relation.",
                    "relation_type": "flow",
                    "status": "MAPPED",
                    "representations": [
                        {"kind": "connector", "ids": [item["id"]]}
                        for item in connectors
                    ],
                }
            ],
            "summary": {
                "must_show_total": 3,
                "must_show_mapped": 3,
                "relationships_total": 1,
                "relationships_mapped": 1,
                "unresolved_total": 0,
            },
        },
        "canvas": {
            **scenario["canvas"],
            "unit": "px",
            "margin": 24,
            "background": "#FFFFFF",
        },
        "final_size": scenario["final_size"],
        "theme": {
            "font_family": "Arial",
            "font_size_px": 18,
            "title_font_size_px": 21,
            "line_width_px": 2,
            "palette": {"ink": "#17324D", "paper": "#FFFFFF"},
        },
        "elements": elements,
        "connectors": connectors,
        "semantic_assertions": assertions,
        "outputs": {
            "source": f"{benchmark_id}.drawio",
            "formats": scenario["formats"],
            "manifest": f"{benchmark_id}.manifest.json",
            "qa_report": f"{benchmark_id}.qa.json",
        },
        "metadata": {
            "benchmark_id": benchmark_id,
            "generated_by": "B01-B04 integration test",
            "selected_backend_is_explicit": True,
        },
    }
    contract = runtime.validate_render_plan_contract(plan)
    if contract:
        raise AssertionError([item.as_dict() for item in contract])
    runtime.write_json_atomic(plan_path, plan)
    return plan


def execute_baseline(root: Path, scenario: dict) -> tuple[dict, Path, Path, Path, dict]:
    plan_path = root / f"{scenario['benchmark_id']}.render-plan.json"
    plan = build_plan(scenario, plan_path)
    source_path = backend.write_drawio_source(plan, root / plan["outputs"]["source"])
    manifest_path = root / plan["outputs"]["manifest"]
    export_result = exporter.export_drawio(
        plan_path=plan_path,
        source_path=source_path,
        output_dir=root / "artifacts",
        drawio_command=fake_command(),
        manifest_path=manifest_path,
        strict_lint=True,
    )
    if not export_result.success:
        raise AssertionError(export_result.manifest)
    qa_result = inspector.inspect_figure(
        plan_path=plan_path,
        source_path=source_path,
        manifest_path=manifest_path,
        qa_path=root / plan["outputs"]["qa_report"],
    )
    return plan, plan_path, source_path, manifest_path, qa_result.report


class DrawioBenchmarkTests(unittest.TestCase):
    def test_all_four_benchmark_descriptors_are_versioned_and_unique(self) -> None:
        scenarios = [read_scenario(item) for item in SCENARIOS]
        self.assertEqual({"B01", "B02", "B03", "B04"}, {item["benchmark_id"] for item in scenarios})
        self.assertTrue(all(item["benchmark_version"] == "1.0" for item in scenarios))

    def test_b01_minimal_workflow_passes_complete_loop(self) -> None:
        scenario = read_scenario("B01")
        with tempfile.TemporaryDirectory() as tmp:
            _, _, _, _, report = execute_baseline(Path(tmp), scenario)
        self.assertEqual(scenario["expected"]["baseline_outcome"], report["outcome"])
        self.assertEqual([], report["issues"])

    def test_b02_reference_leakage_is_blocked(self) -> None:
        scenario = read_scenario("B02")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline"
            mutated = root / "mutated"
            _, _, _, _, baseline_report = execute_baseline(baseline, scenario)
            plan, plan_path, source_path, _, _ = execute_baseline(mutated, scenario)
            # Remove the first run outputs before re-exporting the mutation.
            for path in (mutated / plan["outputs"]["manifest"], mutated / plan["outputs"]["qa_report"]):
                path.unlink()
            for path in (mutated / "artifacts").iterdir():
                path.unlink()
            document = ET.parse(source_path)
            graph_root = document.getroot().find("./diagram/mxGraphModel/root")
            assert graph_root is not None
            edge = ET.SubElement(
                graph_root,
                "mxCell",
                {
                    "id": "forbidden-reference-system",
                    "value": "",
                    "style": "edgeStyle=orthogonalEdgeStyle;html=1;endArrow=block;",
                    "edge": "1",
                    "parent": "1",
                    "source": "reference",
                    "target": "ai-system",
                    "data-directed": "true",
                },
            )
            ET.SubElement(edge, "mxGeometry", {"relative": "1", "as": "geometry"})
            document.write(source_path, encoding="utf-8", xml_declaration=True)
            manifest_path = mutated / plan["outputs"]["manifest"]
            export_result = exporter.export_drawio(
                plan_path=plan_path,
                source_path=source_path,
                output_dir=mutated / "artifacts",
                drawio_command=fake_command(),
                manifest_path=manifest_path,
                strict_lint=True,
            )
            self.assertTrue(export_result.success)
            report = inspector.inspect_figure(
                plan_path=plan_path,
                source_path=source_path,
                manifest_path=manifest_path,
                qa_path=mutated / plan["outputs"]["qa_report"],
            ).report
            codes = {item["code"] for item in report["issues"]}

        self.assertEqual("AUTOMATED_CHECKS_PASSED", baseline_report["outcome"])
        self.assertEqual(scenario["expected"]["mutated_outcome"], report["outcome"])
        self.assertIn(scenario["expected"]["issue_code"], codes)

    def test_b03_plan_bounded_repair_resolves_fixture_defects(self) -> None:
        scenario = read_scenario("B03")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "B03.render-plan.json"
            plan = build_plan(scenario, plan_path)
            source_path = backend.write_drawio_source(plan, root / "B03.drawio")
            original_hash = runtime.sha256_file(source_path)
            document = ET.parse(source_path)
            graph_root = document.getroot().find("./diagram/mxGraphModel/root")
            assert graph_root is not None
            source = graph_root.find("mxCell[@id='source-node']")
            edge = graph_root.find("mxCell[@id='source-target']")
            assert source is not None and edge is not None
            source.set("style", (source.get("style") or "").replace("whiteSpace=wrap;", ""))
            geometry = source.find("mxGeometry")
            assert geometry is not None
            geometry.set("x", "-60")
            edge.set("target", "missing")
            document.write(source_path, encoding="utf-8", xml_declaration=True)
            corrupted_hash = runtime.sha256_file(source_path)
            result = repairer.repair_drawio(
                source_path=source_path,
                output_path=root / "B03.repaired.drawio",
                plan_path=plan_path,
            )
            action_codes = {item["code"] for item in result.actions}
            preserved_hash = runtime.sha256_file(source_path)

        self.assertNotEqual(original_hash, corrupted_hash)
        self.assertEqual(corrupted_hash, preserved_hash)
        self.assertTrue(result.safe_complete)
        self.assertTrue(set(scenario["expected"]["action_codes"]).issubset(action_codes))

    def test_b04_final_size_baseline_and_small_text_mutation(self) -> None:
        scenario = read_scenario("B04")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, _, _, baseline_report = execute_baseline(root / "baseline", scenario)
            mutated_scenario = deepcopy(scenario)
            mutated_scenario["elements"][0]["font_size_px"] = 4
            _, _, _, _, mutated_report = execute_baseline(root / "mutated", mutated_scenario)
            codes = {item["code"] for item in mutated_report["issues"]}

        self.assertEqual(scenario["expected"]["baseline_outcome"], baseline_report["outcome"])
        self.assertEqual(scenario["expected"]["mutated_outcome"], mutated_report["outcome"])
        self.assertIn(scenario["expected"]["issue_code"], codes)

    def test_f001_unified_render_command_completes_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "figure.py"),
                    "render",
                    str(F001),
                    "--backend",
                    "drawio",
                    "--work-dir",
                    tmp,
                    "--drawio-command",
                    fake_command(),
                    "--json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(completed.stdout)
            qa_path = Path(payload["qa_path"])
            qa = json.loads(qa_path.read_text(encoding="utf-8"))

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertTrue(payload["success"])
        self.assertEqual("COMPLETED", payload["export_status"])
        self.assertEqual("AUTOMATED_CHECKS_PASSED", payload["qa_outcome"])
        self.assertEqual({"blocking": 0, "major": 0, "minor": 0}, qa["summary"])


if __name__ == "__main__":
    unittest.main()
