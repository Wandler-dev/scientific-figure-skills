# Scientific Figure Definition Standard v1.0

This document defines the canonical structure for one scientific figure specification.

It is intended for both researchers and AI agents. It records the scientific message, the required content, the relationships that must remain correct, and the design constraints needed to render and revise the figure reliably.

A figure specification is not an image-generation prompt and not a process log.

Its purpose is to answer:

```text
What must the figure communicate?
What must appear exactly?
How are the elements scientifically related?
What visual organization best expresses those relations?
What must the figure avoid implying?
How should the result be delivered?
```

The governing rule is:

> Specify scientific meaning tightly; leave routine implementation flexible.

---

## 1. Canonical Structure

Use these seven top-level sections in this order:

| # | Section | Purpose |
|---|---|---|
| 1 | Figure Identity | Identify the figure and its dominant archetype |
| 2 | Scientific Purpose | State why the figure exists and what the reader should learn |
| 3 | Required Content | Record essential content, exact content, sources, and removable detail |
| 4 | Scientific Structure & Relationships | Define how important elements relate |
| 5 | Figure Design | Define reading order, composition, hierarchy, and simplification |
| 6 | Visual & Content Constraints | Control semantic encodings, exact labels, and misleading implications |
| 7 | References & Rendering Requirements | Record references, cross-figure rules, target use, and outputs |

Additional subsections may be added when the figure genuinely needs them. The seven top-level sections should remain stable.

---

## 2. Canonical Skeleton

```markdown
# 1. Figure Identity
**Primary Archetype:**
**Secondary Archetype(s):**

# 2. Scientific Purpose
## 2.1 Core Message

## 2.2 Intended Reader Takeaway

## 2.3 Role in the Paper

# 3. Required Content
## 3.1 Must Show
-

## 3.2 Exact Scientific Content
-

## 3.3 Source Binding
-

## 3.4 Optional / Removable Content
-

## 3.5 Assumptions / Open Questions
-

# 4. Scientific Structure & Relationships
## 4.1 Relationships
-

# 5. Figure Design
## 5.1 Reading Order

## 5.2 Composition

## 5.3 Primary Visual Anchor

## 5.4 Information Hierarchy
### Primary
-
### Secondary
-
### Supporting
-

## 5.5 Simplification & Redundancy
-

# 6. Visual & Content Constraints
## 6.1 Visual Semantics
-

## 6.2 Required Figure Labels
-

## 6.3 Must Not Imply / Avoid
-

# 7. References & Rendering Requirements
## 7.1 References

## 7.2 Cross-Figure Consistency
-

## 7.3 Rendering Requirements
**Intended Use:**
**Target Size / Aspect Ratio:**
**Preferred Backend:**
**Required Outputs:**
```

A non-applicable optional field may contain `None` or `Not applicable`. Required fields should contain real content rather than placeholders.

---

## 3. Section Guidance

### 3.1 Figure Identity

The stable figure ID and working title live in YAML frontmatter. They should not depend on manuscript numbering.

Use one **Primary Archetype** to determine the overall information architecture. Add one or two secondary archetypes only when they support the main structure.

Examples:

```text
Primary Archetype: Method Overview
Secondary Archetypes: Hierarchy, Evaluation
```

Do not use `Hybrid` as a substitute for deciding what the figure is fundamentally doing.

### 3.2 Scientific Purpose

#### Core Message

Write one concise paragraph about the science, not the appearance.

Weak:

> Draw three blue modules connected by arrows.

Better:

> Show how fixed evidence is reconstructed into a hierarchical event-process representation while keeping structural, temporal, causal, and evidence-traceable information visible.

#### Intended Reader Takeaway

State the one idea a reader should retain after a brief view.

#### Role in the Paper

State the figure's function, such as:

```text
method overview
benchmark construction
evaluation logic
empirical result
mechanism explanation
case study
```

If another figure covers related material, state what is unique here.

### 3.3 Required Content

#### Must Show

List concrete, verifiable content that cannot disappear during simplification.

Weak:

> Show evaluation.

Better:

> Show Candidate EPG, Reference EPG, their alignment, and the four diagnostic dimensions.

At least one Must Show item is required before a figure is considered ready.

#### Exact Scientific Content

Record values, labels, notation, terminology, model names, and other content that must remain exact.

Write `None` when no content requires exact wording.

#### Source Binding

Link exact facts and values to their authoritative source when relevant.

Example:

```text
“3,000 events” → dataset statistics file / paper Section 3.1
“Structural Fidelity” → evaluation definition in paper Section 4
```

Do not copy unsupported facts from a reference image merely because they improve visual completeness.

#### Optional / Removable Content

List supporting material that may be shortened, abstracted, or removed if it competes with the primary message.

#### Assumptions / Open Questions

Record only assumptions that could affect scientific validity or design. Do not create an administrative list of trivial unknowns.

### 3.4 Scientific Structure & Relationships

Define important relations explicitly.

Recommended form:

```text
Fixed Evidence → Reconstruction System
Relation: input / information source

Candidate EPG ↔ Reference EPG
Relation: alignment and comparison, not transformation

Episode contains actions and participants
Relation: hierarchy / containment
```

Common relation types include:

```text
sequence
temporal order
causal relation
transformation
input / output
containment
hierarchy
comparison
alignment
association
evidence support
feedback
branching alternatives
shared component
```

Keep these distinctions explicit:

```text
temporal order ≠ causality
association ≠ causality
comparison ≠ transformation
containment ≠ process flow
alignment ≠ information access
```

If an arrow, enclosure, color, or spatial alignment carries scientific meaning, its meaning must be recoverable from Sections 4 or 6.

### 3.5 Figure Design

#### Reading Order

State the intended path, for example:

```text
left → right
overview → detail
candidate/reference → comparison → diagnostics
past → present → alternative futures
```

#### Composition

Describe major regions, their relative importance, and how they connect. Avoid premature pixel coordinates.

#### Primary Visual Anchor

Identify the object or region that deserves the strongest visual attention. It should match the Core Message.

#### Information Hierarchy

Classify content as Primary, Secondary, or Supporting. The rendered visual hierarchy should follow this classification.

#### Simplification & Redundancy

Every major panel, icon, mini-diagram, label, and repeated object must serve a distinct role.

Ask:

- What new information does this element add?
- Is the same message already communicated elsewhere?
- Does repetition express multiplicity, comparison, variation, progression, or overview-to-detail?
- Would removing the element reduce scientific understanding, structural clarity, or intentional emphasis?

Avoid repeated elements that exist only to fill space, make the method look more complex, or create an AI-infographic appearance.

> If removing an element does not reduce understanding, structure, or intentional emphasis, simplify or remove it.

### 3.6 Visual & Content Constraints

#### Visual Semantics

Define colors, shapes, connectors, and line styles only when they carry meaning.

Example:

```text
Blue = Candidate
Purple = Reference
Gold = Evidence
Solid arrow = observed process
Dashed arrow = hypothetical continuation
```

Critical distinctions should not rely only on color.

#### Required Figure Labels

List text that must appear exactly. Do not add unverified labels, values, model names, or scores for visual balance.

#### Must Not Imply / Avoid

Record risks that could materially distort interpretation.

Examples:

- temporal order must not appear causal;
- Reference must not look like an input to the evaluated system;
- a schematic example must not look like an empirical result;
- uncertain branches must not look deterministic;
- do not invent numerical values;
- avoid dense micro-text;
- avoid dashboard-like cards when they have no scientific grouping role;
- avoid repeated mini-graphs that communicate no new distinction.

Keep this subsection focused on meaningful risks rather than generic aesthetic preferences.

### 3.7 References & Rendering Requirements

For every reference, state:

```text
Source:
Use for:
Do not copy:
```

A style reference may guide palette, typography, line weight, and whitespace without authorizing reuse of its composition or scientific content.

Record cross-figure terminology, semantic colors, node types, and connector meanings when consistency matters.

Rendering requirements should state intended use, target size, preferred backend, and required outputs. The backend follows the scientific design; it does not determine it.

---

## 4. Cross-Section Consistency

Before treating the specification as ready, confirm:

1. Every Must Show item has a place in the design.
2. The Core Message and Primary Visual Anchor emphasize the same scientific focus.
3. Important relationships can be represented without changing their meaning.
4. Exact Scientific Content and Required Figure Labels do not conflict.
5. Source-bound values remain traceable.
6. Visual semantics do not introduce unsupported distinctions.
7. Optional content does not dominate required content.
8. Every major panel has a distinct scientific or communicative role.
9. Repetition carries additional information or meaningful structure.
10. References do not override the current figure's scientific purpose.
11. Rendering requirements are compatible with the intended use.

When a conflict exists, scientific meaning takes priority over visual convenience.

---

## 5. Completeness Standard

A figure definition is ready when another competent researcher or agent can answer:

- Why does the figure exist?
- What is the dominant scientific message?
- What content cannot be omitted?
- Which terms or values must remain exact, and where do they come from?
- How are the important elements related?
- What is the intended reading order and primary visual anchor?
- What should be simplified or removed?
- What must the figure avoid implying?
- What outputs and target medium are required?

A good specification may be short. It needs to remove ambiguities that would materially affect the figure.
