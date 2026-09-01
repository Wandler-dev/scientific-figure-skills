---
spec_version: "1.0"
figure_id: "F922"
working_title: "Task-by-Model Score Heatmap"
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

Show the authoritative score associated with every declared task and model pair.

## 2.2 Intended Reader Takeaway

Readers should compare the task-by-model pattern using one explicitly labeled sequential color scale.

## 2.3 Role in the Paper

Compact quantitative comparison across a small result matrix.

# 3. Required Content

## 3.1 Must Show

- Scores for both models across all three tasks.

## 3.2 Exact Scientific Content

- Model A
- Model B
- Task 1
- Task 2
- Task 3

## 3.3 Source Binding

- Every heatmap cell → data.csv.

## 3.4 Optional / Removable Content

- Cell value labels are optional.

## 3.5 Assumptions / Open Questions

- None.

# 4. Scientific Structure & Relationships

## 4.1 Relationships

- Each cell maps one model and one task to one recorded score. Relation: categorical pair to quantitative value.

# 5. Figure Design

## 5.1 Reading Order

Scan tasks by row and models by column.

## 5.2 Composition

Use one compact heatmap with a separate labeled colorbar.

## 5.3 Primary Visual Anchor

The task-by-model score matrix.

## 5.4 Information Hierarchy

### Primary

- Recorded score pattern.

### Secondary

- Task and model categories.

### Supporting

- Colorbar ticks.

## 5.5 Simplification & Redundancy

- Do not add duplicate result cards.

# 6. Visual & Content Constraints

## 6.1 Visual Semantics

- Use a restrained sequential mapping; no scientific center is asserted.

## 6.2 Required Figure Labels

- Model.
- Task.
- Score.

## 6.3 Must Not Imply / Avoid

- Do not use an undeclared diverging center or invent missing cells.

# 7. References & Rendering Requirements

## 7.1 References

None required.

## 7.2 Cross-Figure Consistency

- Preserve task and model ordering.

## 7.3 Rendering Requirements

**Intended Use:** Single-column diagnostic figure.

**Target Size / Aspect Ratio:** 90 mm x 75 mm.

**Preferred Backend:** Matplotlib.

**Required Outputs:** Reproducible Python source, SVG, PDF, and PNG.
