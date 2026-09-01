from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import textwrap
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
validator = load_module("validate_figure_spec", SCRIPTS / "validate_figure_spec.py")
load_module("figure_coverage", SCRIPTS / "figure_coverage.py")
backend = load_module("drawio_backend", SCRIPTS / "drawio_backend.py")
linter = load_module("drawio_lint", SCRIPTS / "drawio_lint.py")
exporter = load_module("drawio_export", SCRIPTS / "drawio_export.py")
inspector = load_module("figure_inspect", SCRIPTS / "figure_inspect.py")


def fake_command() -> str:
    return f'"{sys.executable}" "{FAKE_DRAWIO}"'


def write_spec(
    root: Path,
    *,
    figure_id: str,
    labels: list[str],
    must_show: list[str],
    relationships: list[str],
) -> Path:
    path = root / f"{figure_id}-coverage-test.md"
    bullets = lambda values: "\n".join(f"            - {value}" for value in values)
    path.write_text(
        textwrap.dedent(
            f"""\
            ---
            spec_version: "1.0"
            figure_id: "{figure_id}"
            working_title: "Coverage Test {figure_id}"
            status: "READY"
            outputs:
              source: null
              vector: null
              preview: null
            ---

            # Scientific Figure Specification

            # 1. Figure Identity

            **Primary Archetype:** Hierarchy

            **Secondary Archetype(s):** Workflow / Pipeline

            # 2. Scientific Purpose

            ## 2.1 Core Message

            Exercise conservative FigureSpec-to-RenderPlan coverage behavior.

            ## 2.2 Intended Reader Takeaway

            Required scientific content must be explicitly represented or reported unresolved.

            ## 2.3 Role in the Paper

            Internal regression fixture only.

            # 3. Required Content

            ## 3.1 Must Show

            {bullets(must_show)}

            ## 3.2 Exact Scientific Content

            - None

            ## 3.3 Source Binding

            - Test semantics → this fixture.

            ## 3.4 Optional / Removable Content

            - Decorative styling.

            ## 3.5 Assumptions / Open Questions

            - This is a synthetic test fixture.

            # 4. Scientific Structure & Relationships

            ## 4.1 Relationships

            {bullets(relationships)}

            # 5. Figure Design

            ## 5.1 Reading Order

            Follow the declared semantic relationship.

            ## 5.2 Composition

            Use a compact editable structure.

            ## 5.3 Primary Visual Anchor

            The declared required content.

            ## 5.4 Information Hierarchy

            ### Primary

            - Required content and relation semantics.

            ### Secondary

            - Editable geometry.

            ### Supporting

            - Minimal styling.

            ## 5.5 Simplification & Redundancy

            - Add no unrelated decorative content.

            # 6. Visual & Content Constraints

            ## 6.1 Visual Semantics

            - Containment is represented through nesting rather than process flow.

            ## 6.2 Required Figure Labels

            {bullets(labels)}

            ## 6.3 Must Not Imply / Avoid

            - Do not replace containment with a directional process arrow.

            # 7. References & Rendering Requirements

            ## 7.1 References

            None

            ## 7.2 Cross-Figure Consistency

            - Preserve declared terms exactly.

            ## 7.3 Rendering Requirements

            **Intended Use:** Automated regression fixture.

            **Target Size / Aspect Ratio:** Approximately 1.8:1 landscape.

            **Preferred Backend:** Draw.io for this explicit fixture only.

            **Required Outputs:** Editable Draw.io source and SVG export.
            """
        ),
        encoding="utf-8",
    )
    report = validator.validate_file(path, project_root=root)
    if report.errors or report.warnings:
        raise AssertionError([item.as_dict() for item in [*report.errors, *report.warnings]])
    return path


class FigureSpecCoverageTests(unittest.TestCase):
    def test_f001_maps_all_must_show_relationships_and_does_not_require_helper_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = backend.build_render_plan(
                F001,
                Path(tmp) / "F001.render-plan.json",
                backend="drawio",
                strict=True,
            )

        self.assertEqual("COMPLETE", plan["spec_coverage"]["status"])
        self.assertEqual(7, plan["spec_coverage"]["summary"]["must_show_mapped"])
        self.assertEqual(6, plan["spec_coverage"]["summary"]["relationships_mapped"])
        relations = {item["relation_type"]: item for item in plan["spec_coverage"]["relationships"]}
        self.assertEqual("MAPPED", relations["evidence_support"]["status"])
        provenance_id = relations["evidence_support"]["representations"][0]["ids"][0]
        provenance = next(item for item in plan["connectors"] if item["id"] == provenance_id)
        self.assertEqual("el-fixed-evidence", provenance["source"])
        self.assertEqual("cue-episode", provenance["target"])

        required_labels = {
            item["params"]["label"]
            for item in plan["semantic_assertions"]
            if item["kind"] == "required_label"
        }
        self.assertNotIn("Alignment / Comparison", required_labels)
        self.assertNotIn("Fidelity Diagnostics", required_labels)
        self.assertNotIn("Stage", required_labels)
        self.assertNotIn("Episode", required_labels)

    def test_canonical_containment_authors_true_parent_child_without_flow_edge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec_path = write_spec(
                root,
                figure_id="F902",
                labels=["Episode", "Action"],
                must_show=["An Episode containing an Action."],
                relationships=[
                    "Episode contains Action. Relation: containment / hierarchy."
                ],
            )
            plan = backend.build_render_plan(
                spec_path,
                root / "F902.render-plan.json",
                backend="drawio",
                strict=True,
            )
            source_path = backend.write_drawio_source(plan, root / "F902.drawio")
            report = linter.lint_drawio(source_path)
            document = ET.parse(source_path)
            cells = {
                cell.get("id"): cell
                for cell in document.getroot().findall("./diagram/mxGraphModel/root/mxCell")
            }

        episode = next(item for item in plan["elements"] if item["label"] == "Episode")
        action = next(item for item in plan["elements"] if item["label"] == "Action")
        self.assertEqual("container", episode["kind"])
        self.assertEqual(episode["id"], action["parent_id"])
        self.assertEqual(episode["id"], cells[action["id"]].get("parent"))
        self.assertFalse(plan["connectors"])
        self.assertEqual([], report.issues)

    def test_unmapped_must_show_blocks_plan_cli_and_authoring(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec_path = write_spec(
                root,
                figure_id="F903",
                labels=["Known Node", "Output"],
                must_show=[
                    "Known Node and Output.",
                    "A scientifically essential latent mechanism with no declared representation.",
                ],
                relationships=[
                    "Known Node → Output. Relation: generated output."
                ],
            )
            plan_path = root / "F903.render-plan.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "figure.py"),
                    "plan",
                    str(spec_path),
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
            plan = json.loads(plan_path.read_text(encoding="utf-8"))

        self.assertEqual(1, completed.returncode)
        self.assertIn("scientific.coverage.must_show_unmapped", completed.stdout)
        self.assertEqual("BLOCKED", plan["spec_coverage"]["status"])
        with self.assertRaisesRegex(backend.DrawioBackendError, "plan.coverage.blocked"):
            backend.drawio_bytes(plan)

    def test_inspector_reparses_figurespec_instead_of_trusting_plan_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "F001.render-plan.json"
            plan = backend.build_render_plan(
                F001,
                plan_path,
                backend="drawio",
                strict=True,
            )
            plan["spec_coverage"]["must_show"].pop()
            plan["spec_coverage"]["summary"]["must_show_total"] -= 1
            plan["spec_coverage"]["summary"]["must_show_mapped"] -= 1
            runtime.write_json_atomic(plan_path, plan)
            source_path = backend.write_drawio_source(plan, root / "F001.drawio")
            manifest_path = root / "F001.manifest.json"
            exporter.export_drawio(
                plan_path=plan_path,
                source_path=source_path,
                output_dir=root / "artifacts",
                drawio_command=fake_command(),
                manifest_path=manifest_path,
                strict_lint=True,
            )
            result = inspector.inspect_figure(
                plan_path=plan_path,
                source_path=source_path,
                manifest_path=manifest_path,
                qa_path=root / "F001.qa.json",
            )
            codes = {item["code"] for item in result.report["issues"]}

        self.assertEqual("BLOCKED", result.report["outcome"])
        self.assertIn("scientific.coverage.must_show_missing", codes)

    def test_inspector_detects_lost_container_parenting_as_coverage_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "F001.render-plan.json"
            plan = backend.create_render_plan_file(
                F001,
                plan_path,
                backend="drawio",
                strict=True,
            )
            source_path = backend.write_drawio_source(plan, root / "F001.drawio")
            document = ET.parse(source_path)
            diagnostic = document.getroot().find(
                "./diagram/mxGraphModel/root/mxCell[@id='el-structural-fidelity']"
            )
            assert diagnostic is not None
            diagnostic.set("parent", "1")
            document.write(source_path, encoding="utf-8", xml_declaration=True)
            manifest_path = root / "F001.manifest.json"
            exporter.export_drawio(
                plan_path=plan_path,
                source_path=source_path,
                output_dir=root / "artifacts",
                drawio_command=fake_command(),
                manifest_path=manifest_path,
                strict_lint=False,
            )
            result = inspector.inspect_figure(
                plan_path=plan_path,
                source_path=source_path,
                manifest_path=manifest_path,
                qa_path=root / "F001.qa.json",
            )
            codes = {item["code"] for item in result.report["issues"]}

        self.assertEqual("BLOCKED", result.report["outcome"])
        self.assertIn("scientific.coverage.representation_missing", codes)


if __name__ == "__main__":
    unittest.main()
