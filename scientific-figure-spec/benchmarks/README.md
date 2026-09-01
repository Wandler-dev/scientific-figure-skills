# Execution Benchmarks

These fixtures test execution contracts rather than figure aesthetics. B01–B08
exercise structured-diagram RenderPlan behavior through Draw.io and Native SVG.
B09–B12 exercise PlotPlan, authoritative-data binding, Matplotlib artifacts,
and negative quantitative scenarios.

| ID | Focus | Required result |
|---|---|---|
| B01 | Minimal directed workflow | author, strict lint, export, and QA pass |
| B02 | Candidate/Reference isolation | injected Reference → AI System leakage is blocked |
| B03 | Geometry and connector repair | bounded repair restores plan-owned geometry and endpoint |
| B04 | Final-size readability | baseline passes; undersized text requires revision |
| B05 | F001 backend parity | normalized Draw.io and SVG scientific structures match |
| B06 | Containment hierarchy | both backends preserve true parent-child nesting without a flow edge |
| B07 | Native SVG defects | deterministic invalid sources emit stable SVG issue codes |
| B08 | SVG export capability | SVG-only works internally; optional PNG/PDF capability is explicit |
| B09 | Line plot with uncertainty | data hashes, gaps, precomputed intervals, and vector/raster outputs remain reproducible |
| B10 | Grouped bar plot | groups, exact values, uncertainty, deterministic order, and zero baseline remain data-bound |
| B11 | Heatmap | categories, values, units, color scale, and deterministic order remain explicit |
| B12 | Negative data binding | stale identities, missing inputs, unbound values, invalid axes, and unresolved coverage block execution |

The Draw.io executable used in automated tests is the explicitly labeled
`tests/fixtures/fake_drawio_cli.py` test double. Production export remains bound
to an installed Draw.io Desktop CLI.

`tests/fixtures/fake_svg_renderer.py` is likewise test-only. Native SVG source
does not need a renderer; production PNG/PDF output uses a discovered or
explicitly selected real renderer.

B09 and B10 execute against real Matplotlib when it is installed. Their data
and PlotPlans are small fixed fixtures; tests skip production rendering cleanly
when the optional runtime is absent. B12 never relies on a fake scientific data
producer.
