from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_ROOT / "scripts"
TESTS = Path(__file__).resolve().parent
import sys

sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(SCRIPTS))

from figure_runtime import RuntimeIssue, sha256_file
from plot_test_utils import valid_line_plan, write_line_data, write_plot_spec
import matplotlib_backend
import plot_inspect


HAS_MATPLOTLIB = importlib.util.find_spec("matplotlib") is not None


class PlotInspectionIssueDedupTests(unittest.TestCase):
    def test_manifest_copy_is_deduplicated_without_hiding_distinct_paths(self) -> None:
        message = "The PlotPlan explicitly uses a non-zero bar baseline."
        path_one = RuntimeIssue(
            "WARNING",
            "plot.axis.nonzero_bar_baseline",
            message,
            "$.panels[0].axes.y.limits",
        )
        path_two = RuntimeIssue(
            "WARNING",
            "plot.axis.nonzero_bar_baseline",
            message,
            "$.panels[1].axes.y.limits",
        )
        manifest_copy = {
            "severity": "WARNING",
            "code": "plot.axis.nonzero_bar_baseline",
            "message": message,
        }
        deduplicated = plot_inspect._dedupe_runtime_issues(
            [manifest_copy, path_one, path_two]
        )
        self.assertEqual([path_one, path_two], deduplicated)


@unittest.skipUnless(HAS_MATPLOTLIB, "Matplotlib optional runtime is unavailable")
class PlotInspectionTests(unittest.TestCase):
    def prepare(self, root: Path) -> tuple[Path, Path, Path]:
        spec = write_plot_spec(root)
        data = write_line_data(root)
        plan_path, _ = valid_line_plan(root, spec, data)
        source = matplotlib_backend.author_plot_source(plan_path)
        manifest = root / "manifest.json"
        result = matplotlib_backend.export_matplotlib(
            plan_path=plan_path,
            source_path=source,
            output_dir=root / "artifacts",
            manifest_path=manifest,
            strict_lint=True,
        )
        if not result.success:
            raise AssertionError(result.manifest)
        return plan_path, source, manifest

    def test_full_plot_inspection_passes_without_ocr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, source, manifest = self.prepare(root)
            result = plot_inspect.inspect_plot(
                plan_path=plan,
                source_path=source,
                manifest_path=manifest,
                qa_path=root / "qa.json",
            )
        self.assertTrue(result.passed, result.report["issues"])
        self.assertEqual("AUTOMATED_CHECKS_PASSED", result.report["outcome"])
        self.assertEqual("AUTOMATED_EXECUTION", result.report["assessment_scope"])
        self.assertEqual("NOT_PERFORMED", result.report["human_review_status"])
        self.assertFalse(result.report["metadata"]["ocr_used"])

    def test_artifact_hash_mutation_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, source, manifest_path = self.prepare(root)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            svg = next(item for item in manifest["artifacts"] if item["format"] == "svg")
            svg_path = (manifest_path.parent / svg["path"]).resolve()
            with svg_path.open("a", encoding="utf-8") as handle:
                handle.write("\n")
            result = plot_inspect.inspect_plot(
                plan_path=plan,
                source_path=source,
                manifest_path=manifest_path,
                qa_path=root / "qa.json",
            )
        self.assertEqual("BLOCKED", result.report["outcome"])
        self.assertIn("technical.artifact.hash_mismatch", {item["code"] for item in result.report["issues"]})

    def test_resolved_trace_drift_blocks_even_with_updated_trace_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, source, manifest_path = self.prepare(root)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            trace_ref = manifest["metadata"]["resolved_trace"]
            trace_path = (manifest_path.parent / trace_ref["path"]).resolve()
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            trace["panels"][0]["series"][0]["data_digest"] = "0" * 64
            trace_path.write_text(json.dumps(trace, indent=2) + "\n", encoding="utf-8")
            trace_ref["sha256"] = sha256_file(trace_path)
            trace_ref["size_bytes"] = trace_path.stat().st_size
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            result = plot_inspect.inspect_plot(
                plan_path=plan,
                source_path=source,
                manifest_path=manifest_path,
                qa_path=root / "qa.json",
            )
        self.assertEqual("BLOCKED", result.report["outcome"])
        self.assertIn(
            "scientific.data.execution_trace_mismatch",
            {item["code"] for item in result.report["issues"]},
        )

    def test_missing_manifest_input_provenance_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, source, manifest_path = self.prepare(root)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["metadata"]["inputs"] = []
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            result = plot_inspect.inspect_plot(
                plan_path=plan,
                source_path=source,
                manifest_path=manifest_path,
                qa_path=root / "qa.json",
            )
        self.assertEqual("BLOCKED", result.report["outcome"])
        self.assertIn(
            "plot.output.input_provenance_missing",
            {item["code"] for item in result.report["issues"]},
        )

    def test_missing_planned_svg_label_blocks_even_when_hash_is_updated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, source, manifest_path = self.prepare(root)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            record = next(item for item in manifest["artifacts"] if item["format"] == "svg")
            svg_path = (manifest_path.parent / record["path"]).resolve()
            tree = ET.parse(svg_path)
            label = next(
                node
                for node in tree.getroot().iter()
                if node.tag.rsplit("}", 1)[-1] == "text"
                and "Model A" in "".join(node.itertext())
            )
            label.text = "Model X"
            for child in list(label):
                label.remove(child)
            tree.write(svg_path, encoding="utf-8", xml_declaration=True)
            record["sha256"] = sha256_file(svg_path)
            record["size_bytes"] = svg_path.stat().st_size
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            result = plot_inspect.inspect_plot(
                plan_path=plan,
                source_path=source,
                manifest_path=manifest_path,
                qa_path=root / "qa.json",
            )
        self.assertEqual("BLOCKED", result.report["outcome"])
        self.assertIn(
            "plot.output.planned_label_missing",
            {item["code"] for item in result.report["issues"]},
        )

    def test_manifest_only_update_cannot_conceal_added_svg_scientific_mark(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, source, manifest_path = self.prepare(root)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            record = next(item for item in manifest["artifacts"] if item["format"] == "svg")
            svg_path = (manifest_path.parent / record["path"]).resolve()
            tree = ET.parse(svg_path)
            axes = next(
                node
                for node in tree.getroot().iter()
                if node.attrib.get("id") == "axes_1"
            )
            extra = ET.SubElement(axes, "{http://www.w3.org/2000/svg}path")
            extra.set("d", "M 10 100 L 20 100 L 20 1 L 10 1 z")
            extra.set("style", "fill: #2f6fb6")
            tree.write(svg_path, encoding="utf-8", xml_declaration=True)
            record["sha256"] = sha256_file(svg_path)
            record["size_bytes"] = svg_path.stat().st_size
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            result = plot_inspect.inspect_plot(
                plan_path=plan,
                source_path=source,
                manifest_path=manifest_path,
                qa_path=root / "qa.json",
            )
        self.assertEqual("BLOCKED", result.report["outcome"])
        self.assertIn(
            "scientific.data.artifact_trace_mismatch",
            {item["code"] for item in result.report["issues"]},
        )
        artifact_check = next(
            item for item in result.report["checks"] if item["id"] == "plot.artifacts"
        )
        self.assertEqual("FAIL", artifact_check["status"])

    def test_embedded_pdf_raster_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, source, manifest_path = self.prepare(root)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            record = next(item for item in manifest["artifacts"] if item["format"] == "pdf")
            pdf_path = (manifest_path.parent / record["path"]).resolve()
            with pdf_path.open("ab") as handle:
                handle.write(b"\n% /Subtype /Image intentional regression marker\n")
            record["sha256"] = sha256_file(pdf_path)
            record["size_bytes"] = pdf_path.stat().st_size
            trace_ref = manifest["metadata"]["resolved_trace"]
            trace_path = (manifest_path.parent / trace_ref["path"]).resolve()
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            trace_record = next(
                item for item in trace["artifact_outputs"] if item["format"] == "pdf"
            )
            trace_record["sha256"] = record["sha256"]
            trace_record["size_bytes"] = record["size_bytes"]
            trace_path.write_text(json.dumps(trace, indent=2) + "\n", encoding="utf-8")
            trace_ref["sha256"] = sha256_file(trace_path)
            trace_ref["size_bytes"] = trace_path.stat().st_size
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            result = plot_inspect.inspect_plot(
                plan_path=plan,
                source_path=source,
                manifest_path=manifest_path,
                qa_path=root / "qa.json",
            )
        self.assertEqual("REVISION_REQUIRED", result.report["outcome"])
        self.assertIn(
            "plot.output.pdf_raster_embedded",
            {item["code"] for item in result.report["issues"]},
        )

    def test_grayscale_indistinguishable_series_is_advisory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = write_plot_spec(root)
            data = write_line_data(root)
            plan_path, plan = valid_line_plan(root, spec, data)
            for series in plan["panels"][0]["series"]:
                series.update(color="#666666", marker="o", line_style="-")
            plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
            source = matplotlib_backend.author_plot_source(plan_path)
            manifest_path = root / "manifest.json"
            export = matplotlib_backend.export_matplotlib(
                plan_path=plan_path,
                source_path=source,
                output_dir=root / "artifacts",
                manifest_path=manifest_path,
                strict_lint=True,
            )
            self.assertTrue(export.success, export.manifest["issues"])
            result = plot_inspect.inspect_plot(
                plan_path=plan_path,
                source_path=source,
                manifest_path=manifest_path,
                qa_path=root / "qa.json",
            )
        self.assertEqual("REVISION_REQUIRED", result.report["outcome"])
        issue = next(
            item
            for item in result.report["issues"]
            if item["code"] == "plot.style.grayscale_indistinguishable"
        )
        self.assertEqual("MINOR", issue["severity"])


if __name__ == "__main__":
    unittest.main()
