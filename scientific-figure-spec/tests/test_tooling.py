from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_ROOT / "scripts"
EXAMPLE = SKILL_ROOT / "examples" / "F001-evidence-traceable-reconstruction.md"
TEMPLATE = SKILL_ROOT / "assets" / "figure-spec.template.md"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module: {path}")
    module = importlib.util.module_from_spec(spec)
    # dataclasses and other reflection helpers expect the module to exist here.
    import sys

    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


init = load_module("figure_spec_init", SCRIPTS / "init_figures.py")
validator = load_module("figure_spec_validator", SCRIPTS / "validate_figure_spec.py")


def validate_document(document: str, filename: str = "F001-test.md"):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / filename
        path.write_text(document, encoding="utf-8")
        return validator.validate_file(path, project_root=root)


def move_h2_before(document: str, source_title: str, target_title: str) -> str:
    lines = document.splitlines(keepends=True)
    source_marker = f"## {source_title}"
    target_marker = f"## {target_title}"
    start = next(i for i, line in enumerate(lines) if line.strip() == source_marker)
    end = len(lines)
    for index in range(start + 1, len(lines)):
        stripped = lines[index].lstrip()
        if stripped.startswith("# ") or stripped.startswith("## "):
            end = index
            break
    block = lines[start:end]
    del lines[start:end]
    target = next(i for i, line in enumerate(lines) if line.strip() == target_marker)
    lines[target:target] = block
    return "".join(lines)


def move_h3_after_h2(document: str, source_title: str, target_title: str) -> str:
    lines = document.splitlines(keepends=True)
    source_marker = f"### {source_title}"
    target_marker = f"## {target_title}"
    start = next(i for i, line in enumerate(lines) if line.strip() == source_marker)
    end = len(lines)
    for index in range(start + 1, len(lines)):
        stripped = lines[index].lstrip()
        if (
            stripped.startswith("# ")
            or stripped.startswith("## ")
            or stripped.startswith("### ")
        ):
            end = index
            break
    block = lines[start:end]
    del lines[start:end]
    target = next(i for i, line in enumerate(lines) if line.strip() == target_marker)
    lines[target + 1 : target + 1] = block
    return "".join(lines)


class FigureSpecToolingTests(unittest.TestCase):
    def test_example_passes(self) -> None:
        report = validator.validate_file(EXAMPLE, project_root=SKILL_ROOT)
        self.assertEqual([], report.errors)
        self.assertEqual([], report.warnings)

    def test_unicode_slug_and_batch_initialization(self) -> None:
        self.assertEqual("事件过程分析", init.slugify("事件过程分析"))
        self.assertEqual(
            "prediction-simulation",
            init.slugify("Prediction / Simulation"),
        )

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "figures"
            output_dir.mkdir()
            template = init.load_template(TEMPLATE)
            plan = init.make_plan(
                ["事件过程分析", "Evaluation Framework"],
                output_dir,
                first_number=1,
            )
            init.preflight(plan)
            init.write_batch(plan, template)

            self.assertTrue((output_dir / "F001-事件过程分析.md").is_file())
            self.assertTrue((output_dir / "F002-evaluation-framework.md").is_file())
            self.assertEqual({1, 2}, init.existing_figure_numbers(output_dir))

    def test_ready_status_rejects_template_boilerplate(self) -> None:
        template = init.load_template(TEMPLATE)
        document = init.render_spec(template, "F001", "Empty Ready Figure")
        document = init.replace_frontmatter_field(
            document,
            "status",
            init.yaml_string("READY"),
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "F001-empty-ready.md"
            path.write_text(document, encoding="utf-8")
            report = validator.validate_file(path, project_root=Path(tmp))
            codes = {issue.code for issue in report.errors}

        self.assertIn("readiness.core_message", codes)
        self.assertIn("readiness.must_show", codes)
        self.assertIn("readiness.relationships", codes)
        self.assertIn("readiness.composition", codes)
        self.assertIn("readiness.primary_anchor", codes)

    def test_numeric_exact_content_requires_source_binding_warning(self) -> None:
        document = EXAMPLE.read_text(encoding="utf-8")
        document = document.replace(
            "- Candidate EPG\n- Reference EPG",
            "- 3,000 events\n- Candidate EPG\n- Reference EPG",
            1,
        )
        document = document.replace(
            "- Terminology and evaluation dimensions → paper method and evaluation sections.\n"
            "- Candidate / Reference separation → benchmark evaluation protocol.",
            "- None",
            1,
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "F001-numeric.md"
            path.write_text(document, encoding="utf-8")
            report = validator.validate_file(path, project_root=Path(tmp))
            codes = {issue.code for issue in report.warnings}

        self.assertIn("content.numeric_without_source_binding", codes)

    def test_rendered_status_requires_artifact(self) -> None:
        document = EXAMPLE.read_text(encoding="utf-8").replace(
            'status: "READY"',
            'status: "RENDERED"',
            1,
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "F001-rendered.md"
            path.write_text(document, encoding="utf-8")
            report = validator.validate_file(path, project_root=Path(tmp))
            codes = {issue.code for issue in report.errors}

        self.assertIn("outputs.required", codes)

    def test_rendered_status_rejects_directory_artifact(self) -> None:
        document = EXAMPLE.read_text(encoding="utf-8")
        document = document.replace('status: "READY"', 'status: "RENDERED"', 1)
        document = document.replace('vector: null', 'vector: "artifact.svg"', 1)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "artifact.svg").mkdir()
            path = root / "F001-rendered-directory.md"
            path.write_text(document, encoding="utf-8")
            report = validator.validate_file(path, project_root=root)
            codes = {issue.code for issue in report.errors}

        self.assertIn("outputs.missing_artifact", codes)

    def test_core_message_in_section_seven_fails(self) -> None:
        document = move_h2_before(
            EXAMPLE.read_text(encoding="utf-8"),
            "2.1 Core Message",
            "7.2 Cross-Figure Consistency",
        )
        report = validate_document(document)
        codes = {issue.code for issue in report.errors}

        self.assertIn("structure.subheading_parent", codes)

    def test_references_in_section_two_fails(self) -> None:
        document = move_h2_before(
            EXAMPLE.read_text(encoding="utf-8"),
            "7.1 References",
            "2.2 Intended Reader Takeaway",
        )
        report = validate_document(document)
        codes = {issue.code for issue in report.errors}

        self.assertIn("structure.subheading_parent", codes)

    def test_required_subheading_order_fails(self) -> None:
        document = EXAMPLE.read_text(encoding="utf-8")
        document = document.replace("## 2.1 Core Message", "## __TEMP__", 1)
        document = document.replace(
            "## 2.2 Intended Reader Takeaway",
            "## 2.1 Core Message",
            1,
        )
        document = document.replace(
            "## __TEMP__",
            "## 2.2 Intended Reader Takeaway",
            1,
        )
        report = validate_document(document)
        codes = {issue.code for issue in report.errors}

        self.assertIn("structure.subheading_order", codes)

    def test_extra_top_level_heading_fails(self) -> None:
        document = (
            EXAMPLE.read_text(encoding="utf-8")
            + "\n# 8. Extra Section\n\nUnexpected top-level content.\n"
        )
        report = validate_document(document)
        codes = {issue.code for issue in report.errors}

        self.assertIn("structure.unexpected_top_level_heading", codes)

    def test_canonical_top_level_heading_order_fails(self) -> None:
        document = EXAMPLE.read_text(encoding="utf-8")
        document = document.replace("# 2. Scientific Purpose", "# __TEMP__", 1)
        document = document.replace(
            "# 3. Required Content",
            "# 2. Scientific Purpose",
            1,
        )
        document = document.replace("# __TEMP__", "# 3. Required Content", 1)
        report = validate_document(document)
        codes = {issue.code for issue in report.errors}

        self.assertIn("structure.section_order", codes)

    def test_primary_outside_information_hierarchy_fails(self) -> None:
        document = move_h3_after_h2(
            EXAMPLE.read_text(encoding="utf-8"),
            "Primary",
            "5.5 Simplification & Redundancy",
        )
        report = validate_document(document)
        codes = {issue.code for issue in report.errors}

        self.assertIn("structure.hierarchy_heading_parent", codes)

    def test_hierarchy_heading_order_fails(self) -> None:
        document = EXAMPLE.read_text(encoding="utf-8")
        document = document.replace("### Primary", "### __TEMP__", 1)
        document = document.replace("### Secondary", "### Primary", 1)
        document = document.replace("### __TEMP__", "### Secondary", 1)
        report = validate_document(document)
        codes = {issue.code for issue in report.errors}

        self.assertIn("structure.hierarchy_heading_order", codes)

    def test_extra_subheading_in_canonical_section_passes(self) -> None:
        document = EXAMPLE.read_text(encoding="utf-8").replace(
            "# 3. Required Content",
            "## 2.4 Additional Context\n\nOptional context.\n\n"
            "# 3. Required Content",
            1,
        )
        report = validate_document(document)

        self.assertEqual([], report.errors)
        self.assertEqual([], report.warnings)

    def test_extra_h3_in_canonical_section_passes(self) -> None:
        document = EXAMPLE.read_text(encoding="utf-8").replace(
            "## 5.5 Simplification & Redundancy",
            "### Additional Hierarchy Note\n\nOptional detail.\n\n"
            "## 5.5 Simplification & Redundancy",
            1,
        )
        report = validate_document(document)

        self.assertEqual([], report.errors)
        self.assertEqual([], report.warnings)

    def test_noncanonical_status_casing_warns_and_strict_fails(self) -> None:
        document = EXAMPLE.read_text(encoding="utf-8").replace(
            'status: "READY"',
            'status: "ready"',
            1,
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "F001-lowercase-status.md"
            path.write_text(document, encoding="utf-8")
            report = validator.validate_file(path, project_root=Path(tmp))
            warning_codes = {issue.code for issue in report.warnings}
            normal = subprocess.run(
                [sys.executable, str(SCRIPTS / "validate_figure_spec.py"), str(path)],
                check=False,
                capture_output=True,
                text=True,
            )
            strict = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "validate_figure_spec.py"),
                    "--strict",
                    str(path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual([], report.errors)
        self.assertIn("metadata.status_casing", warning_codes)
        self.assertEqual(0, normal.returncode)
        self.assertEqual(1, strict.returncode)

    def test_duplicate_ids_are_detected(self) -> None:
        document = EXAMPLE.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path_a = root / "F001-a.md"
            path_b = root / "F001-b.md"
            path_a.write_text(document, encoding="utf-8")
            path_b.write_text(document.replace(
                'working_title: "Evidence-Traceable Reconstruction Overview"',
                'working_title: "Another Figure"',
                1,
            ), encoding="utf-8")

            reports = [
                validator.validate_file(path_a, project_root=root),
                validator.validate_file(path_b, project_root=root),
            ]
            validator.validate_duplicate_ids(reports)
            codes = [
                issue.code
                for report in reports
                for issue in report.errors
            ]

        self.assertGreaterEqual(codes.count("project.duplicate_figure_id"), 2)


if __name__ == "__main__":
    unittest.main()
