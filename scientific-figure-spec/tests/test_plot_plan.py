from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_ROOT / "scripts"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(SCRIPTS))

from plot_test_utils import write_line_data, write_plot_spec
from plot_test_utils import valid_line_plan

import plot_plan
import figure_runtime


class PlotPlanTests(unittest.TestCase):
    def test_plot_plan_schema_is_independent_versioned_contract(self) -> None:
        schema = json.loads(
            (SKILL_ROOT / "schemas" / "plot-plan.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual("1.0", schema["properties"]["schema_version"]["const"])
        self.assertEqual("matplotlib", schema["properties"]["backend"]["const"])
        self.assertNotIn("elements", schema["properties"])
        self.assertNotIn("connectors", schema["properties"])

    def test_scaffold_records_inputs_without_guessing_plot_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = write_plot_spec(root)
            data = write_line_data(root)
            plan_path = root / "scaffold.json"
            plan = plot_plan.create_plot_plan_file(
                spec,
                plan_path,
                data_paths=[data],
                strict=True,
            )
        self.assertEqual("1.0", plan["schema_version"])
        self.assertEqual("matplotlib", plan["backend"])
        self.assertEqual([], plan["panels"])
        self.assertEqual("BLOCKED", plan["spec_coverage"]["status"])
        self.assertGreater(plan["spec_coverage"]["summary"]["unresolved_total"], 0)
        self.assertEqual("authoritative_plot_data", plan["data_sources"][0]["role"])
        self.assertEqual([], [i for i in figure_runtime.validate_plot_plan_contract(plan) if i.severity == "ERROR"])

    def test_unified_cli_creates_blocked_matplotlib_scaffold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = write_plot_spec(root)
            data = write_line_data(root)
            output = root / "scaffold.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "figure.py"),
                    "plan",
                    str(spec),
                    "--backend",
                    "matplotlib",
                    "--data",
                    str(data),
                    "--output",
                    str(output),
                    "--strict",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            plan = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(1, completed.returncode, completed.stderr)
        self.assertIn("requires explicit panel", completed.stdout)
        self.assertEqual("BLOCKED", plan["spec_coverage"]["status"])

    def test_validate_sidecar_accepts_plot_plan_kind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = write_plot_spec(root)
            data = write_line_data(root)
            path = root / "scaffold.json"
            plot_plan.create_plot_plan_file(spec, path, data_paths=[data])
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "figure.py"),
                    "validate-sidecar",
                    "plot-plan",
                    str(path),
                    "--json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertTrue(json.loads(completed.stdout)["passed"])

    def test_contract_rejects_uncertainty_on_scatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = write_plot_spec(root)
            data = write_line_data(root, include_gap=False)
            _, plan = valid_line_plan(root, spec, data)
            plan["panels"][0]["plot_type"] = "scatter"
            plan["panels"][0]["missing_policy"] = "error"
            issues = figure_runtime.validate_plot_plan_contract(plan)
        self.assertIn(
            "plot.uncertainty.plot_type_unsupported",
            {item.code for item in issues},
        )

    def test_contract_requires_consistent_shared_legend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = write_plot_spec(root)
            data = write_line_data(root)
            _, plan = valid_line_plan(root, spec, data)
            plan["panels"][0]["legend"]["mode"] = "figure"
            issues = figure_runtime.validate_plot_plan_contract(plan)
            plan["layout"]["shared_legend"] = True
            corrected = figure_runtime.validate_plot_plan_contract(plan)
        self.assertIn("plot.legend.shared_disabled", {item.code for item in issues})
        self.assertNotIn("plot.legend.shared_disabled", {item.code for item in corrected})

    def test_contract_rejects_silent_extra_encoding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = write_plot_spec(root)
            data = write_line_data(root)
            _, plan = valid_line_plan(root, spec, data)
            plan["panels"][0]["encoding"]["value"] = "accuracy"
            issues = figure_runtime.validate_plot_plan_contract(plan)
        self.assertIn("plot.panel.encoding_unsupported", {item.code for item in issues})

    def test_contract_rejects_unsafe_output_path_and_empty_formats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = write_plot_spec(root)
            data = write_line_data(root)
            _, plan = valid_line_plan(root, spec, data)
            plan["outputs"]["source"] = "../outside.plot.py"
            plan["outputs"]["formats"] = []
            issues = figure_runtime.validate_plot_plan_contract(plan)
        codes = {item.code for item in issues}
        self.assertIn("plot.output.path_unsafe", codes)
        self.assertIn("schema.min_items", codes)


if __name__ == "__main__":
    unittest.main()
