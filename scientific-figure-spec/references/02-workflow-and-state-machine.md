# Adaptive Figure Workflow v1.0

## 1. Purpose

The workflow should protect scientific meaning without making routine figure work unnecessarily slow.

Version 1.0 therefore follows the user's requested endpoint rather than forcing every figure through a fixed approval sequence.

The practical questions are:

```text
What does the user want now?
Is the scientific meaning sufficiently specified?
Would the next action introduce a material interpretation choice?
Has the actual rendered artifact been inspected?
```

---

## 2. Task Routes

### 2.1 Define

Use when the user asks for a standardized `figure.md`, specification, or review of figure intent.

Output:

```text
FigureSpec
```

Do not render unless requested.

### 2.2 Design

Use when the user asks for layout, composition, visual hierarchy, or a drawing plan.

Output:

```text
FigureSpec with completed design sections
```

Stop before rendering unless the request also asks for a visual artifact.

### 2.3 Render

Use when the user asks to draw, create, render, or produce a first version.

Default flow:

```text
understand
→ define
→ design
→ generate RenderPlan scaffold
→ compare scaffold with FigureSpec Section 5
→ render
→ deterministic lint and artifact inspection
→ visual inspection when available
→ revise obvious defects locally
→ deliver draft
```

Do not insert an approval stop merely because rendering follows design.
The scaffold review is internal and should correct a mechanically uniform layout
when it fails to express the specified reading order, primary anchor,
information hierarchy, or simplification decisions.

### 2.4 Revise

Use when an existing artifact should change.

Establish:

```text
Locked
Change
Flexible
```

Then modify only what the request and necessary supporting adjustments require.

### 2.5 Recreate

Use for high-fidelity reproduction of an available reference.

Measure composition and details, rebuild with editable objects where practical, compare full view and local details, and preserve already-correct elements across iterations.

### 2.6 Plot

Use for real numerical results.

Use authoritative data and reproducible code. Do not manually place values or use generated imagery to imitate a result plot.

Default flow:

```text
read FigureSpec
→ identify authoritative local plotting data
→ create or complete PlotPlan
→ pass FigureSpec coverage and Data Binding Gate
→ review axes, missingness, uncertainty, and visual emphasis
→ author reproducible Python entry point
→ render with Matplotlib
→ inspect trace, manifest, and actual artifacts
→ visually inspect when available
→ apply at most one or two targeted corrections
→ deliver draft
```

The deterministic planner may create an unresolved scaffold, but it must not
guess scientific column meaning. Missing or conflicting data bindings are a
blocker, not permission to invent a value or secretly analyze the data.

---

## 3. Review Gate

Ask for a design decision before rendering only when at least one of the following is true:

- a required scientific fact or relation is missing;
- two incompatible primary messages compete;
- a proposed simplification would remove Must Show content;
- a layout choice would introduce a new causal, temporal, or evidential interpretation;
- the user explicitly asks to review the design first;
- a strict reproduction has a consequential ambiguity not resolvable from the reference;
- a high-stakes exact-data figure has conflicting authoritative inputs.

Do not ask for approval for:

- spacing;
- alignment;
- connector routing;
- minor typography;
- neutral color selection;
- export settings;
- routine backend implementation choices that preserve the design.

A useful rule is:

> Ask when scientific interpretation or major scope is at stake, not when implementation simply requires judgment.

---

## 4. State Transitions

The normal state progression is:

```text
DRAFT → READY → RENDERED → FINAL
```

The workflow is not required to pause at every state.

### From `DRAFT`

Move to `READY` when the specification is sufficiently complete for rendering or deliberate design review.

### From `READY`

Move to `RENDERED` when at least one concrete artifact exists and has been inspected.

### From `RENDERED`

Move to `FINAL` only after explicit author acceptance of the actual artifact.

### Reopening

Use the earliest state that reflects what changed:

```text
minor export or spacing change:
FINAL → RENDERED → FINAL

major design change:
FINAL → READY → RENDERED → FINAL

scientific-purpose change:
FINAL → DRAFT
```

Do not perform state changes merely to simulate progress.

---

## 5. Missing Information

When information is incomplete:

1. identify the gap;
2. distinguish scientific blockers from routine design freedom;
3. mark consequential assumptions;
4. continue unaffected work;
5. ask only when the gap prevents honest progress.

Examples:

```text
Unknown exact model score
→ do not invent it; omit or use a clearly marked placeholder

Unknown exact shade of blue
→ choose a restrained default and continue

Unclear whether an arrow is causal or temporal
→ ask or use a non-directional relation until clarified
```

---

## 6. Revision Contract

For revisions, write or internally maintain:

```yaml
locked:
  - elements that must remain unchanged

change:
  - requested modifications

flexible:
  - supporting details allowed to adapt
```

Examples of locked elements:

- exact labels;
- canvas ratio;
- scientific relationships;
- approved visual semantics;
- content in an unaffected panel.

Examples of flexible elements:

- nearby whitespace;
- connector routing;
- local alignment;
- proportional resizing required to fit the requested change.

Do not reinterpret “make the right side larger” as permission to redesign every panel.

---

## 7. Problems Discovered During Rendering

Ask:

> Can the issue be fixed without changing the scientific communication?

If yes, fix it directly.

Examples:

- overlap;
- poor spacing;
- hidden arrowhead;
- font substitution;
- weak contrast;
- crop problem.

After deterministic checks, inspect the preview visually when vision is
available. Focus on the primary anchor, reading order, scientific hierarchy,
redundancy, spacing, label density, connector ambiguity, collision, and balance
at final size. Use at most one or two targeted correction cycles by default and
stop when no obvious defect remains. Do not require OCR, a critic agent, or a
fixed optimization round count.

If no, return to the author or update the design before continuing.

Examples:

- one required panel must be removed to remain readable;
- a process layout falsely implies causality;
- Candidate and Reference cannot remain distinguishable in the approved structure;
- the only available data contradicts a specified value.

---

## 8. Finalization

A successful render and a passing automated validator do not make a figure final.

`FINAL` means:

- the author has seen the current artifact;
- known scientific blockers are resolved;
- the intended message is clear;
- the artifact is acceptable for the current manuscript or communication context.

Later manuscript changes may reopen the figure.

### Executable structured-diagram records

When Draw.io or Native SVG is selected, keep transient execution records outside
the FigureSpec:

```text
RenderPlan
editable backend source (.drawio or .svg)
artifact manifest
QA report
```

These files provide traceability but do not create new workflow states or
approval gates. A passing QA report supports `RENDERED`; it cannot establish
`FINAL` without author acceptance.

### Executable quantitative-plot records

When Matplotlib is selected, keep the parallel execution records outside the
FigureSpec:

```text
PlotPlan 1.0
authoritative local data references and hashes
reproducible .plot.py entry point
SVG / PDF / PNG artifacts
resolved execution trace in Artifact Manifest 1.0
QA Report 1.1
```

Rendering is blocked when FigureSpec coverage is unresolved, the FigureSpec or
data hash is stale, a scientific value is unbound, or a required artifact is
missing. Automated success remains `AUTOMATED_CHECKS_PASSED`; it cannot establish
`FINAL`.

---

## 9. Minimal Workflow

For most requests:

```text
Understand the message.
Define the figure.
Design the visual structure.
Render when asked.
Inspect the export.
Fix material issues.
Ask only when meaning is at stake.
```
