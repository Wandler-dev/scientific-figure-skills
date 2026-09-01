# Scientific Figure Rendering Backends v1.0

## 1. Principle

Choose the backend after the scientific design is clear.

```text
Scientific question
→ figure archetype
→ visual design
→ backend
→ rendered artifact
```

Do not force the figure into the style of the tool that happens to be available.

Selection priorities:

```text
scientific suitability
→ editability or reproducibility
→ publication quality
→ revision cost
→ implementation efficiency
```

---

## 2. Quick Routing

| Figure need | Preferred backend | Bundled status |
|---|---|---|
| Method, architecture, workflow, evaluation, hierarchy | Native SVG / Draw.io | Stable |
| Quantitative results, ablations, diagnostics | Matplotlib | Stable; optional runtime |
| Mathematical or LaTeX-native diagram | TikZ | Not implemented |
| Presentation-first manual editing | PPTX | Not implemented |
| Large structured graph | Graph layout code + vector refinement | Not implemented |
| Public-facing conceptual illustration | Project-selected illustration workflow | Not implemented |
| Mixed multi-panel figure | Appropriate backend per panel, then compose | No bundled composition engine |

This is scientific selection guidance, not a claim that every listed tool is
implemented here. The bundled execution tracks are Draw.io, Native SVG, and
Matplotlib only; another project-provided tool must follow its own capability
and provenance contract.

---

## 3. Preferred Artifact Hierarchy

For publication-oriented work, prefer:

```text
editable or reproducible source
→ vector export where appropriate
→ raster preview
```

Examples:

```text
SVG source → SVG/PDF → PNG preview
Python source + data → PDF/SVG → PNG preview
draw.io source → SVG/PDF → PNG preview
```

A preview is useful for review but should not replace a better long-term source.

---

## 4. SVG

Best for structured scientific diagrams composed of boxes, labels, paths, connectors, and simple icons.

Strengths:

- scalable vector output;
- deterministic geometry;
- text and shapes can remain editable;
- good control of exact relations;
- text-based versioning.

Use native text, shapes, and paths where practical. Avoid implementing a technical diagram as one embedded raster image.

The bundled Native SVG adapter is opt-in and shares the same structured-diagram
RenderPlan 1.1 as Draw.io. It authors stable semantic object IDs, live text,
true nested groups for containment, and native connectors. SVG authoring and
strict lint are internal and require no external renderer.

The `.svg` source is also the vector artifact. PNG/PDF are optional dynamic
capabilities discovered through `rsvg-convert`, Chrome/Chromium headless, then
CairoSVG. Missing optional renderers do not make SVG authoring unavailable and
must not trigger a silent fallback.

QA:

- valid viewBox and crop;
- no clipping;
- text remains correct;
- embedded assets resolve;
- strokes and arrowheads scale appropriately;
- vector content has not been unintentionally rasterized.

For commands, source restrictions, capability behavior, and issue families,
read `09-svg-execution.md`.

---

## 5. draw.io

Best when researchers are likely to make visual edits such as moving boxes, changing labels, or rerouting connectors.

Strengths:

- convenient manual editing;
- strong grouping and alignment;
- practical connector routing;
- export to SVG, PDF, and PNG.

Use draw.io when human post-editability outweighs the benefits of fully programmatic geometry.

The bundled Draw.io execution adapter remains opt-in: the capability registry
has no default backend, and `plan` or `render` requires an explicit
`--backend drawio` selection.

The implemented closure is:

```text
FigureSpec 1.0
→ shared structured-diagram RenderPlan sidecar
→ native uncompressed mxGraph XML
→ structure and geometry lint
→ Draw.io Desktop CLI export
→ artifact manifest
→ normalized final-size and semantic QA report
```

The external Desktop CLI is required only for SVG, PDF, or PNG export. Do not
substitute the test double, generated imagery, OCR, or a raster-to-editable
conversion in production work.

QA:

- source opens correctly;
- connectors remain attached;
- export matches editor view;
- fonts render consistently;
- grouped objects remain editable.

For commands, repair boundaries, and issue codes, read
`08-drawio-execution.md`.

---

## 6. Python / Matplotlib and R

Use for real numerical data.

Strengths:

- authoritative values can remain tied to data;
- figures regenerate when results change;
- statistical plots use familiar visual conventions;
- vector export is available.

Do not manually draw bars, points, confidence intervals, or values when plotting code can generate them.

QA:

- source runs in the intended environment;
- values come from authoritative data;
- units, scales, ordering, and uncertainty are correct;
- vector export works;
- text is readable at final size;
- the actual plot is inspected after execution.

Use the project's existing analysis language where practical rather than introducing a second stack only for aesthetics.

The bundled Matplotlib adapter is optional and uses a separate PlotPlan 1.0. It
does not force axes, series, or data bindings into structured-diagram elements
and connectors.

```text
FigureSpec 1.0 + authoritative local data
→ PlotPlan 1.0
→ Data Binding Gate
→ reproducible Python entry point
→ Matplotlib SVG / PDF / PNG
→ provenance-aware artifact inspection
```

The core data loader supports local CSV, TSV, and JSON records without pandas.
Matplotlib is required only for authoring exports. If it is absent, diagram
capabilities remain available and plotting reports
`capability.matplotlib.missing`; the runtime never installs dependencies or
falls back silently.

Supported plot types are deliberately limited to line, scatter, bar, and
heatmap. Statistical testing, fitting, smoothing, interpolation, data cleaning,
and uncertainty calculation remain upstream responsibilities. For the complete
data, axis, uncertainty, export, and QA contract, read
`10-publication-plots.md`.

---

## 7. TikZ

Best for mathematical diagrams, theoretical structures, exact LaTeX notation, and manuscript-native typography.

Strengths:

- reproducible vector output;
- precise geometry;
- strong LaTeX integration.

Weaknesses:

- free-form illustration and rapid visual iteration can be expensive;
- complex layouts may require substantial debugging.

QA:

- source compiles;
- notation and fonts are correct;
- output scale and crop are appropriate;
- no clipping or unexpected line intersections occur.

---

## 8. PPTX

Best when presentation use and collaborator editing are major requirements.

Strengths:

- accessible manual editing;
- easy reuse in talks and meetings;
- native shapes, text, and arrows.

Weaknesses:

- export and text flow may vary by platform;
- version control is weaker than text-based formats.

QA:

- objects remain editable;
- layout survives reopening;
- text does not reflow unexpectedly;
- export quality is sufficient;
- external assets remain available.

---

## 9. Graph-Layout Code

Use Graphviz, NetworkX, igraph, or specialized layout tools when topology comes from structured data or many nodes must be positioned reproducibly.

Recommended workflow:

```text
structured graph
→ automatic layout
→ semantic simplification
→ vector refinement
```

Do not assume a library's default layout is publication-ready. Automatic layouts optimize graph criteria, not necessarily communication.

---

## 10. Image Generation

Use for conceptual illustration, graphical abstracts, public-facing research visuals, visual metaphors, or selected illustrative assets.

Do not use it as the final authority for:

- exact architecture diagrams;
- quantitative plots;
- dense labeled graphs;
- precise evaluation pipelines;
- figures with many exact scientific relations.

Generated imagery must be checked against the FigureSpec. Verify labels, object count, relationships, chronology, and any scientific claim.

When exact editability matters, use generated imagery as a draft or component and reconstruct the scientific structure in SVG or another controllable backend.

---

## 11. Hybrid Workflows

Hybrid rendering is often appropriate:

```text
image generation → illustrative asset → SVG composition with exact labels

graph layout → topology → SVG refinement

Matplotlib → result panels → vector multi-panel composition

draw.io → human refinement → SVG/PDF export
```

Each backend should handle the part it is best suited for.

When combining panels, standardize typography, semantic colors, line weight, panel spacing, and labels.

---

## 12. Backend Decision Questions

Ask:

- Is the figure primarily a diagram, plot, graph, mathematical object, or illustration?
- Does it contain exact labels, values, or relationships?
- Is it derived from numerical data?
- Will a human need to move objects manually?
- Should it regenerate automatically when data changes?
- Is vector output preferred?
- What type of revision is likely later?
- Can the backend express the design without excessive fragility?

Minimal rule:

```text
real quantitative plot → Python / R
structured scientific diagram → SVG / draw.io
strongly mathematical → TikZ
presentation-first editing → PPTX
primarily illustrative → image generation may be appropriate
```

---

## 13. Final Rule

Use the simplest backend that can faithfully implement the scientific design and preserve the required level of editability or reproducibility.
