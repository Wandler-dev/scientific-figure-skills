from __future__ import annotations

import csv
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_ROOT / "scripts"
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(SCRIPTS))

from plot_test_utils import valid_line_plan, write_line_data, write_plot_spec

from figure_runtime import sha256_file
from plot_binding import validate_data_binding


def write_plan(path: Path, plan: dict) -> None:
    path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")


class PlotBindingTests(unittest.TestCase):
    def prepare(self, root: Path) -> tuple[Path, Path, Path, dict]:
        spec = write_plot_spec(root)
        data = write_line_data(root)
        plan_path, plan = valid_line_plan(root, spec, data)
        return spec, data, plan_path, plan

    def test_complete_binding_preserves_line_gap_and_uncertainty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, _, plan_path, _ = self.prepare(Path(tmp))
            result = validate_data_binding(plan_path)
        self.assertTrue(result.passed, [i.as_dict() for i in result.issues])
        self.assertEqual("COMPLETE", result.trace["binding_status"])
        model_b = result.resolved_panels[0]["series"][1]
        self.assertEqual(1, model_b["missing_count"])
        self.assertEqual(3, model_b["row_count"])
        self.assertIsNone(model_b["y"][1])
        self.assertIsNone(model_b["lower"][1])
        self.assertEqual("95% CI", model_b["uncertainty_kind"])
        panel_trace = result.trace["panels"][0]
        self.assertEqual({"x": "epoch", "y": "accuracy", "group": "model"}, panel_trace["bound_columns"])
        self.assertEqual(
            {"lower_column": "ci_low", "upper_column": "ci_high"},
            panel_trace["uncertainty_columns"],
        )
        self.assertEqual(
            {"min": 0.7, "max": 0.8},
            panel_trace["series"][0]["value_ranges"]["y"],
        )

    def test_data_hash_mutation_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, data, plan_path, _ = self.prepare(Path(tmp))
            with data.open("a", encoding="utf-8") as handle:
                handle.write("4,Model A,0.82,0.79,0.85\n")
            result = validate_data_binding(plan_path)
        self.assertFalse(result.passed)
        self.assertIn("plot.data.hash_mismatch", {item.code for item in result.issues})

    def test_missing_data_file_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, data, plan_path, _ = self.prepare(Path(tmp))
            data.unlink()
            result = validate_data_binding(plan_path)
        self.assertIn("plot.data.file_missing", {item.code for item in result.issues})

    def test_missing_bound_column_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, _, plan_path, plan = self.prepare(Path(tmp))
            plan["panels"][0]["encoding"]["y"] = "missing_metric"
            write_plan(plan_path, plan)
            result = validate_data_binding(plan_path)
        self.assertIn("plot.binding.column_missing", {item.code for item in result.issues})

    def test_unresolved_figurespec_coverage_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, _, plan_path, plan = self.prepare(Path(tmp))
            item = plan["spec_coverage"]["must_show"][0]
            item["status"] = "UNRESOLVED"
            item["representations"] = []
            item["reason"] = "test"
            summary = plan["spec_coverage"]["summary"]
            summary["must_show_mapped"] -= 1
            summary["unresolved_total"] += 1
            plan["spec_coverage"]["status"] = "BLOCKED"
            write_plan(plan_path, plan)
            result = validate_data_binding(plan_path)
        self.assertIn(
            "scientific.coverage.must_show_unmapped",
            {item.code for item in result.issues},
        )

    def test_log_axis_with_zero_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, data, plan_path, plan = self.prepare(root)
            with data.open("r", encoding="utf-8") as handle:
                rows = list(csv.reader(handle))
            rows[1][2] = "0"
            with data.open("w", encoding="utf-8", newline="") as handle:
                csv.writer(handle).writerows(rows)
            plan["data_sources"][0]["sha256"] = sha256_file(data)
            plan["panels"][0]["axes"]["y"]["scale"] = "log"
            plan["panels"][0]["axes"]["y"].pop("limits")
            write_plan(plan_path, plan)
            result = validate_data_binding(plan_path)
        self.assertIn("plot.axis.log_nonpositive", {item.code for item in result.issues})

    def test_stale_figurespec_hash_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec, _, plan_path, _ = self.prepare(Path(tmp))
            with spec.open("a", encoding="utf-8") as handle:
                handle.write("\n")
            result = validate_data_binding(plan_path)
        self.assertIn(
            "plot.plan.figure_spec_hash_mismatch",
            {item.code for item in result.issues},
        )

    def test_axis_clipping_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, _, plan_path, plan = self.prepare(Path(tmp))
            plan["panels"][0]["axes"]["y"]["limits"] = [0.70, 0.78]
            write_plan(plan_path, plan)
            result = validate_data_binding(plan_path)
        self.assertIn("plot.axis.data_clipped", {item.code for item in result.issues})

    def test_symmetric_uncertainty_is_included_in_axis_clipping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, _, plan_path, plan = self.prepare(Path(tmp))
            panel = plan["panels"][0]
            panel["uncertainty"] = {"kind": "SD", "symmetric_column": "ci_low"}
            panel["axes"]["y"]["limits"] = [0, 1]
            write_plan(plan_path, plan)
            result = validate_data_binding(plan_path)
        self.assertIn("plot.axis.data_clipped", {item.code for item in result.issues})

    def test_gap_forces_uncertainty_gap_even_when_bounds_are_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, data, plan_path, plan = self.prepare(root)
            with data.open("r", encoding="utf-8") as handle:
                rows = list(csv.reader(handle))
            rows[5][3] = "0.68"
            rows[5][4] = "0.74"
            with data.open("w", encoding="utf-8", newline="") as handle:
                csv.writer(handle).writerows(rows)
            plan["data_sources"][0]["sha256"] = sha256_file(data)
            write_plan(plan_path, plan)
            result = validate_data_binding(plan_path)
        self.assertTrue(result.passed, [item.as_dict() for item in result.issues])
        model_b = result.resolved_panels[0]["series"][1]
        self.assertIsNone(model_b["y"][1])
        self.assertIsNone(model_b["lower"][1])
        self.assertIsNone(model_b["upper"][1])

    def test_manual_unbound_scientific_annotation_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, _, plan_path, plan = self.prepare(Path(tmp))
            plan["panels"][0]["annotations"].append(
                {
                    "id": "invented-winner",
                    "text": "+12%",
                    "source": {"type": "source_bound_constant"},
                    "x": 2,
                    "y": 0.8,
                }
            )
            write_plan(plan_path, plan)
            result = validate_data_binding(plan_path)
        self.assertIn("scientific.data.unbound_value", {item.code for item in result.issues})

    def test_annotation_text_cannot_disagree_with_bound_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, _, plan_path, plan = self.prepare(Path(tmp))
            plan["panels"][0]["annotations"].append(
                {
                    "id": "invented-gain",
                    "text": "+12%",
                    "source": {
                        "type": "source_bound_constant",
                        "data_source": "results",
                        "column": "accuracy",
                        "filter": {"column": "model", "operator": "eq", "value": "Model A"},
                        "value": 0.70,
                    },
                    "x": 1,
                    "y": 0.70,
                }
            )
            write_plan(plan_path, plan)
            result = validate_data_binding(plan_path)
        self.assertIn("scientific.data.unbound_value", {item.code for item in result.issues})

    def test_figure_spec_annotation_must_be_a_declared_required_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, _, plan_path, plan = self.prepare(Path(tmp))
            plan["panels"][0]["annotations"].append(
                {
                    "id": "invented-claim",
                    "text": "SOTA",
                    "source": {"type": "figure_spec_label"},
                    "x": 1,
                    "y": 0.70,
                }
            )
            write_plan(plan_path, plan)
            result = validate_data_binding(plan_path)
        self.assertIn("scientific.data.unbound_value", {item.code for item in result.issues})

    def test_design_reference_requires_figure_spec_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, _, plan_path, plan = self.prepare(Path(tmp))
            plan["panels"][0]["reference_lines"].append(
                {
                    "id": "chance-level",
                    "axis": "y",
                    "value": 0.5,
                    "label": "Chance level",
                    "source_type": "design_reference",
                }
            )
            write_plan(plan_path, plan)
            result = validate_data_binding(plan_path)
        self.assertIn("scientific.data.unbound_value", {item.code for item in result.issues})

    def test_figure_spec_covered_design_reference_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, _, plan_path, plan = self.prepare(Path(tmp))
            plan["panels"][0]["reference_lines"].append(
                {
                    "id": "chance-level",
                    "axis": "y",
                    "value": 0.5,
                    "label": "Chance level",
                    "source_type": "design_reference",
                }
            )
            plan["spec_coverage"]["must_show"][0]["representations"].append(
                {"kind": "reference_line", "ids": ["chance-level"]}
            )
            write_plan(plan_path, plan)
            result = validate_data_binding(plan_path)
        self.assertTrue(result.passed, [item.as_dict() for item in result.issues])

    def test_source_bound_reference_accepts_numeric_format_equivalence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, _, plan_path, plan = self.prepare(Path(tmp))
            plan["panels"][0]["reference_lines"].append(
                {
                    "id": "observed-level",
                    "axis": "y",
                    "value": 0.7,
                    "label": "Observed level",
                    "source_type": "source_bound_constant",
                    "source": {
                        "type": "source_bound_constant",
                        "data_source": "results",
                        "column": "accuracy",
                        "filter": {
                            "column": "model",
                            "operator": "eq",
                            "value": "Model A",
                        },
                        "value": 0.7,
                    },
                }
            )
            write_plan(plan_path, plan)
            result = validate_data_binding(plan_path)
        self.assertTrue(result.passed, [item.as_dict() for item in result.issues])

    def test_source_bound_reference_rejects_absent_numeric_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, _, plan_path, plan = self.prepare(Path(tmp))
            plan["panels"][0]["reference_lines"].append(
                {
                    "id": "invented-level",
                    "axis": "y",
                    "value": 0.987654321,
                    "label": "Invented level",
                    "source_type": "source_bound_constant",
                    "source": {
                        "type": "source_bound_constant",
                        "data_source": "results",
                        "column": "accuracy",
                        "value": 0.987654321,
                    },
                }
            )
            write_plan(plan_path, plan)
            result = validate_data_binding(plan_path)
        self.assertIn("scientific.data.unbound_value", {item.code for item in result.issues})

    def test_error_missing_policy_blocks_missing_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, _, plan_path, plan = self.prepare(Path(tmp))
            plan["panels"][0]["missing_policy"] = "error"
            write_plan(plan_path, plan)
            result = validate_data_binding(plan_path)
        self.assertIn("plot.binding.missing_value", {item.code for item in result.issues})

    def test_drop_policy_records_omitted_rows_without_imputation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, _, plan_path, plan = self.prepare(Path(tmp))
            plan["panels"][0]["missing_policy"] = "drop"
            write_plan(plan_path, plan)
            result = validate_data_binding(plan_path)
        self.assertTrue(result.passed, [item.as_dict() for item in result.issues])
        model_b = result.resolved_panels[0]["series"][1]
        self.assertEqual(1, model_b["omitted_count"])
        self.assertEqual(2, model_b["row_count"])

    def test_scatter_size_is_bound_to_declared_numeric_column(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = write_plot_spec(root)
            data = write_line_data(root, include_gap=False)
            plan_path, plan = valid_line_plan(root, spec, data)
            panel = plan["panels"][0]
            panel["plot_type"] = "scatter"
            panel["encoding"]["size"] = "ci_low"
            panel["missing_policy"] = "error"
            panel.pop("uncertainty")
            write_plan(plan_path, plan)
            result = validate_data_binding(plan_path)
        self.assertTrue(result.passed, [item.as_dict() for item in result.issues])
        self.assertEqual([0.67, 0.73, 0.77], result.resolved_panels[0]["series"][0]["size"])

    def test_scatter_nonpositive_size_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = write_plot_spec(root)
            data = write_line_data(root, include_gap=False)
            with data.open("r", encoding="utf-8") as handle:
                rows = list(csv.reader(handle))
            rows[1][3] = "0"
            with data.open("w", encoding="utf-8", newline="") as handle:
                csv.writer(handle).writerows(rows)
            plan_path, plan = valid_line_plan(root, spec, data)
            panel = plan["panels"][0]
            panel["plot_type"] = "scatter"
            panel["encoding"]["size"] = "ci_low"
            panel["missing_policy"] = "error"
            panel.pop("uncertainty")
            write_plan(plan_path, plan)
            result = validate_data_binding(plan_path)
        self.assertIn("plot.series.size_nonpositive", {item.code for item in result.issues})


if __name__ == "__main__":
    unittest.main()
