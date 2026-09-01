from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from figure_runtime import sha256_file
from plot_plan import SECTION_REQUIREMENTS, extract_plot_requirements


def write_plot_spec(root: Path, figure_id: str = "F910") -> Path:
    path = root / f"{figure_id}-validation-accuracy.md"
    path.write_text(
        f'''---
spec_version: "1.0"
figure_id: "{figure_id}"
working_title: "Validation Accuracy"
status: "READY"
outputs:
  source: null
  vector: null
  preview: null
---

# Scientific Figure Specification

# 1. Figure Identity

**Primary Archetype:** Results

**Secondary Archetype(s):** Diagnostics

# 2. Scientific Purpose

## 2.1 Core Message

Compare validation accuracy trajectories for two declared models using authoritative plotting data and precomputed uncertainty.

## 2.2 Intended Reader Takeaway

Readers should see how the two model trajectories differ across the recorded epochs.

## 2.3 Role in the Paper

Quantitative result supporting the model comparison.

# 3. Required Content

## 3.1 Must Show

- Model A and Model B validation accuracy across epochs with precomputed 95% confidence intervals.

## 3.2 Exact Scientific Content

- Model A
- Model B
- 95% CI

## 3.3 Source Binding

- Values and uncertainty → authoritative local plotting table.

## 3.4 Optional / Removable Content

- Minor grid lines may be removed.

## 3.5 Assumptions / Open Questions

- None.

# 4. Scientific Structure & Relationships

## 4.1 Relationships

- Epoch is encoded on x and validation accuracy on y for each model. Relation: quantitative x/y encoding.

# 5. Figure Design

## 5.1 Reading Order

Read the two trajectories from left to right across increasing epochs.

## 5.2 Composition

Use one conventional line-plot panel with a compact legend.

## 5.3 Primary Visual Anchor

The two validation accuracy trajectories and their uncertainty bands.

## 5.4 Information Hierarchy

### Primary

- The model trajectories.

### Secondary

- Precomputed uncertainty.

### Supporting

- Axis ticks and restrained grid lines.

## 5.5 Simplification & Redundancy

- Do not duplicate the result in decorative panels.

# 6. Visual & Content Constraints

## 6.1 Visual Semantics

- Use distinct line styles and markers as well as restrained color.

## 6.2 Required Figure Labels

- Epoch.
- Validation Accuracy.
- Model A.
- Model B.

## 6.3 Must Not Imply / Avoid

- Do not interpolate across missing observations or infer statistical significance.

# 7. References & Rendering Requirements

## 7.1 References

None required.

## 7.2 Cross-Figure Consistency

- Keep model colors and naming consistent with related result figures.

## 7.3 Rendering Requirements

**Intended Use:** Double-column result figure.

**Target Size / Aspect Ratio:** 180 mm x 100 mm.

**Preferred Backend:** Matplotlib.

**Required Outputs:** Reproducible Python source, SVG, PDF, and PNG.
''',
        encoding="utf-8",
    )
    return path


def write_line_data(root: Path, *, include_gap: bool = True) -> Path:
    path = root / "line-results.csv"
    rows = [
        ["epoch", "model", "accuracy", "ci_low", "ci_high"],
        [1, "Model A", 0.70, 0.67, 0.73],
        [2, "Model A", 0.76, 0.73, 0.79],
        [3, "Model A", 0.80, 0.77, 0.83],
        [1, "Model B", 0.66, 0.63, 0.69],
        [2, "Model B", "" if include_gap else 0.71, "" if include_gap else 0.68, "" if include_gap else 0.74],
        [3, "Model B", 0.75, 0.72, 0.78],
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(rows)
    return path


def _coverage(spec_path: Path) -> dict[str, Any]:
    requirements = extract_plot_requirements(spec_path)
    mappings = {
        "must_show": [
            {"kind": "panel", "ids": ["P1"]},
            {"kind": "series", "ids": ["P1", "model-a"]},
            {"kind": "series", "ids": ["P1", "model-b"]},
            {"kind": "data_binding", "ids": ["results"]},
        ],
        "relationships": [
            {"kind": "axis", "ids": ["P1", "x"]},
            {"kind": "axis", "ids": ["P1", "y"]},
        ],
        "required_labels": [
            {"kind": "axis", "ids": ["P1", "x"]},
            {"kind": "axis", "ids": ["P1", "y"]},
            {"kind": "legend", "ids": ["P1"]},
        ],
        "must_not_imply": [{"kind": "panel", "ids": ["P1"]}],
    }
    coverage: dict[str, Any] = {}
    for section, title in SECTION_REQUIREMENTS.items():
        coverage[section] = [
            {
                "id": f"{section.replace('_', '-')}-{index:03d}",
                "source_ref": f"{title}[{index}]",
                "source_text": text,
                "status": "MAPPED",
                "representations": mappings[section],
            }
            for index, text in enumerate(requirements[section], start=1)
        ]
    summary: dict[str, int] = {}
    for section in SECTION_REQUIREMENTS:
        summary[f"{section}_total"] = len(coverage[section])
        summary[f"{section}_mapped"] = len(coverage[section])
    summary["unresolved_total"] = 0
    coverage["status"] = "COMPLETE"
    coverage["summary"] = summary
    return coverage


def valid_line_plan(
    root: Path,
    spec_path: Path,
    data_path: Path,
    *,
    formats: list[str] | None = None,
) -> tuple[Path, dict[str, Any]]:
    plan_path = root / "F910.plot-plan.json"
    plan = {
        "schema_version": "1.0",
        "plan_id": "F910-matplotlib-v1",
        "figure_id": "F910",
        "backend": "matplotlib",
        "figure_spec": {
            "path": spec_path.name,
            "sha256": sha256_file(spec_path),
            "spec_version": "1.0",
            "figure_id": "F910",
        },
        "target": {
            "width": 180,
            "height": 100,
            "unit": "mm",
            "dpi": 150,
            "minimum_text_size_pt": 6.5,
        },
        "data_sources": [
            {
                "id": "results",
                "path": data_path.name,
                "format": "csv",
                "sha256": sha256_file(data_path),
                "role": "authoritative_plot_data",
            }
        ],
        "spec_coverage": _coverage(spec_path),
        "layout": {"rows": 1, "columns": 1, "shared_legend": False},
        "panels": [
            {
                "id": "P1",
                "plot_type": "line",
                "data_source": "results",
                "title": "Validation Accuracy",
                "grid": {"row": 0, "column": 0},
                "encoding": {"x": "epoch", "y": "accuracy", "group": "model"},
                "series": [
                    {
                        "id": "model-a",
                        "label": "Model A",
                        "filter": {"column": "model", "operator": "eq", "value": "Model A"},
                        "color": "#2F6FB6",
                        "marker": "o",
                        "line_style": "-",
                    },
                    {
                        "id": "model-b",
                        "label": "Model B",
                        "filter": {"column": "model", "operator": "eq", "value": "Model B"},
                        "color": "#C56B2D",
                        "marker": "s",
                        "line_style": "--",
                    },
                ],
                "axes": {
                    "x": {"label": "Epoch", "unit": None, "scale": "linear"},
                    "y": {"label": "Validation Accuracy", "unit": None, "scale": "linear", "limits": [0, 1]},
                },
                "legend": {"mode": "panel", "title": None, "location": "lower right"},
                "annotations": [],
                "reference_lines": [],
                "missing_policy": "gap",
                "uncertainty": {"kind": "95% CI", "lower_column": "ci_low", "upper_column": "ci_high"},
                "sort_by": "epoch",
            }
        ],
        "style_profile": "publication-default",
        "outputs": {
            "source": "F910-validation-accuracy.plot.py",
            "formats": formats or ["svg", "pdf", "png"],
            "manifest": "F910-validation-accuracy.manifest.json",
            "qa_report": "F910-validation-accuracy.qa.json",
            "trace": "F910-validation-accuracy.plot-trace.json",
        },
        "checks": {
            "grayscale_distinguishability": True,
            "vector_text": True,
            "data_binding": True,
        },
        "metadata": {"fixture": True},
    }
    plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return plan_path, plan
