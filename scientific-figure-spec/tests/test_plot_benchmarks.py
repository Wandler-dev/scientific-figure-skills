from __future__ import annotations

import csv
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_ROOT / "scripts"
BENCHMARKS = SKILL_ROOT / "benchmarks"
sys.path.insert(0, str(SCRIPTS))

from figure_runtime import sha256_file, validate_plot_plan_contract
from plot_binding import validate_data_binding
from plot_pipeline import run_plot_pipeline


HAS_MATPLOTLIB = importlib.util.find_spec("matplotlib") is not None
PLOT_BENCHMARKS = {
    "B09": BENCHMARKS / "B09-line-uncertainty",
    "B10": BENCHMARKS / "B10-grouped-bar",
    "B11": BENCHMARKS / "B11-heatmap",
}


def load_plan(root: Path) -> dict:
    return json.loads((root / "plot-plan.json").read_text(encoding="utf-8"))


def write_plan(root: Path, plan: dict) -> Path:
    path = root / "plot-plan.json"
    path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return path


class PlotBenchmarkTests(unittest.TestCase):
    def test_b09_b10_b11_contracts_and_bindings_are_complete(self) -> None:
        for benchmark_id, root in PLOT_BENCHMARKS.items():
            with self.subTest(benchmark_id=benchmark_id):
                plan_path = root / "plot-plan.json"
                plan = load_plan(root)
                self.assertEqual([], [i for i in validate_plot_plan_contract(plan) if i.severity == "ERROR"])
                binding = validate_data_binding(plan_path)
                self.assertTrue(binding.passed, [i.as_dict() for i in binding.issues])

    def test_b09_preserves_gap_and_precomputed_uncertainty(self) -> None:
        binding = validate_data_binding(PLOT_BENCHMARKS["B09"] / "plot-plan.json")
        model_b = binding.resolved_panels[0]["series"][1]
        self.assertIsNone(model_b["y"][1])
        self.assertIsNone(model_b["lower"][1])
        self.assertEqual("95% CI", model_b["uncertainty_kind"])
        self.assertEqual(0, model_b["omitted_count"])

    def test_b10_preserves_grouping_values_uncertainty_and_zero_baseline(self) -> None:
        root = PLOT_BENCHMARKS["B10"]
        plan = load_plan(root)
        binding = validate_data_binding(root / "plot-plan.json")
        panel = plan["panels"][0]
        model_a = binding.resolved_panels[0]["series"][0]
        self.assertEqual(["Accuracy", "F1"], panel["category_order"])
        self.assertEqual([0.82, 0.78], model_a["value"])
        self.assertEqual([0.02, 0.03], model_a["symmetric"])
        self.assertEqual(0, panel["axes"]["y"]["limits"][0])

    def test_b11_has_deterministic_cells_and_labeled_sequential_scale(self) -> None:
        root = PLOT_BENCHMARKS["B11"]
        plan = load_plan(root)
        binding = validate_data_binding(root / "plot-plan.json")
        panel = plan["panels"][0]
        self.assertEqual("sequential", panel["color_scale"]["kind"])
        self.assertEqual("Score", panel["color_scale"]["label"])
        self.assertEqual(6, len(binding.resolved_panels[0]["cells"]))

    def test_b11_missing_matrix_cell_blocks_under_error_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "B11-heatmap"
            shutil.copytree(PLOT_BENCHMARKS["B11"], root)
            data = root / "data.csv"
            with data.open("r", encoding="utf-8") as handle:
                rows = list(csv.reader(handle))
            rows.pop()
            with data.open("w", encoding="utf-8", newline="") as handle:
                csv.writer(handle).writerows(rows)
            plan = load_plan(root)
            plan["data_sources"][0]["sha256"] = sha256_file(data)
            plan_path = write_plan(root, plan)
            result = validate_data_binding(plan_path)
        self.assertIn(
            "plot.binding.heatmap_cell_missing",
            {item.code for item in result.issues},
        )

    def test_b10_rejects_missing_or_duplicate_category_within_one_series(self) -> None:
        for mutation, expected_code in (
            ("missing", "plot.binding.category_missing"),
            ("duplicate", "plot.binding.category_duplicate"),
        ):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "B10-grouped-bar"
                shutil.copytree(PLOT_BENCHMARKS["B10"], root)
                data = root / "data.csv"
                with data.open("r", encoding="utf-8") as handle:
                    rows = list(csv.reader(handle))
                if mutation == "missing":
                    rows = [row for row in rows if row[:2] != ["Model B", "F1"]]
                else:
                    rows.append(list(rows[1]))
                with data.open("w", encoding="utf-8", newline="") as handle:
                    csv.writer(handle).writerows(rows)
                plan = load_plan(root)
                plan["data_sources"][0]["sha256"] = sha256_file(data)
                plan_path = write_plan(root, plan)
                result = validate_data_binding(plan_path)
            self.assertIn(expected_code, {item.code for item in result.issues})

    @unittest.skipUnless(HAS_MATPLOTLIB, "Matplotlib optional runtime is unavailable")
    def test_b09_and_b10_complete_with_real_matplotlib(self) -> None:
        for benchmark_id in ("B09", "B10"):
            with self.subTest(benchmark_id=benchmark_id), tempfile.TemporaryDirectory() as tmp:
                result = run_plot_pipeline(
                    plot_plan_path=PLOT_BENCHMARKS[benchmark_id] / "plot-plan.json",
                    work_dir=Path(tmp),
                    strict_lint=True,
                )
                self.assertTrue(result.success, result.as_dict())
                self.assertEqual("COMPLETED", result.export_status)
                self.assertEqual("AUTOMATED_CHECKS_PASSED", result.qa_outcome)

    @unittest.skipUnless(HAS_MATPLOTLIB, "Matplotlib optional runtime is unavailable")
    def test_b10_svg_preserves_categorical_tick_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_plot_pipeline(
                plot_plan_path=PLOT_BENCHMARKS["B10"] / "plot-plan.json",
                work_dir=root,
                strict_lint=True,
            )
            svg = root / "artifacts" / "F921-grouped-bar.svg"
            document = ET.parse(svg).getroot()
            labels = {
                "".join(node.itertext()).strip()
                for node in document.iter()
                if node.tag.rsplit("}", 1)[-1] == "text"
            }
        self.assertTrue(result.success, result.as_dict())
        self.assertIn("Accuracy", labels)
        self.assertIn("F1", labels)

    @unittest.skipUnless(HAS_MATPLOTLIB, "Matplotlib optional runtime is unavailable")
    def test_b11_svg_uses_vector_cells_and_categorical_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_plot_pipeline(
                plot_plan_path=PLOT_BENCHMARKS["B11"] / "plot-plan.json",
                work_dir=root,
                strict_lint=True,
            )
            svg = root / "artifacts" / "F922-heatmap.svg"
            document = ET.parse(svg).getroot()
            local_names = [node.tag.rsplit("}", 1)[-1] for node in document.iter()]
            labels = {
                "".join(node.itertext()).strip()
                for node in document.iter()
                if node.tag.rsplit("}", 1)[-1] == "text"
            }
        self.assertTrue(result.success, result.as_dict())
        self.assertNotIn("image", local_names)
        self.assertTrue({"Model A", "Model B", "Task 1", "Task 2", "Task 3"}.issubset(labels))

    def test_b12_negative_mutations_emit_stable_codes(self) -> None:
        scenarios = json.loads(
            (BENCHMARKS / "B12-data-binding-negative" / "scenarios.json").read_text(encoding="utf-8")
        )["cases"]
        for scenario in scenarios:
            with self.subTest(case=scenario["id"]), tempfile.TemporaryDirectory() as tmp:
                source_root = PLOT_BENCHMARKS[scenario["base"]]
                root = Path(tmp) / source_root.name
                shutil.copytree(source_root, root)
                plan = load_plan(root)
                case = scenario["id"]
                data = root / "data.csv"
                if case == "wrong-data-sha256":
                    plan["data_sources"][0]["sha256"] = "0" * 64
                elif case == "missing-data-file":
                    data.unlink()
                elif case == "missing-column":
                    plan["panels"][0]["encoding"]["y"] = "missing_metric"
                elif case == "missing-uncertainty-column":
                    plan["panels"][0]["uncertainty"]["lower_column"] = "missing_ci"
                elif case == "invalid-numeric-value":
                    with data.open("r", encoding="utf-8") as handle:
                        rows = list(csv.reader(handle))
                    rows[1][2] = "not-a-number"
                    with data.open("w", encoding="utf-8", newline="") as handle:
                        csv.writer(handle).writerows(rows)
                    plan["data_sources"][0]["sha256"] = sha256_file(data)
                elif case == "missing-under-error-policy":
                    plan["panels"][0]["missing_policy"] = "error"
                elif case == "unresolved-coverage":
                    item = plan["spec_coverage"]["must_show"][0]
                    item.update(status="UNRESOLVED", representations=[], reason="intentional benchmark mutation")
                    summary = plan["spec_coverage"]["summary"]
                    summary["must_show_mapped"] -= 1
                    summary["unresolved_total"] += 1
                    plan["spec_coverage"]["status"] = "BLOCKED"
                elif case == "unbound-manual-value":
                    plan["panels"][0]["annotations"].append(
                        {
                            "id": "manual-score",
                            "text": "+12%",
                            "source": {"type": "source_bound_constant"},
                            "x": 0,
                            "y": 0.9,
                        }
                    )
                elif case == "log-axis-zero":
                    with data.open("r", encoding="utf-8") as handle:
                        rows = list(csv.reader(handle))
                    rows[1][2] = "0"
                    with data.open("w", encoding="utf-8", newline="") as handle:
                        csv.writer(handle).writerows(rows)
                    plan["data_sources"][0]["sha256"] = sha256_file(data)
                    plan["panels"][0]["axes"]["y"]["scale"] = "log"
                    plan["panels"][0]["axes"]["y"].pop("limits", None)
                elif case == "stale-figure-spec":
                    spec_path = root / plan["figure_spec"]["path"]
                    with spec_path.open("a", encoding="utf-8") as handle:
                        handle.write("\n")
                elif case == "axis-clipping":
                    plan["panels"][0]["axes"]["y"]["limits"] = [0.70, 0.78]
                elif case == "category-missing":
                    plan["panels"][0]["category_order"] = ["Accuracy"]
                elif case == "nonzero-bar-baseline":
                    plan["panels"][0]["axes"]["y"]["limits"] = [0.5, 1]
                elif case == "diverging-center-missing":
                    plan["panels"][0]["color_scale"]["kind"] = "diverging"
                    plan["panels"][0]["color_scale"].pop("center", None)
                elif case == "heatmap-missing-value-column":
                    plan["panels"][0]["encoding"]["value"] = "missing_score"
                elif case == "heatmap-unbound-manual-annotation":
                    plan["panels"][0]["annotations"].append(
                        {
                            "id": "manual-best",
                            "text": "best",
                            "source": {"type": "source_bound_constant"},
                            "x": 0,
                            "y": 0,
                        }
                    )
                else:
                    self.fail(f"Unhandled B12 case: {case}")
                plan_path = write_plan(root, plan)
                result = validate_data_binding(plan_path)
                self.assertFalse(result.passed)
                self.assertIn(scenario["expected_code"], {item.code for item in result.issues})


if __name__ == "__main__":
    unittest.main()
