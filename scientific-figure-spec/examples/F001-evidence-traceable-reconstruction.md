---
spec_version: "1.0"
figure_id: "F001"
working_title: "Evidence-Traceable Reconstruction Overview"
status: "READY"
outputs:
  source: null
  vector: null
  preview: null
---

# Scientific Figure Specification

# 1. Figure Identity

**Primary Archetype:** Method Overview

**Secondary Archetype(s):** Evaluation, Hierarchy

# 2. Scientific Purpose

## 2.1 Core Message

Show how fixed multi-source evidence is reconstructed into a hierarchical, evidence-traceable Event-Process Graph and then compared with an independently constructed Reference EPG through interpretable diagnostic dimensions.

## 2.2 Intended Reader Takeaway

The reader should understand that the system is evaluated on structured event-process reconstruction rather than unstructured summarization, and that the Reference EPG is used only in the evaluation stage.

## 2.3 Role in the Paper

Main method and benchmark overview connecting reconstruction, structured representation, and evaluation logic.

# 3. Required Content

## 3.1 Must Show

- Fixed multi-source evidence.
- AI reconstruction system.
- Candidate EPG as the system output.
- Reference EPG as an independently constructed comparison target.
- Candidate–Reference alignment or comparison.
- Structural, Temporal, Causal, and Evidence Fidelity diagnostics.
- A compact indication that the EPG is hierarchical and evidence-traceable.

## 3.2 Exact Scientific Content

- Candidate EPG
- Reference EPG
- Structural Fidelity
- Temporal Fidelity
- Causal Fidelity
- Evidence Fidelity

## 3.3 Source Binding

- Terminology and evaluation dimensions → paper method and evaluation sections.
- Candidate / Reference separation → benchmark evaluation protocol.

## 3.4 Optional / Removable Content

- Representative internal nodes inside each EPG.
- Small source-type icons inside the evidence region.
- A compact normalization or alignment substep if space permits.

## 3.5 Assumptions / Open Questions

- The figure is conceptual and should not display numerical benchmark scores.

# 4. Scientific Structure & Relationships

## 4.1 Relationships

- Fixed Evidence → AI Reconstruction System. Relation: input / information source.
- AI Reconstruction System → Candidate EPG. Relation: generated system output.
- Reference EPG is constructed independently of the evaluated system. Relation: external comparison target.
- Candidate EPG ↔ Reference EPG. Relation: alignment and comparison, not transformation or model input.
- Candidate–Reference comparison → Four Fidelity Diagnostics. Relation: evaluation output.
- Evidence supports EPG content through provenance links. Relation: evidence support, visually subordinate to primary process flow.

# 5. Figure Design

## 5.1 Reading Order

Left to right: fixed evidence → reconstruction → Candidate EPG; then Candidate and Reference are compared in a visually separate evaluation region; diagnostics appear at the far right or bottom-right.

## 5.2 Composition

Use three major regions. A compact evidence region occupies the left. The reconstruction system and Candidate EPG form the dominant center. A separate evaluation region aligns Candidate and Reference representations and leads to four concise diagnostic labels. Keep the Reference outside the reconstruction path.

## 5.3 Primary Visual Anchor

The Candidate EPG and its evidence-traceable hierarchical structure.

## 5.4 Information Hierarchy

### Primary

- Fixed evidence to Candidate EPG reconstruction story.
- Candidate / Reference separation and evaluation relationship.

### Secondary

- Four fidelity diagnostics.
- Hierarchical and evidence-traceable nature of the EPG.

### Supporting

- Representative evidence cards.
- Simplified internal nodes and edges.
- Optional alignment or normalization cue.

## 5.5 Simplification & Redundancy

- Use only a few representative evidence cards rather than many repeated document icons.
- Show simplified graph structure rather than a dense miniature graph.
- Present the four diagnostics as concise aligned labels rather than four decorative cards with redundant illustrations.
- Do not repeat the Candidate EPG in several panels unless the repetition is required for aligned comparison.

# 6. Visual & Content Constraints

## 6.1 Visual Semantics

- Evidence uses a restrained gold accent.
- Candidate uses blue.
- Reference uses purple.
- Reconstruction flow uses solid directional arrows.
- Candidate–Reference comparison uses a distinct non-causal comparison connector.
- Provenance links are thinner and visually subordinate.

## 6.2 Required Figure Labels

- Fixed Evidence
- AI Reconstruction
- Candidate EPG
- Reference EPG
- Structural Fidelity
- Temporal Fidelity
- Causal Fidelity
- Evidence Fidelity

## 6.3 Must Not Imply / Avoid

- Do not imply that the Reference EPG is available to the AI reconstruction system.
- Do not imply that temporal relations are automatically causal.
- Do not invent model names, numerical scores, or dataset statistics.
- Avoid a dashboard-like layout with many equal-weight cards.
- Avoid repeated icons or mini-graphs that add no new information.
- Avoid dense micro-text that fails at double-column size.

# 7. References & Rendering Requirements

## 7.1 References

None required for the example.

## 7.2 Cross-Figure Consistency

- Preserve project-wide Candidate = blue, Reference = purple, Evidence = gold semantics.
- Use the paper's exact EPG terminology.

## 7.3 Rendering Requirements

**Intended Use:** Double-column main-paper method overview.

**Target Size / Aspect Ratio:** Approximately 1.8:1 landscape; all labels readable at final paper width.

**Preferred Backend:** SVG, with editable text and native connectors.

**Required Outputs:** Editable SVG source, vector SVG or PDF export, and PNG preview.
