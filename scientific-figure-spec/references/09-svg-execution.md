# Native SVG Execution Loop

## Scope and boundaries

This reference describes the bundled opt-in Native SVG path for structured
scientific diagrams. It shares the same scientific planning and QA contracts as
Draw.io:

```text
FigureSpec 1.0
→ exhaustive Spec Coverage
→ shared structured-diagram RenderPlan 1.1
→ native semantic SVG
→ deterministic SVG lint
→ SVG artifact and optional PNG/PDF rendering
→ normalized artifact inspection
→ Artifact Manifest 1.0 + QA Report 1.1
```

The capability registry defines no default backend. Native SVG does not add
coordinates, backend markup, artifact hashes, or execution state to FigureSpec.

This path does not implement Matplotlib, PlotPlan, Graphviz, PPTX, TikZ, image
generation, OCR, raster-to-editable conversion, or multi-agent orchestration.

## Shared planner

`scripts/diagram_plan.py` converts FigureSpec content and exhaustive coverage
into elements, containers, parent-child hierarchy, connectors, semantic styles,
assertions, and geometry. It contains no SVG tags or Draw.io cells.

The generated plan is an implementation scaffold. Before authoring a real paper
figure, compare it with FigureSpec Section 5 and adjust the RenderPlan when its
reading order, composition, primary anchor, information hierarchy, or
simplification choices require deliberate refinement. This internal review is
not a new approval gate.

## Unified CLI

Use the existing command family with explicit `--backend svg` selection:

```text
figure.py preflight --backend svg --operation OPERATION
figure.py plan FIGURE_SPEC --backend svg --output PLAN [--strict]
figure.py author PLAN [--output SOURCE]
figure.py lint SOURCE [--plan PLAN] [--strict] [--json]
figure.py export SOURCE --plan PLAN [--format FORMAT]
figure.py inspect SOURCE --plan PLAN --manifest MANIFEST [--qa REPORT]
figure.py render FIGURE_SPEC --backend svg --work-dir DIR
```

`repair` is intentionally unavailable for Native SVG. Edit the text-based
source directly, lint again, and inspect the new artifact.

## Authoring contract

The author writes a real SVG document using native groups, shapes, paths,
polylines, markers, text, and tspans. Each planned element and connector keeps a
stable object ID and semantic metadata. Planned parent-child relationships are
encoded as nested groups, not inferred only from coordinates.

Normal labels remain searchable live text. The backend does not convert labels
to paths, embed a whole-figure raster, use `foreignObject`, load remote fonts or
images, or copy the full FigureSpec into SVG metadata.

Connector endpoints dock to object bounds. Routing is intentionally limited to
straight and orthogonal paths with at most one safe detour; it is not a
general-purpose graph routing engine. Directed markers have stable
user-space dimensions.

## Lint contract

`scripts/svg_lint.py` checks deterministic properties, including:

- parseable SVG XML and a finite positive viewBox;
- unique IDs and resolvable marker, clip, mask, and `url(#id)` references;
- no external assets, embedded raster, scripts, or forbidden foreign content;
- live text and positive font sizes;
- complete plan objects, connectors, and true parent-child nesting;
- valid geometry within the viewBox;
- effective final-size text thresholds;
- valid connector endpoints and markers;
- obvious connector-through-unrelated-node and arrowhead clipping cases.

Approximate collision checks are warnings where exact font or path geometry
cannot be proven. Strict mode treats warnings as failure.

Stable issue families are:

```text
svg.xml.*
svg.structure.*
svg.reference.*
svg.asset.*
svg.editability.*
svg.geometry.*
svg.text.*
svg.connector.*
svg.style.*
```

## Export and capability contract

The native `.svg` is both editable source and vector artifact. SVG-only delivery
therefore needs no external renderer.

PNG and PDF are dynamic optional capabilities, discovered in this order:

```text
rsvg-convert
→ Chrome / Chromium headless
→ CairoSVG
```

No renderer is a silent production fallback. An explicitly supplied renderer
command is authoritative. The artifact manifest records the actual command,
version, invocations, artifact hashes, sizes, formats, and dimensions.

If an optional renderer is unavailable:

- SVG authoring, lint, and SVG artifact delivery remain available;
- PNG-only or PDF-only export is `BLOCKED`;
- a mixed request that successfully records SVG is `PARTIAL`.

Generated PDF must be non-empty, begin with a valid PDF header, and expose
reasonable positive page dimensions. Missing optional font-forensics tools do
not invalidate otherwise valid SVG execution.

The fake SVG renderer under `tests/fixtures/` is test-only and is never a
production fallback.

## Normalized inspection

Draw.io and SVG adapters are normalized into the same source model:

```text
object IDs
labels
parent-child hierarchy
connectors and relation kinds
semantic roles and colors
geometry and bounds
embedded-raster status
```

Shared inspection verifies FigureSpec identity, exhaustive coverage, planned
objects and relations, forbidden relations, hierarchy, artifacts, final-size
text, and required outputs. It also blocks obvious source content absent from
the RenderPlan:

```text
semantic.unplanned_label.present
semantic.unplanned_relation.present
semantic.unplanned_required_object.present
```

Decorative technical metadata is excluded. The inspector does not use an LLM
to infer arbitrary natural-language semantics.

Zero automated issues produce `AUTOMATED_CHECKS_PASSED` with:

```text
assessment_scope = AUTOMATED_EXECUTION
human_review_status = NOT_PERFORMED
```

This does not establish complete scientific truth, communication quality,
visual polish, author acceptance, or `FINAL` status.
