from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_ROOT / "scripts"
TESTS = Path(__file__).resolve().parent
import sys

sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(SCRIPTS))

from plot_test_utils import valid_line_plan, write_line_data, write_plot_spec
import matplotlib_backend


HAS_MATPLOTLIB = importlib.util.find_spec("matplotlib") is not None


@unittest.skipUnless(HAS_MATPLOTLIB, "Matplotlib optional runtime is unavailable")
class MatplotlibBackendTests(unittest.TestCase):
    def prepare(self, root: Path) -> tuple[Path, Path]:
        spec = write_plot_spec(root)
        data = write_line_data(root)
        plan_path, _ = valid_line_plan(root, spec, data)
        source = matplotlib_backend.author_plot_source(plan_path)
        return plan_path, source

    def test_authoring_creates_thin_hash_pinned_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan_path, source = self.prepare(Path(tmp))
            text = source.read_text(encoding="utf-8")
            lint = matplotlib_backend.lint_plot_source(source, plan_path=plan_path)
        self.assertIn("EXPECTED_PLOT_PLAN_SHA256", text)
        self.assertIn("execute_generated_source", text)
        self.assertNotIn("matplotlib.pyplot", text)
        self.assertTrue(matplotlib_backend.plot_source_lint_passed(lint, strict=True))

    def test_source_detects_plotplan_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan_path, source = self.prepare(Path(tmp))
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["metadata"]["changed"] = True
            plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
            lint = matplotlib_backend.lint_plot_source(source, plan_path=plan_path)
        self.assertIn("plot.source.plan_hash_mismatch", {item.code for item in lint.issues})

    def test_source_detects_manual_runner_logic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan_path, source = self.prepare(Path(tmp))
            with source.open("a", encoding="utf-8") as handle:
                handle.write("\nprint('manual execution drift')\n")
            lint = matplotlib_backend.lint_plot_source(source, plan_path=plan_path)
        self.assertIn("plot.source.runner_drift", {item.code for item in lint.issues})

    def test_real_export_records_source_data_and_all_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, source = self.prepare(root)
            result = matplotlib_backend.export_matplotlib(
                plan_path=plan_path,
                source_path=source,
                output_dir=root / "artifacts",
                manifest_path=root / "manifest.json",
                strict_lint=True,
            )
            artifacts = {item["format"]: item for item in result.manifest["artifacts"]}
            svg_path = root / "artifacts" / "F910-validation-accuracy.svg"
            svg_root = ET.parse(svg_path).getroot()
            text_nodes = [node for node in svg_root.iter() if node.tag.rsplit("}", 1)[-1] == "text"]
        self.assertTrue(result.success, result.manifest["issues"])
        self.assertEqual({"svg", "pdf", "png"}, set(artifacts))
        self.assertEqual("matplotlib", result.manifest["exporter"]["backend"])
        self.assertTrue(result.manifest["exporter"]["version"])
        self.assertEqual("results", result.manifest["metadata"]["inputs"][0]["id"])
        self.assertIsNotNone(result.manifest["metadata"]["resolved_trace"])
        self.assertTrue(result.manifest["metadata"]["font_resolution"]["resolved_name"])
        self.assertTrue(text_nodes)
        self.assertTrue(all("dimensions" in item for item in artifacts.values()))

    def test_direct_export_reports_missing_optional_matplotlib_capability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, source = self.prepare(root)
            with patch("matplotlib_backend.importlib.util.find_spec", return_value=None):
                with self.assertRaisesRegex(
                    matplotlib_backend.MatplotlibBackendError,
                    "capability.matplotlib.missing",
                ):
                    matplotlib_backend.export_matplotlib(
                        plan_path=plan_path,
                        source_path=source,
                        output_dir=root / "artifacts",
                        manifest_path=root / "manifest.json",
                    )

    def test_scoped_style_does_not_mutate_global_rcparams(self) -> None:
        import matplotlib

        before = matplotlib.rcParams["font.size"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, source = self.prepare(root)
            result = matplotlib_backend.export_matplotlib(
                plan_path=plan_path,
                source_path=source,
                formats=["svg"],
                output_dir=root / "artifacts",
                manifest_path=root / "manifest.json",
            )
        self.assertTrue(result.success, result.manifest["issues"])
        self.assertEqual(before, matplotlib.rcParams["font.size"])

    def test_figure_level_shared_legend_is_authored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = write_plot_spec(root)
            data = write_line_data(root)
            plan_path, plan = valid_line_plan(root, spec, data, formats=["svg"])
            plan["layout"]["shared_legend"] = True
            plan["panels"][0]["legend"]["mode"] = "figure"
            plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
            source = matplotlib_backend.author_plot_source(plan_path)
            result = matplotlib_backend.export_matplotlib(
                plan_path=plan_path,
                source_path=source,
                output_dir=root / "artifacts",
                manifest_path=root / "manifest.json",
                strict_lint=True,
            )
            document = ET.parse(root / "artifacts" / "F910-validation-accuracy.svg").getroot()
            labels = [
                "".join(node.itertext()).strip()
                for node in document.iter()
                if node.tag.rsplit("}", 1)[-1] == "text"
            ]
        self.assertTrue(result.success, result.manifest["issues"])
        self.assertEqual(1, labels.count("Model A"))
        self.assertEqual(1, labels.count("Model B"))


if __name__ == "__main__":
    unittest.main()
