---
spec_version: "1.0"
figure_id: "F900"
working_title: "Draw.io Tooling Benchmark Fixtures"
status: "READY"
outputs:
  source: null
  vector: null
  preview: null
---

# Scientific Figure Specification

# 1. Figure Identity

**Primary Archetype:** Workflow / Pipeline

**Secondary Archetype(s):** Evaluation, Comparison

# 2. Scientific Purpose

## 2.1 Core Message

Provide a synthetic, explicitly test-only scientific diagram vocabulary for verifying that the Draw.io execution loop preserves required labels, directed workflow relations, Candidate/Reference isolation, editable geometry, and final-size readability.

## 2.2 Intended Reader Takeaway

The fixture is a tooling contract, not an empirical result: valid source and exports must preserve the declared structure, while leakage, broken geometry, and unreadable labels must be detected.

## 2.3 Role in the Paper

Internal regression and integration benchmark; not a manuscript figure.

# 3. Required Content

## 3.1 Must Show

- A directed input-to-system-to-output workflow.
- A Candidate and Reference comparison that keeps Reference outside the AI System input path.
- Plan-owned nodes and connectors with editable geometry.
- Labels that remain readable at the declared final size.

## 3.2 Exact Scientific Content

- None

## 3.3 Source Binding

- Tooling behavior → the bundled benchmark scenario JSON files and integration tests.

## 3.4 Optional / Removable Content

- Decorative styling beyond the minimal semantic distinctions.

## 3.5 Assumptions / Open Questions

- The fixture uses synthetic labels and does not represent a real experiment or result.

# 4. Scientific Structure & Relationships

## 4.1 Relationships

- Input Evidence → Processing System. Relation: input / information source.
- Processing System → Structured Output. Relation: generated output.
- AI System → Candidate. Relation: generated output.
- Candidate ↔ Reference. Relation: alignment and comparison.
- Candidate–Reference comparison → Diagnostic. Relation: evaluation output.
- Source Node → Target Node. Relation: directed workflow.

# 5. Figure Design

## 5.1 Reading Order

Left to right for workflows; Candidate and Reference align before the Diagnostic.

## 5.2 Composition

Use a compact landscape canvas with large native nodes, attached connectors, and enough whitespace to make geometry defects unambiguous.

## 5.3 Primary Visual Anchor

The declared workflow or Candidate/Reference comparison for the active benchmark scenario.

## 5.4 Information Hierarchy

### Primary

- Required nodes and semantic relations.

### Secondary

- Final-size text and semantic colors.

### Supporting

- Minimal container and connector styling.

## 5.5 Simplification & Redundancy

- Use only the nodes needed by each scenario.
- Do not add repeated icons, decorative cards, or untested content.

# 6. Visual & Content Constraints

## 6.1 Visual Semantics

- Candidate uses blue.
- Reference uses purple.
- Evidence uses gold.
- Non-causal comparison connectors are dashed and non-directional.

## 6.2 Required Figure Labels

- Input Evidence
- Processing System
- Structured Output
- AI System
- Candidate
- Reference
- Diagnostic
- Source Node
- Target Node
- Compact Panel A
- Compact Panel B

## 6.3 Must Not Imply / Avoid

- Do not imply that Reference is available to the AI System.
- Do not embed raster screenshots in place of editable cells.
- Do not shrink required labels below the declared final-size threshold.
- Do not present the fixture as an empirical result.

# 7. References & Rendering Requirements

## 7.1 References

None

## 7.2 Cross-Figure Consistency

- Preserve Candidate = blue, Reference = purple, and Evidence = gold in relevant scenarios.

## 7.3 Rendering Requirements

**Intended Use:** Automated Draw.io integration benchmark.

**Target Size / Aspect Ratio:** Approximately 1.8:1 landscape.

**Preferred Backend:** Draw.io for this explicit tooling fixture only.

**Required Outputs:** Editable Draw.io source plus SVG, PDF, and PNG exports.
