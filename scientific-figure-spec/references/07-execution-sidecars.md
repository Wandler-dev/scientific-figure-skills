# Execution Sidecars v1.1

## Purpose

FigureSpec remains the sole durable source of scientific and communication
meaning. Backend execution state lives in separate files so rendering can evolve
without changing `spec_version: "1.0"` or the seven canonical sections.

```text
FigureSpec 1.0
    ├→ RenderPlan 1.1 → Draw.io / Native SVG
    └→ PlotPlan 1.0 + authoritative data → Matplotlib
                     ↓ executes
             reproducible/editable source + exported artifacts
                     ↓ records
             Artifact Manifest 1.0 + QA Report 1.1
```

The sidecars do not authorize a renderer to add facts, labels, relationships, or
visual implications that are absent from the FigureSpec.

## RenderPlan

`schemas/render-plan.schema.json` records one shared structured-diagram
implementation contract, with only source/output metadata selected per backend:

- an immutable reference to the source FigureSpec and its SHA-256 digest;
- an exhaustive mapping for every Must Show and Relationships bullet, including
  explicit unresolved records that block downstream execution;
- canvas and intended final size;
- semantic theme tokens;
- editable elements and connectors;
- machine-checkable semantic assertions;
- expected source, export, manifest, and QA paths.

Coordinates belong here, not in the canonical FigureSpec. A plan can be replaced
or regenerated without rewriting scientific intent.

Draw.io and Native SVG must preserve the same elements, labels, hierarchy,
connectors, relation kinds, semantic roles, assertions, coverage, canvas, and
theme semantics. Their XML and producer metadata may differ.

## PlotPlan

`schemas/plot-plan.schema.json` is a separate quantitative-plot contract. It
records an immutable FigureSpec identity, authoritative local data paths and
hashes, FigureSpec coverage, panel and series encodings, axes, units,
missing-data policy, precomputed uncertainty, style profile, requested outputs,
and checks.

PlotPlan does not contain diagram elements or connectors. RenderPlan does not
contain datasets, axes, series, or uncertainty. They share scientific fidelity,
provenance, output handling, and QA severity semantics without a universal IR.

## Artifact Manifest

`schemas/artifact-manifest.schema.json` records what actually ran and what was
produced:

- plan and editable-source identities;
- exporter command and observed exit status;
- artifact paths, media types, sizes, hashes, and measurable dimensions;
- export problems using stable issue codes.

For Native SVG, the editable `.svg` source can also be the recorded vector
artifact without an external renderer. Optional PNG/PDF producers remain
explicit and are recorded when used.

For Matplotlib, the unchanged Manifest 1.0 contract records input data
path/hash/row metadata, PlotPlan and Python-source identities, Python and
Matplotlib versions, resolved series bindings, output hashes and formats,
physical dimensions, and raster DPI through existing metadata fields. No schema
change is required for this additive provenance.

The manifest is evidence of execution, not evidence of scientific correctness.

## QA Report

`schemas/qa-report.schema.json` records inspection of the actual source and
exports using the existing four dimensions:

```text
Scientific
Communication
Visual
Technical
```

Generated reports identify their scope as `AUTOMATED_EXECUTION`. A zero-issue
run records `AUTOMATED_CHECKS_PASSED`; `REVISION_REQUIRED` and `BLOCKED` retain
their existing meanings. `PASS` remains a valid complete-review outcome, but
automated execution does not use it to imply that checks proved complete
scientific, communication, or visual quality. Only explicit author acceptance
can move a FigureSpec to `FINAL`; the runtime does not add a mandatory approval
gate.

Inspection normalizes Draw.io and SVG sources before shared scientific checks.
It verifies plan-to-source completeness and blocks obvious unplanned labels,
semantic objects, and relations rather than maintaining two drifting QA paths.

Plot inspection follows the parallel PlotPlan/data/trace path and uses the same
four QA categories and outcomes. It does not OCR raster artifacts or infer values
from pixels.

## Issue-code ownership

Stable issue namespaces identify the layer that owns a finding:

```text
metadata.* / structure.* / readiness.*
→ canonical FigureSpec validation

schema.* / plan.* / manifest.* / qa.*
→ shared sidecar contracts

scientific.coverage.* / scientific.data.* / semantic.*
→ cross-layer scientific integrity

drawio.* / svg.* / plot.*
→ backend or track-specific validation

export.* / capability.*
→ production and environment capability

visual.* / technical.*
→ artifact-level QA

repair.*
→ bounded Draw.io repair actions or skips
```

Do not rename stable codes merely to make the namespaces visually uniform.
Exact Draw.io codes are indexed in `08-drawio-execution.md`; Native SVG and
plot codes remain under the `svg.*` and `plot.*` families documented in
`09-svg-execution.md` and `10-publication-plots.md`.

## Versioning

Each sidecar has its own `schema_version`. RenderPlan and QA remain `1.1`,
PlotPlan is `1.0`, and Artifact Manifest remains `1.0`. None of these versions
changes FigureSpec's `spec_version: "1.0"`.
