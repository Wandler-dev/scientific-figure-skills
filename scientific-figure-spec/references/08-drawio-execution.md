# Draw.io Execution Loop

## Scope and boundaries

This reference describes the bundled executable Draw.io path. Sidecar versions
are independent of the canonical FigureSpec, which remains
`spec_version: "1.0"` with seven top-level sections.

Draw.io is selected only when explicitly requested or when the active agent has
already chosen it as the appropriate editable structured-diagram backend. The
capability registry intentionally defines no default backend.

Scientific planning is shared with Native SVG through `diagram_plan.py`.
`drawio_backend.py` is the mxGraph adapter, not the owner of FigureSpec
interpretation or coverage logic.

The bundled path does not implement Graphviz, PPTX, TikZ, image generation, OCR,
raster-to-editable conversion, or multi-agent orchestration.

## Unified CLI

The original `init_figures.py` and `validate_figure_spec.py` commands remain
available. `figure.py` adds compatibility aliases and executable commands:

```text
figure.py init ...
figure.py validate ...
figure.py capabilities [--json]
figure.py preflight --backend drawio --operation OPERATION [--json]
figure.py validate-sidecar {render-plan|plot-plan|manifest|qa} FILE [--json]
figure.py plan FIGURE_SPEC --backend drawio --output PLAN [--strict]
figure.py author PLAN [--output SOURCE]
figure.py lint SOURCE [--strict] [--json]
figure.py export SOURCE --plan PLAN [--output-dir DIR] [--format FORMAT]
figure.py inspect SOURCE --plan PLAN --manifest MANIFEST [--qa REPORT]
figure.py repair SOURCE [--plan PLAN] --output REPAIRED_SOURCE
figure.py render FIGURE_SPEC --backend drawio --work-dir DIR
```

Use `--drawio-command` or `DRAWIO_COMMAND` when Draw.io Desktop is not available
as `drawio` or `draw.io`. An explicit command is authoritative; an invalid
explicit path does not silently fall back to another executable.

Normal exit meanings for new commands are:

```text
0  requested check or complete loop passed
1  a valid run produced FAIL, BLOCKED, or REVISION_REQUIRED
2  usage, setup, contract, or safe-write failure
```

## Execution artifacts

```text
FNNN-name.md
FNNN-name.render-plan.json
FNNN-name.drawio
FNNN-name.manifest.json
FNNN-name.qa.json
artifacts/FNNN-name.{svg,pdf,png}
```

The RenderPlan is the only file allowed to hold backend geometry. RenderPlan
1.1 also records exhaustive Must Show and Relationships coverage. The manifest
binds exports to exact source and plan hashes. QA Report 1.1 binds inspection to
the live FigureSpec, normalized editable source, and actual exported bytes. A zero-issue
machine run records `AUTOMATED_CHECKS_PASSED`; it does not claim complete
scientific or visual `PASS`.

## Scientific coverage gate

The planner records every bullet from `3.1 Must Show` and `4.1 Relationships`
as `MAPPED` or `UNRESOLVED`, with concrete element, connector, parent-child, or
assertion references. The summary is complete only when no item is unresolved.

```text
FigureSpec 1.0
  → independent requirement extraction
  → RenderPlan 1.1 spec_coverage
  → author/export only when COMPLETE
  → QA reparses FigureSpec and verifies mapped source representations
```

Supported conservative relation mappings include explicit flow arrows,
containment/hierarchy, evidence support/provenance, Candidate–Reference
comparison, evaluation output, and Reference independence. Unsupported or
ambiguous wording remains explicit `UNRESOLVED`; the planner does not invent a
connector to satisfy the gate.

## Authoring contract

The authoring backend emits one native, uncompressed `mxGraphModel` page:

- globally unique stable cell IDs;
- native vertex text and geometry;
- edge cells attached by source and target IDs;
- semantic role and relation metadata;
- no embedded raster screenshot;
- deterministic bytes for the same RenderPlan.
- real Draw.io parent-child cells with relative child coordinates for
  containment rather than a visual-only overlay.

If Required Figure Labels are absent, the planner may use Must Show bullets
verbatim. This is an execution fallback, not a new mandatory author field or an
approval gate.

## Export contract

Production export always invokes a separately installed Draw.io Desktop CLI.
All requested formats are exported to temporary paths first and moved into
place only after the full batch succeeds. Existing outputs and manifests are
not overwritten without `--force`.

`tests/fixtures/fake_drawio_cli.py` is an explicitly labeled automated-test
double. It must never be used to claim a production Draw.io export.

## Inspection contract

Inspection normalizes native cells into the same source model used by Native
SVG, then combines that model with artifact metadata and SVG text. It does not
use OCR. It checks:

- live FigureSpec identity and exhaustive Must Show / Relationships coverage;
- mapped element, connector, assertion, and parent-child representations;
- source and manifest identity;
- artifact existence, hash, dimensions, and required formats;
- canvas and final-size aspect ratio;
- effective point size at the declared final width;
- required and forbidden labels or relations;
- plan-bound semantic colors;
- absence of obvious unplanned scientific labels, objects, and relations;
- vector/editability constraints.

Native SVG-specific execution rules are documented in `09-svg-execution.md`;
they do not alter this Draw.io adapter contract.

## Safe repair contract

Repair never edits the input in place. Without a RenderPlan it can only add
safe style tokens or normalize edge geometry. With a validated matching plan it
may restore missing plan-owned cells, endpoints, geometry, empty labels, and
semantic colors, or remove a relation explicitly marked forbidden.

It does not overwrite a non-empty conflicting label and does not delete
embedded raster content. Those cases remain incomplete and require design or
scientific review.

## Stable Draw.io issue codes

The legacy FigureSpec validator codes are unchanged. The following execution
codes remain stable.

### Sidecar schema and contract

```text
schema.file.invalid
schema.additional_property
schema.const
schema.enum
schema.exclusive_minimum
schema.format
schema.max_items
schema.min_items
schema.min_length
schema.min_properties
schema.minimum
schema.pattern
schema.ref
schema.required
schema.type
schema.unique_items

plan.assertion.id_duplicate
plan.backend.unsupported
plan.connector.endpoint_missing
plan.element.parent_missing
plan.id_duplicate
plan.output.source_extension

manifest.artifact.path_duplicate
manifest.completed_without_artifacts

qa.outcome.mismatch
qa.summary.mismatch
```

### Capability preflight

```text
capability.backend.out_of_scope
capability.backend.unknown
capability.drawio_cli.missing
capability.drawio_cli.version_unknown
capability.operation.unavailable
capability.operation.unknown
```

### Draw.io structure, geometry, and editability

```text
drawio.file.missing
drawio.file.read
drawio.xml.invalid
drawio.xml.unsafe_doctype
drawio.format.compressed
drawio.structure.mxfile_missing
drawio.structure.diagram_missing
drawio.structure.diagram_multiple
drawio.structure.graph_model_missing
drawio.structure.root_missing
drawio.structure.base_cell_missing
drawio.structure.id_missing
drawio.structure.id_duplicate
drawio.structure.parent_missing
drawio.structure.parent_unknown
drawio.structure.cell_type_missing
drawio.geometry.canvas_invalid
drawio.geometry.missing
drawio.geometry.missing_attribute
drawio.geometry.invalid
drawio.geometry.nonpositive
drawio.geometry.out_of_bounds
drawio.geometry.overlap
drawio.connector.endpoint_missing
drawio.connector.endpoint_unknown
drawio.connector.endpoint_type
drawio.connector.geometry_missing
drawio.connector.geometry_not_relative
drawio.editability.embedded_raster
drawio.style.wrap_missing
drawio.text.empty_vertex
```

### Export and manifest production

```text
export.source.lint_failed
export.source.plan_mismatch
export.figure_spec.missing
export.figure_spec.hash_mismatch
export.output.exists
export.cli.missing
export.cli.timeout
export.cli.failed
export.artifact.missing
export.artifact.empty
export.artifact.dimension_unreadable
```

### Artifact and semantic QA

```text
technical.export.incomplete
technical.manifest.plan_hash_mismatch
technical.manifest.source_hash_mismatch
technical.artifact.missing
technical.artifact.hash_mismatch
technical.artifact.dimensions_unreadable
technical.artifact.aspect_mismatch
technical.artifact.required_format_missing
technical.svg.invalid
technical.svg.embedded_raster
technical.editability.embedded_raster
semantic.required_label.missing
semantic.required_relation.missing
semantic.forbidden_relation.present
semantic.role_color.mismatch
semantic.source.plan_id_mismatch
semantic.source.required_object_missing
semantic.source.required_relation_missing
semantic.source.parent_mismatch
semantic.source.role_mismatch
semantic.source.label_mismatch
semantic.source.relation_mismatch
semantic.unplanned_label.present
semantic.unplanned_relation.present
semantic.unplanned_required_object.present
visual.final_size.aspect_mismatch
visual.text.too_small
```

### Repair action and skip codes

Repair codes describe bounded actions rather than hiding the original lint or
QA finding.

```text
repair.format.uncompressed_marker_added
repair.style.wrap_added
repair.connector.geometry_relative
repair.cell.restored_from_plan
repair.connector.restored_from_plan
repair.geometry.restored_from_plan
repair.label.restored_from_plan
repair.semantic_color.restored
repair.forbidden_relation.removed
repair.skipped.label_conflict
repair.skipped.unsafe_raster
repair.skipped.unresolved_issue
repair.no_change
```

## Coverage and containment issue codes

```text
plan.element.parent_not_container
plan.element.child_out_of_parent
plan.element.parent_cycle
plan.coverage.id_duplicate
plan.coverage.summary_mismatch
plan.coverage.status_mismatch
plan.coverage.representation_missing
plan.coverage.unresolved_reason_missing
plan.coverage.blocked

drawio.structure.parent_not_container
drawio.structure.parent_cycle
drawio.geometry.child_out_of_parent

export.plan.coverage_blocked

scientific.coverage.figure_spec_missing
scientific.coverage.figure_spec_hash_mismatch
scientific.coverage.must_show_missing
scientific.coverage.relationship_missing
scientific.coverage.must_show_unmapped
scientific.coverage.relationship_unmapped
scientific.coverage.representation_missing
```
