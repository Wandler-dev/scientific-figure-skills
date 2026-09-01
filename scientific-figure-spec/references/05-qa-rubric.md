# Scientific Figure QA Rubric v1.0

## 1. Purpose

QA asks:

> Does the actual rendered artifact faithfully and clearly communicate the FigureSpec?

Review the export itself, not only the specification, code, or editing canvas.

Use four dimensions:

```text
Scientific
Communication
Visual
Technical
```

Scientific and interpretation problems outrank cosmetic polish.

---

## 2. Outcomes

### `AUTOMATED_CHECKS_PASSED`

The executable checks completed without a recorded blocking, major, or minor
finding. This is deliberately narrower than `PASS`: it covers FigureSpec
coverage, source structure, artifact identity, machine-checkable semantics,
and final-size constraints, but does not claim that scientific truth, primary
visual emphasis, communication hierarchy, or overall visual quality received
complete review.

### `PASS`

The figure is scientifically faithful, understandable, readable, and technically usable for the current stage.

### `REVISION_REQUIRED`

The figure is usable in principle but contains issues that should be fixed before final acceptance.

### `BLOCKED`

A serious problem prevents valid use, such as fabricated information, a wrong scientific relation, missing critical content, unreadable essential labels, or a broken export.

---

## 3. Review Order

Fix issues in this order:

```text
scientific correctness
→ interpretation
→ readability
→ hierarchy
→ technical defects
→ cosmetic polish
```

Do not polish shadows while an arrow communicates the wrong relation.

---

## 4. Scientific QA

Check:

- Does the artifact preserve the Core Message?
- Is every Must Show item present?
- Are exact terms, values, and labels correct?
- Is source-bound content represented faithfully?
- Was any unsupported value, model name, evidence, chronology, or result introduced?
- Do arrows, grouping, alignment, color, and position imply only supported relations?
- Are temporal order and causality distinguishable?
- Are Candidate and Reference, observed and hypothetical, or schematic and empirical content clearly separated?

Scientific blockers include:

- fabricated factual or numerical content;
- missing critical Must Show information;
- an incorrect causal, temporal, or evidential relation;
- Reference shown as an input when it is not;
- a schematic displayed as if it were an empirical result;
- terminology that changes scientific meaning.

---

## 5. Communication QA

Check:

- What attracts attention first?
- Is that the intended primary message?
- Can the high-level story be understood quickly?
- Is the starting point and reading order clear?
- Does visual weight match Primary, Secondary, and Supporting information?
- Are labels concise and placed near what they describe?
- Are important connectors unambiguous?
- Are related objects grouped and unrelated objects separated?
- Does each panel have a distinct role?
- Does repeated content add comparison, multiplicity, progression, or detail?

A figure may contain all required objects and still fail if the visual emphasis communicates the wrong story.

---

## 6. Visual QA

Inspect the figure at approximately its intended physical or display size.

Check:

- important text and linework remain readable;
- the primary region has sufficient space;
- whitespace supports grouping;
- comparison objects are aligned;
- internal padding is consistent;
- the palette is restrained and meaningful;
- critical distinctions do not rely only on color;
- typography and terminology are consistent;
- containers and icons have clear roles;
- shadows, gradients, patterns, and decoration do not compete with the science.

If the figure only works when enlarged far beyond its intended size, simplify it.

---

## 7. Technical QA

Check:

- no required text, arrowhead, node, border, or legend is clipped;
- no unintended overlap obscures meaning;
- the export matches the working source;
- fonts and external assets resolve correctly;
- the canvas, crop, margins, and aspect ratio are intentional;
- raster resolution is sufficient for its use;
- vector content remains vector where required;
- editable or reproducible source exists and works;
- recorded output paths point to actual artifacts.

Backend-specific checks belong in `06-rendering-backends.md`.

For executable Draw.io or Native SVG work, the QA report also verifies:

- the current FigureSpec hash still matches the plan binding;
- every Must Show and Relationships bullet is present in the RenderPlan
  coverage ledger;
- every mapped coverage representation still exists in the editable source,
  including true parent-child containment where required;
- normalized source objects, semantic roles, parent hierarchy, connectors, and
  relation kinds still match the RenderPlan;
- no obvious unplanned scientific label, semantic object, or relation was added
  by the backend source;
- the artifact hashes still match the export manifest;
- required formats were actually exported;
- source and artifact aspect ratios match the RenderPlan;
- labels meet the declared minimum point size at intended final width;
- required labels and relations remain present;
- forbidden relations remain absent;
- semantic Candidate, Reference, and Evidence colors remain bound;
- source and SVG exports contain no unintended embedded raster content.

These checks are evidence about the artifact. They do not establish scientific
truth or replace author acceptance.

For data-bound Matplotlib work, the QA report also verifies:

- the current FigureSpec and every declared data hash still match PlotPlan;
- every required FigureSpec item has an explicit plot representation or a
  recorded unresolved blocker;
- all plotted series, uncertainty values, annotation values, and source-bound
  reference lines resolve to declared authoritative data;
- required columns exist, numeric encodings are finite, and declared
  missing-data policy was applied without hidden interpolation or filling;
- log axes contain no zero or negative bound values;
- bar baselines, axis limits, uncertainty bounds, and heatmap color semantics
  follow the declared plan without silent exaggeration or clipping;
- the backend's resolved execution trace matches the validated bindings;
- the reproducible Python source is still bound to the same PlotPlan;
- SVG, PDF, and PNG artifacts exist as requested and match manifest hashes;
- SVG keeps meaningful live text and vector output has not become raster-only;
- final-size text and raster dimensions meet the declared target.

Plot inspection uses the plan, data, execution trace, and artifact metadata. It
does not use OCR to reconstruct plotted values. Grayscale distinguishability is
an advisory heuristic, not an accessibility certification.

After deterministic checks, visually inspect the actual preview when vision is
available. Verify the primary anchor, reading order, scientific and information
hierarchy, redundancy, spacing, label density, connector ambiguity, obvious
collision, and balance at final size. Apply one or two targeted correction
cycles by default; stop when the checks pass and no obvious visual defect
remains. Do not require OCR, a separate critic agent, or a fixed iteration count.

---

## 8. Minimal Checklist

### Scientific

- [ ] The artifact matches the Core Message.
- [ ] All Must Show content is present.
- [ ] No unsupported fact or implication was introduced.

### Communication

- [ ] The primary message is visually obvious.
- [ ] Reading order is clear.
- [ ] Important arrows, labels, and grouping are unambiguous.
- [ ] Every major panel or repeated element adds information.

### Visual

- [ ] The figure is readable at intended final size.
- [ ] Visual hierarchy matches scientific hierarchy.

### Technical

- [ ] No important clipping, overlap, or export defect exists.
- [ ] Required editable or reproducible outputs are usable.

Any `NO` answer should become an actionable issue.

---

## 9. Issue Format

Use:

```text
Severity: BLOCKING / MAJOR / MINOR
Category: Scientific / Communication / Visual / Technical
Issue: ...
Why it matters: ...
Recommended fix: ...
```

Example:

```text
Severity: MAJOR
Category: Scientific
Issue: Temporal and causal arrows use the same style.
Why it matters: Readers may infer unsupported causality.
Recommended fix: Use distinct connector semantics and verify the caption.
```

Avoid arbitrary scores such as `8.7/10` when actionable diagnosis is more useful.

---

## 10. When to Reconsider the Design

Fix implementation issues directly:

- overlap;
- spacing;
- alignment;
- connector routing;
- export defects;
- minor typography;
- crop or resolution.

Return to design when the fix would change:

- Core Message;
- Must Show content;
- main comparison;
- major reading order;
- panel structure;
- an important scientific relation;
- the primary visual anchor.

---

## 11. Final Approval Standard

A figure is ready for author acceptance when:

1. no known scientific blocker remains;
2. required content is complete;
3. the primary message is clear;
4. reading order and important relationships work;
5. the artifact is readable at intended size;
6. no major technical defect remains;
7. required sources and outputs are available;
8. the author has seen the current rendered artifact.

Perfection is not required. Scientific correctness and clear communication are.
