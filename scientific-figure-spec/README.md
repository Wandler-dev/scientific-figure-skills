# Scientific Figure Spec

This directory is the installable `scientific-figure-spec` Agent Skill and its
local execution tooling. Package release **1.3.1** preserves FigureSpec schema
**1.0**.

FigureSpec is the durable scientific and communication definition for one
figure. Plans, backend source, export records, and QA results are execution
sidecars; they do not redefine the FigureSpec.

## Workflow

The Skill follows the requested endpoint:

| Request | Default result |
|---|---|
| Define or review | FigureSpec only |
| Propose a design | FigureSpec through design; no rendering |
| Draw or render | One inspected draft unless scientific meaning is blocked |
| Revise | Preserve Locked content, apply Change, adapt only Flexible content |
| Plot quantitative results | Data-bound PlotPlan and reproducible Matplotlib output |

The lightweight states are:

```text
DRAFT → READY → RENDERED → FINAL
```

Only explicit author acceptance establishes `FINAL`.

## Execution Tracks

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
        Draw.io / Native SVG            Matplotlib
                │                           │
                └─────────────┬─────────────┘
                              │
                    Artifact Inspection
                              │
            Artifact Manifest 1.0 + QA Report 1.1
```

Diagram and plot execution remain separate. RenderPlan describes semantic
objects and relations; PlotPlan describes authoritative data bindings, panels,
series, axes, and uncertainty. `default_backend` is `null`, so selection is
always explicit.

## Initialize and Validate

Create specifications in the default `./figures` directory:

```bash
python scripts/figure.py init \
  "Method Overview" \
  "Evaluation Framework"
```

Use `--output-dir` or `--dry-run` when needed. The original
`scripts/init_figures.py` entry point remains available.

Validate one file or a directory:

```bash
python scripts/figure.py validate --strict figures/
```

The original `scripts/validate_figure_spec.py` supports `--recursive`,
`--strict`, `--json`, and `--project-root`. Validation checks the contract and
recorded paths; it cannot prove scientific truth or visual quality.

## Unified CLI

The public execution entry point is `scripts/figure.py`.

| Command | Purpose |
|---|---|
| `init` | Compatibility alias for FigureSpec initialization |
| `validate` | Compatibility alias for FigureSpec validation |
| `capabilities` | Show registered backends and non-goals |
| `plan` | Create RenderPlan or a conservative PlotPlan scaffold |
| `render` | Run the selected end-to-end execution track |
| `inspect` | Inspect an existing source/manifest pair |
| `preflight` | Check local capability availability |
| `validate-sidecar` | Validate RenderPlan, PlotPlan, manifest, or QA JSON |
| `author` | Create editable source or the reproducible plot runner |
| `lint` | Check backend source |
| `export` | Produce/record artifacts and manifest |
| `repair` | Apply bounded Draw.io repair; unavailable for SVG and Matplotlib |

Common capability check:

```bash
python scripts/figure.py capabilities
python scripts/figure.py preflight --backend matplotlib --operation render
```

Structured-diagram plan:

```bash
python scripts/figure.py plan \
  examples/F001-evidence-traceable-reconstruction.md \
  --backend svg \
  --output build/F001.render-plan.json \
  --strict
```

Quantitative planning creates an intentionally unresolved scaffold unless the
scientific data bindings are completed explicitly:

```bash
python scripts/figure.py plan path/to/F010-results.md \
  --backend matplotlib \
  --data path/to/results.csv \
  --output build/F010.plot-plan.json
```

Detailed backend commands belong in references 08–10, not in this overview.

## Artifact Conventions

Actual names come from the FigureSpec stem and plan outputs. A typical diagram
work directory contains:

```text
build/F001/
├── F001-name.render-plan.json
├── F001-name.drawio or F001-name.svg
├── F001-name.manifest.json
├── F001-name.qa.json
└── artifacts/
    └── F001-name.{svg,pdf,png}
```

A typical plot work directory contains:

```text
build/F005/
├── F005.plot.py
├── F005.plot-trace.json
├── F005.manifest.json
├── F005.qa.json
└── artifacts/
    └── F005.{svg,pdf,png}
```

The completed PlotPlan normally remains at its author-selected path and is
referenced by hash. PNG is a preview, not the canonical editable source.

## Capability Boundaries

- Draw.io planning, authoring, lint, inspection, and bounded repair are
  internal; SVG/PDF/PNG export requires Draw.io Desktop CLI.
- Native SVG planning, authoring, lint, SVG delivery, and inspection are
  internal; optional PDF/PNG output requires a discovered or explicit renderer.
- Matplotlib planning and data binding are internal; rendering requires the
  optional Matplotlib runtime.
- Missing Matplotlib does not affect FigureSpec, Draw.io, or Native SVG.
- Missing Draw.io Desktop does not affect Draw.io authoring/lint, Native SVG,
  or Matplotlib.
- Test doubles under `tests/fixtures/` are never production fallbacks.

## QA Semantics

Automated reports use:

```text
BLOCKED
REVISION_REQUIRED
AUTOMATED_CHECKS_PASSED
```

`AUTOMATED_CHECKS_PASSED` means the recorded deterministic execution checks
passed with `assessment_scope = AUTOMATED_EXECUTION` and
`human_review_status = NOT_PERFORMED`. It is narrower than human-reviewed
`PASS` and never establishes `FINAL`.

## References

Load only what the task requires:

| Need | Reference |
|---|---|
| FigureSpec definition | `references/01-figure-spec-model.md` |
| Workflow, review gates, revision | `references/02-workflow-and-state-machine.md` |
| Archetypes and composition | `references/03-figure-archetypes.md` |
| Design, hierarchy, simplification | `references/04-design-principles.md` |
| Artifact review and outcomes | `references/05-qa-rubric.md` |
| Backend selection | `references/06-rendering-backends.md` |
| Sidecar contracts and issue namespaces | `references/07-execution-sidecars.md` |
| Draw.io execution | `references/08-drawio-execution.md` |
| Native SVG execution | `references/09-svg-execution.md` |
| Data-bound Matplotlib plots | `references/10-publication-plots.md` |

## Examples, Benchmarks, and Tests

`examples/` contains user-facing FigureSpec examples. `benchmarks/` contains
positive and negative execution-contract fixtures; B01–B12 are not authoring
templates.

The test suite covers core FigureSpec tooling, diagram planning, Draw.io,
Native SVG, backend parity, PlotPlan, data binding, Matplotlib, artifact
inspection, and integration/negative regressions.

```bash
python -m unittest discover -s tests -p 'test_*.py'
python -m compileall -q .
```
