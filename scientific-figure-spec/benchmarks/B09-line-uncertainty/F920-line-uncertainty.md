---
spec_version: "1.0"
figure_id: "F920"
working_title: "Validation Accuracy with Uncertainty"
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

Compare validation accuracy trajectories for Model A and Model B using authoritative values and precomputed 95% confidence intervals.

## 2.2 Intended Reader Takeaway

Readers should see the recorded trajectories, uncertainty, and the missing Model B observation without interpolation.

## 2.3 Role in the Paper

Quantitative result demonstrating a data-bound line plot with uncertainty.

# 3. Required Content

## 3.1 Must Show

- Model A and Model B validation accuracy across epochs with precomputed 95% confidence intervals.

## 3.2 Exact Scientific Content

- Model A
- Model B
- 95% CI

## 3.3 Source Binding

- Values and uncertainty → data.csv.

## 3.4 Optional / Removable Content

- Minor grid lines may be removed.

## 3.5 Assumptions / Open Questions

- None.

# 4. Scientific Structure & Relationships

## 4.1 Relationships

- Epoch is encoded on x and validation accuracy on y for each model. Relation: quantitative x/y encoding.

# 5. Figure Design

## 5.1 Reading Order

Read the trajectories from left to right across increasing epochs.

## 5.2 Composition

Use one conventional line-plot panel with a compact legend.

## 5.3 Primary Visual Anchor

The two trajectories and their uncertainty bands.

## 5.4 Information Hierarchy

### Primary

- Model trajectories.

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

- Keep model names and visual encodings stable.

## 7.3 Rendering Requirements

**Intended Use:** Double-column result figure.

**Target Size / Aspect Ratio:** 180 mm x 100 mm.

**Preferred Backend:** Matplotlib.

**Required Outputs:** Reproducible Python source, SVG, PDF, and PNG.
