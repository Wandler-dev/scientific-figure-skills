---
spec_version: "1.0"
figure_id: "F921"
working_title: "Grouped Metric Comparison"
status: "READY"
outputs:
  source: null
  vector: null
  preview: null
---

# Scientific Figure Specification

# 1. Figure Identity

**Primary Archetype:** Results

**Secondary Archetype(s):** Comparison

# 2. Scientific Purpose

## 2.1 Core Message

Compare Model A and Model B on two declared metrics using authoritative values and precomputed standard deviations.

## 2.2 Intended Reader Takeaway

Readers should compare exact model values within each metric without an exaggerated axis.

## 2.3 Role in the Paper

Compact quantitative comparison across metrics.

# 3. Required Content

## 3.1 Must Show

- Model A and Model B values for Accuracy and F1 with precomputed standard-deviation error bars.

## 3.2 Exact Scientific Content

- Accuracy
- F1
- Model A
- Model B

## 3.3 Source Binding

- Bar values and error bars → data.csv.

## 3.4 Optional / Removable Content

- Numeric labels on every bar are optional.

## 3.5 Assumptions / Open Questions

- None.

# 4. Scientific Structure & Relationships

## 4.1 Relationships

- Metrics group the two model values. Relation: within-category comparison.

# 5. Figure Design

## 5.1 Reading Order

Read each metric group, then compare the two models within it.

## 5.2 Composition

Use one grouped bar panel with a compact legend and zero baseline.

## 5.3 Primary Visual Anchor

The within-metric differences between Model A and Model B.

## 5.4 Information Hierarchy

### Primary

- Grouped metric values.

### Secondary

- Precomputed uncertainty.

### Supporting

- Category labels and legend.

## 5.5 Simplification & Redundancy

- Do not add decorative value cards.

# 6. Visual & Content Constraints

## 6.1 Visual Semantics

- Distinguish models using color and hatch while retaining a zero baseline.

## 6.2 Required Figure Labels

- Metric.
- Score.
- Model A.
- Model B.

## 6.3 Must Not Imply / Avoid

- Do not truncate the bar baseline or invent significance claims.

# 7. References & Rendering Requirements

## 7.1 References

None required.

## 7.2 Cross-Figure Consistency

- Preserve model naming across result figures.

## 7.3 Rendering Requirements

**Intended Use:** Single-column result figure.

**Target Size / Aspect Ratio:** 90 mm x 75 mm.

**Preferred Backend:** Matplotlib.

**Required Outputs:** Reproducible Python source, SVG, PDF, and PNG.
