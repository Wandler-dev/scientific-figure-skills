from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from figure_runtime import sha256_file
from plot_data import filtered_rows, load_data_source


class PlotDataTests(unittest.TestCase):
    def declaration(self, path: Path, format_name: str) -> dict:
        return {
            "id": "results",
            "path": path.name,
            "format": format_name,
            "sha256": sha256_file(path),
            "role": "authoritative_plot_data",
        }

    def test_tsv_loader_preserves_rows_and_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "results.tsv"
            path.write_text("step\tvalue\n1\t0.5\n2\t0.7\n", encoding="utf-8")
            loaded, issues = load_data_source(
                self.declaration(path, "tsv"), root / "plan.json"
            )
        self.assertEqual([], issues)
        assert loaded is not None
        self.assertEqual(("step", "value"), loaded.columns)
        self.assertEqual(2, loaded.row_count)

    def test_json_records_loader_uses_deterministic_column_union(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "results.json"
            path.write_text(
                json.dumps([{"x": 1, "group": "A"}, {"x": 2, "y": 3}]),
                encoding="utf-8",
            )
            loaded, issues = load_data_source(
                self.declaration(path, "json-records"), root / "plan.json"
            )
        self.assertEqual([], issues)
        assert loaded is not None
        self.assertEqual(("x", "group", "y"), loaded.columns)
        self.assertIsNone(loaded.rows[0]["y"])
        self.assertIsNone(loaded.rows[1]["group"])

    def test_simple_eq_and_in_filters_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "results.csv"
            path.write_text("group,value\nA,1\nB,2\nA,3\n", encoding="utf-8")
            loaded, _ = load_data_source(
                self.declaration(path, "csv"), root / "plan.json"
            )
        assert loaded is not None
        self.assertEqual(
            ["1", "3"],
            [row["value"] for row in filtered_rows(loaded, {"column": "group", "operator": "eq", "value": "A"})],
        )
        self.assertEqual(
            ["1", "2", "3"],
            [row["value"] for row in filtered_rows(loaded, {"column": "group", "operator": "in", "values": ["A", "B"]})],
        )

    def test_malformed_table_is_reported_without_dataframe_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "bad.csv"
            path.write_text("a,b\n1\n", encoding="utf-8")
            loaded, issues = load_data_source(
                self.declaration(path, "csv"), root / "plan.json"
            )
        self.assertIsNone(loaded)
        self.assertIn("plot.data.parse_failed", {item.code for item in issues})


if __name__ == "__main__":
    unittest.main()
