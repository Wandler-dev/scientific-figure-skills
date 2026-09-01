# Scientific Figure Skills

Scientific Figure Skills is a specification-first toolkit for defining,
designing, rendering, revising, and reviewing scientific figures. It keeps
scientific intent authoritative while producing editable or reproducible
artifacts that can be inspected mechanically and reviewed by people.

Current package release: **1.3.1**. The canonical FigureSpec schema remains
**1.0**.

## Why

Scientific figures fail when visual polish outruns scientific meaning. This
project keeps one durable definition per figure, separates diagram semantics
from quantitative plotting semantics, and checks the artifacts that were
actually produced.

The governing priorities are:

```text
scientific faithfulness
→ communication clarity
→ editable or reproducible execution
→ deterministic inspection
→ human acceptance
```

Every major visual element should contribute information, structure, or
intentional emphasis. Simplify before shrinking text, adding panels, or
repeating decorative objects.

## What It Supports

| Figure need | Contract | Bundled backend | Status |
|---|---|---|---|
| Method, workflow, architecture, hierarchy, evaluation diagram | RenderPlan 1.1 | Draw.io | Stable; desktop CLI required only for export |
| Method, workflow, architecture, hierarchy, evaluation diagram | RenderPlan 1.1 | Native SVG | Stable; SVG source needs no external renderer |
| Line, scatter, bar, or heatmap from authoritative data | PlotPlan 1.0 | Matplotlib | Stable; Matplotlib is optional |
| Mathematical LaTeX-native diagram | — | TikZ | Not implemented |
| Large automatic graph layout | — | Graphviz | Not implemented |
| Reference reconstruction or raster-to-editable conversion | — | — | Not implemented |

Backend availability and scientific suitability are separate decisions. The
package deliberately defines no default backend.

## Architecture

```text
                         FigureSpec 1.0
                              │
                ┌─────────────┴─────────────┐
                │                           │
      Structured Diagram Track     Quantitative Plot Track
                │                           │
       Spec Coverage Gate             Data Binding Gate
                │                           │
        RenderPlan 1.1                 PlotPlan 1.0
                │                           │
        ┌───────┴───────┐              Matplotlib
        │               │                  │
     Draw.io        Native SVG         SVG/PDF/PNG
        │               │                  │
        └───────────────┬──────────────────┘
                        │
                Artifact Inspection
                        │
             Artifact Manifest 1.0
                        │
                  QA Report 1.1
```

The two execution tracks share FigureSpec, provenance, output handling, and QA
semantics. They do not share a universal execution IR: diagrams use elements,
containers, and relations; plots use data sources, panels, series, axes, and
uncertainty.

## Quick Start

Run commands from this directory.

Initialize specifications in `./figures`:

```bash
python scientific-figure-spec/scripts/figure.py init \
  "Method Overview" \
  "Evaluation Framework"
```

Validate them strictly:

```bash
python scientific-figure-spec/scripts/figure.py validate \
  --strict figures/
```

Inspect registered and locally available capabilities:

```bash
python scientific-figure-spec/scripts/figure.py capabilities
python scientific-figure-spec/scripts/figure.py preflight \
  --backend svg \
  --operation render
```

Create a structured-diagram plan:

```bash
python scientific-figure-spec/scripts/figure.py plan \
  scientific-figure-spec/examples/F001-evidence-traceable-reconstruction.md \
  --backend svg \
  --output build/F001/F001.render-plan.json \
  --strict
```

`render` runs plan, authoring, lint, export, and inspection. The exact command
depends on the selected backend and requested outputs:

```bash
python scientific-figure-spec/scripts/figure.py render \
  scientific-figure-spec/examples/F001-evidence-traceable-reconstruction.md \
  --backend svg \
  --work-dir build/F001
```

Use `inspect` when checking an existing source/manifest pair after a targeted
revision:

```bash
python scientific-figure-spec/scripts/figure.py inspect \
  build/F001/F001-evidence-traceable-reconstruction.svg \
  --plan build/F001/F001-evidence-traceable-reconstruction.render-plan.json \
  --manifest build/F001/F001-evidence-traceable-reconstruction.manifest.json \
  --qa build/F001/F001-evidence-traceable-reconstruction.reinspect.qa.json
```

Detailed capability requirements are in the backend references under
`scientific-figure-spec/references/`.

## Core Contracts

| Contract | Version | Role |
|---|---:|---|
| FigureSpec | 1.0 | Durable scientific and communication definition |
| RenderPlan | 1.1 | Structured-diagram execution plan |
| PlotPlan | 1.0 | Data-bound quantitative plotting plan |
| Artifact Manifest | 1.0 | Producer, input, output, and hash provenance |
| QA Report | 1.1 | Machine-checkable findings and assessment scope |

Package releases do not mechanically change these independent contract
versions. `scientific-figure-spec/capabilities.json` is the canonical package
version source; the CLI reads it directly. Release history is maintained in Git
commits and tags rather than a separate changelog.

## Quality and Safety Model

- FigureSpec scientific intent remains authoritative.
- Must Show content and scientific relationships cannot disappear silently.
- Quantitative marks must bind to declared local data and precomputed
  uncertainty.
- Renderers must not invent labels, values, relations, or scientific claims.
- Final-size readability is assessed from intended physical size, not preview
  pixel count alone.
- Automated success is `AUTOMATED_CHECKS_PASSED`, not human-reviewed `PASS`.
- Human authors remain authoritative for claims, causal interpretation, source
  correctness, and final acceptance.

## Project Structure

```text
scientific-figure-skills/
├── README.md
├── figure-design-standard.md
└── scientific-figure-spec/
    ├── README.md
    ├── SKILL.md
    ├── capabilities.json
    ├── assets/
    ├── schemas/
    ├── references/
    ├── examples/
    ├── benchmarks/
    ├── scripts/
    └── tests/
```

`figure-design-standard.md` defines what a scientific figure definition must
contain. `scientific-figure-spec/` is the installable Agent Skill and execution
tooling. They share the same seven-section FigureSpec model.

## Documentation

- [Figure definition standard](figure-design-standard.md)
- [Core Skill guide](scientific-figure-spec/README.md)
- [Agent Skill entry point](scientific-figure-spec/SKILL.md)
- [FigureSpec model](scientific-figure-spec/references/01-figure-spec-model.md)
- [Workflow and revision](scientific-figure-spec/references/02-workflow-and-state-machine.md)
- [QA rubric](scientific-figure-spec/references/05-qa-rubric.md)
- [Backend routing](scientific-figure-spec/references/06-rendering-backends.md)
- [Execution sidecars](scientific-figure-spec/references/07-execution-sidecars.md)
- [Draw.io execution](scientific-figure-spec/references/08-drawio-execution.md)
- [Native SVG execution](scientific-figure-spec/references/09-svg-execution.md)
- [Data-bound publication plotting](scientific-figure-spec/references/10-publication-plots.md)

`examples/` is for researchers and Skill users. `benchmarks/` defines execution
contracts and negative regressions; it is not a template library.

## Development and Release Checks

```bash
python -m unittest discover \
  -s scientific-figure-spec/tests \
  -p 'test_*.py'
python -m compileall -q scientific-figure-spec
git diff --check
```

Before release, also validate the Skill package, run the F001 Draw.io/SVG
regressions and backend parity check, run the B09–B11 Matplotlib smoke tests and
B12 negative suite, verify `default_backend` remains `null`, and confirm no
temporary artifacts or stale package names are tracked.
