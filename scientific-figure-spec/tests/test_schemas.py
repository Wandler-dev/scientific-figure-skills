from __future__ import annotations

import json
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = SKILL_ROOT / "schemas"


class ExecutionSchemaTests(unittest.TestCase):
    def load(self, name: str) -> dict:
        return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))

    def test_all_sidecar_schemas_are_valid_json_schema_documents(self) -> None:
        for name in (
            "render-plan.schema.json",
            "plot-plan.schema.json",
            "artifact-manifest.schema.json",
            "qa-report.schema.json",
        ):
            with self.subTest(name=name):
                schema = self.load(name)
                self.assertEqual(
                    "https://json-schema.org/draft/2020-12/schema",
                    schema["$schema"],
                )
                self.assertTrue(
                    schema["$id"].startswith(
                        "https://scientific-figure-skills.local/schemas/"
                    )
                )
                self.assertEqual("object", schema["type"])
                self.assertFalse(schema["additionalProperties"])

    def test_render_plan_keeps_figure_spec_compatibility_boundary(self) -> None:
        schema = self.load("render-plan.schema.json")
        self.assertEqual("1.1", schema["properties"]["schema_version"]["const"])
        spec = schema["properties"]["figure_spec"]["properties"]
        self.assertEqual("1.0", spec["spec_version"]["const"])
        self.assertIn("spec_coverage", schema["required"])
        self.assertIn("semantic_assertions", schema["required"])
        self.assertIn("final_size", schema["required"])

    def test_qa_schema_preserves_existing_taxonomy(self) -> None:
        schema = self.load("qa-report.schema.json")
        outcomes = schema["properties"]["outcome"]["enum"]
        categories = schema["$defs"]["qa_issue"]["properties"]["category"]["enum"]
        self.assertIn("AUTOMATED_CHECKS_PASSED", outcomes)
        self.assertIn("PASS", outcomes)
        self.assertIn("REVISION_REQUIRED", outcomes)
        self.assertIn("BLOCKED", outcomes)
        self.assertEqual(
            "AUTOMATED_EXECUTION",
            schema["properties"]["assessment_scope"]["const"],
        )
        self.assertEqual(
            ["Scientific", "Communication", "Visual", "Technical"],
            categories,
        )

    def test_plot_plan_is_parallel_to_render_plan(self) -> None:
        schema = self.load("plot-plan.schema.json")
        self.assertEqual("1.0", schema["properties"]["schema_version"]["const"])
        self.assertEqual("matplotlib", schema["properties"]["backend"]["const"])
        self.assertIn("data_sources", schema["required"])
        self.assertIn("panels", schema["required"])
        self.assertNotIn("elements", schema["properties"])
        self.assertNotIn("connectors", schema["properties"])


if __name__ == "__main__":
    unittest.main()
