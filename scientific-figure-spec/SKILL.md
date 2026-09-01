---
name: scientific-figure-spec
description: Define, design, render, revise, recreate, or review rigorous scientific figures using a compact seven-section FigureSpec. Use for AI/CS paper figures, method diagrams, architectures, workflows, benchmark and evaluation figures, timelines, graph schematics, quantitative plots, and cross-paper visual consistency.
---

# Scientific Figure Spec

Use this skill to turn scientific intent into a clear FigureSpec and, when
requested, an inspected visual artifact.

```text
scientific intent
→ figure definition
→ visual design
→ appropriate execution track
→ inspection of the actual artifact
→ human acceptance
```

Do not add approval gates beyond those required by the requested endpoint.

## 1. Task Routing

Infer the endpoint from the user's wording.

| User intent | Default action |
|---|---|
| Define, specify, or review a figure | Create or improve FigureSpec only |
| Propose a layout or design direction | Complete FigureSpec through design and stop before rendering |
| Draw, create, render, or make a first version | Define, design, render, inspect, and deliver one usable draft |
| Revise or edit an existing figure | Establish Locked, Change, and Flexible scope; then revise |
| Recreate a supplied reference | Follow a fidelity-oriented reconstruction workflow using available editable mechanisms |
| Plot results from data | Use authoritative data, PlotPlan, and reproducible Matplotlib execution |
| Unify figures across a paper | Establish shared terminology and visual grammar, then apply it selectively |

Do not require the user to say “skip approval” when the request already asks
for a rendered result.

## 2. Hard Rules

1. **Do not invent science.** Never fabricate values, labels, model names,
   chronology, evidence, results, or causal relations.
2. **Preserve author intent.** Reorganize, simplify, and challenge scope when
   useful, but never silently change scientific meaning.
3. **Give the figure one dominant message.** Supporting ideas must not compete
   equally with it.
4. **Match visual relations to scientific relations.** Sequence, causality,
   containment, comparison, alignment, and evidence support are distinct.
5. **Make every major element earn its place.** Remove panels, icons,
   mini-diagrams, labels, and repeated objects that add no information,
   structure, or intentional emphasis.
6. **Design at final size.** Simplify before shrinking text or nodes.
7. **Keep execution tracks distinct.** Diagrams and quantitative plots do not
   share a universal plan or renderer.
8. **Inspect the actual artifact.** A valid specification or successful script
   run does not prove the figure is correct.
9. **Prefer editable or reproducible sources.** Preserve them when practical.
10. **Do not invent approval.** Only explicit author acceptance establishes
    `FINAL`.

## 3. Canonical FigureSpec

Use `assets/figure-spec.template.md` and preserve its seven sections:

```text
1. Figure Identity
2. Scientific Purpose
3. Required Content
4. Scientific Structure & Relationships
5. Figure Design
6. Visual & Content Constraints
7. References & Rendering Requirements
```

FigureSpec is the durable record of scientific and communication meaning. It
must not contain backend coordinates, XML, artifact hashes, execution logs, or
QA bookkeeping.

The minimum useful author input is usually one concise `2.1 Core Message`.
Routine design choices may be inferred; consequential assumptions must remain
visible. Do not force completion of every optional field before useful work can
begin.

Use stable IDs such as `F001` and filenames such as:

```text
FNNN-short-kebab-case-title.md
```

Default project location is `figures/`. Respect an established project
convention. Use `scripts/init_figures.py` or the `figure.py init` compatibility
entry point; do not invent unsupported arguments.

## 4. Progressive Reference Loading

Read only the references needed for the task:

```text
FigureSpec definition or interpretation
→ references/01-figure-spec-model.md

workflow, direct rendering, review gates, or revision
→ references/02-workflow-and-state-machine.md

archetype or composition selection
→ references/03-figure-archetypes.md

visual hierarchy, simplification, or redundancy
→ references/04-design-principles.md

artifact review and QA outcomes
→ references/05-qa-rubric.md

backend selection and delivery
→ references/06-rendering-backends.md

execution sidecars, versions, provenance, or issue namespaces
→ references/07-execution-sidecars.md

Draw.io execution
→ references/08-drawio-execution.md

Native SVG execution
→ references/09-svg-execution.md

data-bound Matplotlib plotting
→ references/10-publication-plots.md
```

After choosing an execution track, load only its backend reference. Do not load
all references for a simple definition or review task.

## 5. Defining and Designing

When creating or updating FigureSpec:

1. Read the relevant paper, project, data, and figure context.
2. State the Core Message and intended reader takeaway.
3. List concrete Must Show content and exact source-bound facts.
4. Define important relationships and prohibited implications.
5. Select one primary archetype and only necessary supporting archetypes.
6. Define reading order, composition, primary anchor, and information
   hierarchy.
7. Identify what should be simplified, grouped, or removed.
8. Define semantic colors, shapes, connectors, and exact labels only where they
   carry meaning.
9. Record intended use, final size, backend preference, and required outputs.

Choose visual structure from the reader's reasoning task:

```text
components and interfaces → Architecture
sequence and transformation → Workflow / Pipeline
containment and levels → Hierarchy
time and progression → Process / Timeline
comparison and judgment → Evaluation / Comparison
causal or interaction logic → Mechanism
quantitative findings → Results / Diagnostics
overall mental model → Method Overview
```

Stay backend-neutral until the scientific composition is clear. Recommend one
design by default; present alternatives only when the author must choose among
scientifically non-equivalent directions.

## 6. Rendering and Track Selection

The bundled execution architecture is:

```text
Structured Diagram Track
FigureSpec → Spec Coverage Gate → RenderPlan 1.1 → Draw.io / Native SVG

Quantitative Plot Track
FigureSpec + authoritative data → Data Binding Gate → PlotPlan 1.0 → Matplotlib
```

All three bundled backends are opt-in. `default_backend` is `null`.

Use Draw.io when manual post-editing is important. Use Native SVG for semantic,
text-based vector diagrams. Use Matplotlib for line, scatter, bar, or heatmap
figures whose marks bind to authoritative local data.

TikZ, Graphviz, PPTX, image generation, dedicated reference reconstruction,
and raster-to-editable conversion are not bundled execution capabilities. Do
not claim they are implemented. If a project supplies another tool, follow its
own contract without weakening FigureSpec.

When the user asks to render, continue through an inspected first draft unless
a real blocker exists. Review before rendering only when:

- required scientific information is missing;
- incompatible primary messages require an author choice;
- simplification would remove Must Show content;
- a visual relation would introduce a causal or scientific interpretation;
- strict reproduction has a consequential ambiguity;
- authoritative data sources conflict;
- the user explicitly asks to approve the design first.

Do not stop for routine spacing, connector bends, minor typography, neutral
palette choices, or export settings. A first artifact is `RENDERED`, never
automatically `FINAL`.

For structured diagrams, treat the deterministic RenderPlan as an execution
scaffold. Compare it with FigureSpec Section 5 before authoring, especially
reading order, composition, primary anchor, information hierarchy, and
simplification. Adjust the plan when a mechanical layout does not communicate
the intended design.

For quantitative figures:

- bind every plotted series, uncertainty interval, numeric annotation, and
  source-bound reference line to declared authoritative data;
- pass both FigureSpec coverage and the Data Binding Gate;
- use precomputed uncertainty and upstream analysis outputs;
- keep units, scales, limits, baselines, and missingness explicit;
- never infer scientific meaning from column names;
- never calculate new statistics, fill missing values, interpolate, smooth,
  remove outliers, or manually redraw values in the backend.

## 7. Revision and Reference Recreation

For revisions, establish:

```text
Locked
- scientific content, geometry, style, or semantics that must remain

Change
- requested revisions

Flexible
- supporting details allowed to adapt
```

Preserve already-correct elements and avoid unrelated redesign, label drift,
changed semantic colors, or new decoration. Return to the author only when the
requested change would alter meaning or remove required content.

For a supplied reference, separate semantic fidelity from visual fidelity,
measure the available composition, rebuild with editable native objects where
practical, and compare full view and local detail. This is workflow guidance,
not a dedicated reconstruction backend, OCR pipeline, or raster-to-editable
engine. A style reference does not authorize copying its scientific content.

## 8. Artifact Inspection and QA

Inspect the actual artifact in four dimensions:

```text
Scientific
Communication
Visual
Technical
```

At minimum verify:

- every Must Show item and required relation is present;
- no unsupported content, value, relation, or implication was introduced;
- the primary message and reading order are clear;
- every panel and repeated element adds information;
- labels, connectors, legends, and uncertainty are unambiguous;
- text and linework remain readable at intended final size;
- no important clipping, overlap, rasterization, provenance, or export defect
  remains;
- editable or reproducible source is usable.

Use QA outcomes consistently:

```text
BLOCKED
REVISION_REQUIRED
AUTOMATED_CHECKS_PASSED
PASS
```

`AUTOMATED_CHECKS_PASSED` covers deterministic execution checks with
`assessment_scope = AUTOMATED_EXECUTION` and
`human_review_status = NOT_PERFORMED`. It does not prove scientific truth,
communication hierarchy, aesthetic quality, author acceptance, or `FINAL`.
Full `PASS` belongs to complete review context.

After deterministic checks, visually inspect the artifact when vision is
available. Apply at most one or two targeted correction cycles by default and
stop when no material defect remains. Do not require OCR, a critic agent,
multi-agent orchestration, or a fixed optimization round count.

## 9. Status and Minimal Procedure

```text
DRAFT
READY
RENDERED
FINAL
```

- `DRAFT`: the definition may be incomplete.
- `READY`: the definition supports deliberate design review or rendering.
- `RENDERED`: a concrete artifact exists and has been inspected.
- `FINAL`: the author accepts the current artifact.

Reopen to the earliest meaningful state when scientific purpose, design, or
rendering changes.

For routine work:

```text
1. Understand the scientific message.
2. Build or update the compact FigureSpec.
3. Choose the archetype and visual hierarchy.
4. Select the appropriate execution track.
5. Render when the request asks for a figure.
6. Inspect the actual artifact at final size.
7. Fix meaningful issues without unrelated drift.
8. Let the author decide when it is final.
```

The specification, agent, plans, backends, and QA exist to serve scientific
communication.
