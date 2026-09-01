from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_ROOT / "scripts"
EXAMPLE = SKILL_ROOT / "examples" / "F001-evidence-traceable-reconstruction.md"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runtime = load_module("figure_runtime", SCRIPTS / "figure_runtime.py")


def valid_render_plan() -> dict:
    return {
        "schema_version": "1.1",
        "plan_id": "F001-test-drawio",
        "backend": "drawio",
        "figure_spec": {
            "path": "F001-test.md",
            "sha256": "0" * 64,
            "spec_version": "1.0",
            "figure_id": "F001",
        },
        "spec_coverage": {
            "status": "COMPLETE",
            "must_show": [],
            "relationships": [],
            "summary": {
                "must_show_total": 0,
                "must_show_mapped": 0,
                "relationships_total": 0,
                "relationships_mapped": 0,
                "unresolved_total": 0,
            },
        },
        "canvas": {
            "width": 1000,
            "height": 600,
            "unit": "px",
            "margin": 24,
            "background": "#FFFFFF",
        },
        "final_size": {
            "width": 180,
            "height": 108,
            "unit": "mm",
            "minimum_text_size_pt": 6.5,
        },
        "theme": {
            "font_family": "Arial",
            "font_size_px": 16,
            "title_font_size_px": 20,
            "line_width_px": 2,
            "palette": {"ink": "#17324D", "paper": "#FFFFFF"},
        },
        "elements": [
            {
                "id": "node-a",
                "kind": "node",
                "label": "A",
                "semantic_role": "input",
                "parent_id": None,
                "geometry": {"x": 40, "y": 80, "width": 180, "height": 80},
                "style_tokens": {
                    "fill": "#FFFFFF",
                    "stroke": "#17324D",
                    "font_color": "#17324D",
                    "font_size_px": 16,
                    "bold": False,
                    "rounded": True,
                    "align": "center",
                    "vertical_align": "middle",
                },
                "source_ref": "3.1 Must Show",
            },
            {
                "id": "node-b",
                "kind": "node",
                "label": "B",
                "semantic_role": "output",
                "parent_id": None,
                "geometry": {"x": 360, "y": 80, "width": 180, "height": 80},
                "style_tokens": {
                    "fill": "#FFFFFF",
                    "stroke": "#17324D",
                    "font_color": "#17324D",
                    "font_size_px": 16,
                    "bold": False,
                    "rounded": True,
                    "align": "center",
                    "vertical_align": "middle",
                },
                "source_ref": "3.1 Must Show",
            },
        ],
        "connectors": [
            {
                "id": "edge-a-b",
                "source": "node-a",
                "target": "node-b",
                "relation": "process flow",
                "directed": True,
                "label": "",
                "style_tokens": {
                    "stroke": "#17324D",
                    "font_color": "#17324D",
                    "font_size_px": 14,
                    "dashed": False,
                },
            }
        ],
        "semantic_assertions": [
            {
                "id": "label-a",
                "kind": "required_label",
                "severity": "BLOCKING",
                "params": {"label": "A"},
                "why": "A is required.",
            }
        ],
        "outputs": {
            "source": "F001-test.drawio",
            "formats": ["svg"],
            "manifest": "F001-test.manifest.json",
            "qa_report": "F001-test.qa.json",
        },
    }


class RuntimeContractTests(unittest.TestCase):
    def test_registry_keeps_all_backends_opt_in_and_records_non_goals(self) -> None:
        registry = runtime.load_capability_registry()
        self.assertEqual("1.3.1", registry["package_version"])
        self.assertEqual(registry["package_version"], runtime.package_version())
        self.assertIn(
            f"release **{registry['package_version']}**",
            (SKILL_ROOT / "README.md").read_text(encoding="utf-8"),
        )
        self.assertIsNone(registry["default_backend"])
        self.assertFalse(registry["backends"]["drawio"]["default"])
        self.assertFalse(registry["backends"]["svg"]["default"])
        self.assertFalse(registry["backends"]["matplotlib"]["default"])
        self.assertIn("graphviz", registry["out_of_scope"])
        self.assertNotIn("matplotlib", registry["out_of_scope"])
        self.assertIn("multi_agent_orchestration", registry["out_of_scope"])
        self.assertNotIn("fake_svg_renderer", json.dumps(registry))

    def test_internal_preflight_does_not_require_drawio_desktop(self) -> None:
        result = runtime.preflight(backend="drawio", operation="author")
        self.assertTrue(result["ready"])
        self.assertIsNone(result["drawio_cli"])

    def test_export_preflight_reports_missing_explicit_cli(self) -> None:
        result = runtime.preflight(
            backend="drawio",
            operation="export",
            drawio_command="/definitely/missing/drawio",
        )
        self.assertFalse(result["ready"])
        codes = {item["code"] for item in result["issues"]}
        self.assertIn("capability.drawio_cli.missing", codes)

    def test_svg_authoring_is_available_independently_of_optional_renderer(self) -> None:
        result = runtime.preflight(backend="svg", operation="author")
        self.assertTrue(result["ready"])
        if result["svg_renderer"] is not None:
            self.assertTrue(result["svg_renderer"]["command"])

    def test_svg_repair_is_explicitly_unavailable(self) -> None:
        result = runtime.preflight(backend="svg", operation="repair")
        self.assertFalse(result["ready"])
        self.assertIn(
            "capability.operation.unavailable",
            {item["code"] for item in result["issues"]},
        )

    def test_matplotlib_is_optional_and_never_becomes_default(self) -> None:
        author = runtime.preflight(backend="matplotlib", operation="author")
        export = runtime.preflight(backend="matplotlib", operation="export")
        self.assertTrue(author["ready"])
        if importlib.util.find_spec("matplotlib") is None:
            self.assertFalse(export["ready"])
            self.assertIn(
                "capability.matplotlib.missing",
                {item["code"] for item in export["issues"]},
            )
        else:
            self.assertTrue(export["ready"])
            self.assertTrue(export["matplotlib"]["version"])

    def test_matplotlib_repair_is_explicitly_unavailable(self) -> None:
        result = runtime.preflight(backend="matplotlib", operation="repair")
        self.assertFalse(result["ready"])
        self.assertIn(
            "capability.operation.unavailable",
            {item["code"] for item in result["issues"]},
        )

    def test_render_plan_contract_checks_ids_and_endpoints(self) -> None:
        plan = valid_render_plan()
        self.assertEqual([], runtime.validate_render_plan_contract(plan))

        broken = deepcopy(plan)
        broken["elements"][1]["id"] = "node-a"
        broken["connectors"][0]["target"] = "missing"
        codes = {
            item.code for item in runtime.validate_render_plan_contract(broken)
        }
        self.assertIn("plan.id_duplicate", codes)
        self.assertIn("plan.connector.endpoint_missing", codes)

    def test_unified_cli_preserves_strict_figurespec_validation(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "figure.py"),
                "validate",
                "--strict",
                str(EXAMPLE),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("Result:   PASS", completed.stdout)

    def test_unified_cli_help_lists_compatibility_and_execution_commands(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPTS / "figure.py"), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        for command in ("init", "validate", "plan", "render", "inspect"):
            with self.subTest(command=command):
                self.assertIn(command, completed.stdout)

    def test_unified_cli_validates_sidecar_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.json"
            path.write_text(
                json.dumps(valid_render_plan()),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "figure.py"),
                    "validate-sidecar",
                    "render-plan",
                    str(path),
                    "--json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertTrue(json.loads(completed.stdout)["passed"])

    def test_installable_skill_does_not_depend_on_parent_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            installed = Path(tmp) / "skills" / "scientific-figure-spec"
            shutil.copytree(
                SKILL_ROOT,
                installed,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            cli = installed / "scripts" / "figure.py"
            help_result = subprocess.run(
                [sys.executable, str(cli), "--help"],
                check=False,
                capture_output=True,
                text=True,
            )
            capabilities_result = subprocess.run(
                [sys.executable, str(cli), "capabilities", "--json"],
                check=False,
                capture_output=True,
                text=True,
            )
            version_result = subprocess.run(
                [sys.executable, str(cli), "--version"],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(0, help_result.returncode, help_result.stderr)
        self.assertEqual(
            0,
            capabilities_result.returncode,
            capabilities_result.stderr,
        )
        capabilities = json.loads(capabilities_result.stdout)
        self.assertEqual("1.3.1", capabilities["package_version"])
        self.assertIn("svg", capabilities["backends"])
        self.assertIn("matplotlib", capabilities["backends"])
        self.assertEqual(0, version_result.returncode, version_result.stderr)
        self.assertIn("scientific-figure-skills", version_result.stdout)
        self.assertIn(capabilities["package_version"], version_result.stdout)


if __name__ == "__main__":
    unittest.main()
