# Data-Bound Publication Plotting v1.0

## 1. Scope

The bundled Matplotlib track turns an authoritative plotting table into a
conventional publication plot through an explicit `PlotPlan 1.0`.

```text
FigureSpec 1.0
+ local authoritative data
→ PlotPlan 1.0
→ Data Binding Gate
→ reproducible Python runner
→ Matplotlib SVG / PDF / PNG
→ resolved execution trace
→ artifact manifest and QA report
```

This track is parallel to the structured-diagram track. A PlotPlan does not use
diagram `elements`, `connectors`, hierarchy, or routing. A RenderPlan does not
contain data columns, series, uncertainty, or axes.

The track faithfully visualizes an already authoritative plotting table. It is
not a statistical analysis or data-cleaning framework.

It does not calculate hypothesis tests, fit models, smooth curves, interpolate
missing values, remove outliers, normalize measurements, or compute confidence
intervals. Perform consequential analysis upstream and bind the resulting table.

## 2. Authoritative Data

PlotPlan 1.0 accepts local:

- CSV;
- TSV;
- JSON records (a top-level array of objects).

Each `data_sources[]` entry records a stable ID, local path, format, SHA-256
digest, and `authoritative_plot_data` role. Remote URLs, databases, spreadsheets,
Parquet, and hidden network access are not supported.

The loader preserves source row order. Its only filtering operations are:

```text
column == value
column in values
```

An optional explicit `sort_by` column may establish plotting order. More complex
transformation belongs in the upstream analysis that produces the plotting
table.

## 3. Two Independent Gates

### Spec Coverage

PlotPlan records every bullet from:

```text
3.1 Must Show
4.1 Relationships
6.2 Required Figure Labels
6.3 Must Not Imply / Avoid
```

Each requirement maps to one or more panel, series, axis, legend, annotation,
reference line, or data-binding IDs. Any unresolved requirement blocks render.

### Data Binding

The Data Binding Gate verifies:

- the FigureSpec path, identity, version, and hash;
- every data path, format, and hash;
- required columns and supported data types;
- non-empty resolved series;
- missing-value policy;
- uncertainty columns and bounds;
- log-scale compatibility;
- explicit axis clipping;
- bar baseline rules;
- source-bound annotations and constants.

Spec Coverage proves that scientific requirements were planned. Data Binding
proves that planned quantitative marks resolve to the declared data.

## 4. PlotPlan Scaffold

`figure.py plan --backend matplotlib` writes a conservative scaffold. It records
the FigureSpec, declared data files, target, outputs, and every coverage item,
but it does not infer that a column named `score`, `time`, or `accuracy` has a
particular scientific role.

The scaffold remains `BLOCKED` until panels, encodings, series, and coverage
mappings are explicitly completed.

```bash
python scripts/figure.py plan path/to/F010-results.md \
  --backend matplotlib \
  --data path/to/results.csv \
  --output build/F010.plot-plan.json \
  --strict
```

Validate a completed plan with:

```bash
python scripts/figure.py validate-sidecar \
  plot-plan build/F010.plot-plan.json
```

## 5. Supported Panels

PlotPlan 1.0 supports simple multi-panel grids and four plot types:

```text
line
scatter
bar
heatmap
```

Each panel has a distinct scientific role and declares its grid location,
source, title, encoding, series, axes, legend, annotations, reference lines,
and missing policy.

### Line

Bind `x`, `y`, explicit series filters, and optional precomputed uncertainty.
Missing `y` values use a gap by default when `missing_policy: gap`; the backend
does not connect across or fill the observation.

### Scatter

Bind numeric `x` and `y`, explicit series, and optional numeric marker size.
The backend does not add regression lines, correlation labels, outlier removal,
or random jitter.

### Bar

Bind category, value, explicit groups, and optional precomputed uncertainty.
Category order is explicit or follows first appearance deterministically. The
baseline includes zero by default.

A non-zero baseline requires both:

```text
allow_nonzero_baseline: true
nonzero_baseline_rationale: ...
```

It remains an automated QA warning because truncated bars can exaggerate
differences.

### Heatmap

Bind long-form x category, y category, and numeric value. A heatmap declares a
color-scale kind, palette, and value label. Sequential color is the restrained
default. A diverging scale requires an explicit scientific center; the backend
does not guess that zero is meaningful.

Heatmap cells use vector-native marks rather than embedding a whole raster image
in SVG.

## 6. Missing Data

Each panel selects exactly one policy:

```text
error
gap
drop
```

- `error` blocks if any plot-required value is missing.
- `gap` preserves missing `y` observations in line plots.
- `drop` deliberately omits affected rows and records the count in the trace.

The backend never treats missing as zero and never imputes values. `gap` is not
supported for bar, scatter, or heatmap panels in PlotPlan 1.0.

## 7. Uncertainty

Uncertainty is authoritative, precomputed input. Declare its meaning and either:

```text
lower_column + upper_column
```

or:

```text
symmetric_column
```

Examples of `kind` include `95% CI`, `SD`, and `SE`. The backend does not infer
which one a column represents. Symmetric uncertainty must be non-negative;
lower and upper bounds must bracket the plotted value.

## 8. Axes, Units, and Clipping

Each axis records label, optional unit, scale, and optional limits.

Supported scales:

```text
linear
log
```

Log axes block when bound values include zero or negative numbers. `symlog` is
not implemented.

Explicit limits are checked against data and uncertainty. Clipping blocks unless
the axis explicitly declares `allow_clipping: true` with a rationale. The
backend does not truncate axes, reorder bars by performance, hide categories,
or select points to make a result appear stronger.

## 9. Scientific Annotations and Reference Lines

Annotations may use exact FigureSpec text, a data column, or a source-bound
constant. Scientific-looking values such as `+12%`, `winner`, or `SOTA` cannot
be added as free renderer content.

A reference line declares whether it is:

- a `design_reference`, such as a deliberately specified chance level; or
- a `source_bound_constant` tied to a declared data source and column.

Reference lines are not disguised data series.

## 10. Reproducible Source and Scoped Style

`author` creates a small `Fxxx.plot.py` runner pinned to the exact PlotPlan hash.
It contains no parallel series, axis, color, or scientific configuration. The
runner imports the versioned Matplotlib backend, rechecks the PlotPlan, executes
the Data Binding Gate, and writes a resolved trace.

```bash
python scripts/figure.py author build/F010.plot-plan.json \
  --output build/F010.plot.py
```

The profiles are intentionally limited:

```text
publication-default
presentation
grayscale
```

They use scoped Matplotlib configuration. They do not permanently mutate global
`rcParams`, claim venue compliance, or require SciencePlots. SVG keeps live text
where Matplotlib supports it; PDF uses embeddable TrueType settings.

## 11. Export and Provenance

Matplotlib is an optional runtime dependency. Its absence blocks only the
Matplotlib export/render capability; Draw.io and Native SVG remain available.
The skill never installs it automatically.

Matplotlib itself writes SVG, PDF, and PNG. No external SVG renderer is used.
The Artifact Manifest remains schema 1.0 because its open `metadata` object can
record, without breaking existing diagram manifests:

- Python and Matplotlib versions;
- PlotPlan and source hashes;
- each data input path and hash;
- target size and raster DPI;
- resolved trace path and hash;
- actual artifact path, hash, format, and dimensions.

The resolved trace records panel and series IDs, source and column bindings,
row and missing counts, uncertainty type, min/max-relevant execution context,
and digests of resolved plotting vectors. It does not duplicate the raw table.

## 12. Inspection and Outcomes

Automated inspection recomputes current data binding and compares it with the
recorded execution trace. It checks requested outputs, hashes, physical size,
PNG dimensions, PDF header/page dimensions, SVG live text, and obvious raster
embedding. It does not use OCR to reconstruct values from pixels.

The QA taxonomy remains:

```text
Scientific
Communication
Visual
Technical
```

A clean deterministic run reports `AUTOMATED_CHECKS_PASSED`, never full `PASS`.
Visual review should still inspect scientific emphasis, axes, legend, error
bars, series distinguishability, density, and final-size readability. Use one
or two targeted correction cycles when needed; human acceptance remains the
only route to `FINAL`.

## 13. Unified CLI

The existing command family dispatches on `backend: matplotlib` in PlotPlan:

```text
plan
author
lint
export
inspect
render
```

For a completed PlotPlan:

```bash
python scripts/figure.py render build/F010.plot-plan.json \
  --backend matplotlib \
  --work-dir build/F010-render
```

`repair` is intentionally unavailable. Revise the declarative PlotPlan and
rerun. There is no Matplotlib-specific second CLI universe.

## 14. Explicit Non-Goals

PlotPlan 1.0 does not implement pandas, Seaborn, Plotly, Excel, SQL, remote data,
statistical testing, bootstrapping, regression analysis, smoothing,
interpolation, automatic data cleaning, outlier removal, dashboard layouts,
interactive plots, OCR, or journal-compliance claims.
