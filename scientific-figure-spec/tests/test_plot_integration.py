from __future__ import annotations

import importlib.util
import json
import os
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

from plot_test_utils import valid_line_plan, write_line_data, write_plot_spec


HAS_MATPLOTLIB = importlib.util.find_spec("matplotlib") is not None


class PlotCliIntegrationTests(unittest.TestCase):
    def test_matplotlib_preflight_reports_real_optional_capability(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "figure.py"),
                "preflight",
                "--backend",
                "matplotlib",
                "--operation",
                "render",
                "--json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(HAS_MATPLOTLIB, payload["ready"])
        if HAS_MATPLOTLIB:
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertTrue(payload["matplotlib"]["version"])
        else:
            self.assertEqual(2, completed.returncode)
            self.assertIn(
                "capability.matplotlib.missing",
                {item["code"] for item in payload["issues"]},
            )

    @unittest.skipUnless(HAS_MATPLOTLIB, "Matplotlib optional runtime is unavailable")
    def test_unified_cli_runs_complete_quantitative_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = write_plot_spec(root)
            data = write_line_data(root)
            plan, _ = valid_line_plan(root, spec, data)
            work = root / "work"
            environment = os.environ.copy()
            environment["MPLCONFIGDIR"] = str(root / "mplconfig")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "figure.py"),
                    "render",
                    str(plan),
                    "--backend",
                    "matplotlib",
                    "--work-dir",
                    str(work),
                    "--json",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
                timeout=60,
            )
            payload = json.loads(completed.stdout)
            qa = json.loads(Path(payload["qa_path"]).read_text(encoding="utf-8"))
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertTrue(payload["success"])
        self.assertEqual("matplotlib", payload["backend"])
        self.assertEqual("COMPLETE", payload["binding_status"])
        self.assertEqual("COMPLETED", payload["export_status"])
        self.assertEqual("AUTOMATED_CHECKS_PASSED", payload["qa_outcome"])
        self.assertEqual("NOT_PERFORMED", qa["human_review_status"])

    def test_matplotlib_repair_is_explicitly_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "F910.plot.py"
            source.write_text("# placeholder\n", encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "figure.py"),
                    "repair",
                    str(source),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(2, completed.returncode)
        self.assertIn("capability.operation.unavailable", completed.stderr)


if __name__ == "__main__":
    unittest.main()
