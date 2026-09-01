---
spec_version: "1.0"
figure_id: "F901"
working_title: "Draw.io Execution Coverage Harness"
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

Provide a scenario-neutral, test-only source contract for B01–B04 plans that verifies explicit FigureSpec coverage binding without presenting an empirical claim.

## 2.2 Intended Reader Takeaway

Every active benchmark scenario must preserve its declared plan-owned elements and relations in an editable, readable artifact.

## 2.3 Role in the Paper

Internal execution regression fixture; not a manuscript figure.

# 3. Required Content

## 3.1 Must Show

- The active scenario's declared plan-owned elements.
- The active scenario's declared plan-owned relationships.
- Editable geometry and labels readable at the declared final size.

## 3.2 Exact Scientific Content

- None

## 3.3 Source Binding

- Scenario content → the corresponding B01–B04 benchmark JSON descriptor.

## 3.4 Optional / Removable Content

- Decorative styling beyond the declared semantic distinctions.

## 3.5 Assumptions / Open Questions

- The harness is synthetic and makes no empirical claim.

# 4. Scientific Structure & Relationships

## 4.1 Relationships

- The active scenario relationships remain attached to their declared endpoints. Relation: scenario-owned execution relation.

# 5. Figure Design

## 5.1 Reading Order

Follow the active benchmark scenario's declared relation order.

## 5.2 Composition

Use a compact landscape canvas with native editable nodes and attached connectors.

## 5.3 Primary Visual Anchor

The active scenario's declared elements and relations.

## 5.4 Information Hierarchy

### Primary

- Plan-owned scenario structure.

### Secondary

- Final-size readability and semantic colors.

### Supporting

- Minimal connector and container styling.

## 5.5 Simplification & Redundancy

- Include only content declared by the active scenario.

# 6. Visual & Content Constraints

## 6.1 Visual Semantics

- Preserve the semantic colors declared by the active benchmark scenario.
- Preserve non-causal connectors as non-directional where declared.

## 6.2 Required Figure Labels

- Scenario-owned labels

## 6.3 Must Not Imply / Avoid

- Do not present the harness as an empirical result.
- Do not embed raster screenshots in place of editable cells.
- Do not shrink labels below the declared final-size threshold.

# 7. References & Rendering Requirements

## 7.1 References

None

## 7.2 Cross-Figure Consistency

- Preserve Candidate, Reference, and Evidence colors when those roles occur.

## 7.3 Rendering Requirements

**Intended Use:** Automated Draw.io integration benchmark.

**Target Size / Aspect Ratio:** Approximately 1.8:1 landscape.

**Preferred Backend:** Draw.io for this explicit tooling fixture only.

**Required Outputs:** Editable Draw.io source plus SVG, PDF, and PNG exports.
