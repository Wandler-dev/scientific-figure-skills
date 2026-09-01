# Scientific Figure Design Principles v1.0

## 1. Priority Order

When design goals conflict, use:

```text
Scientific faithfulness
→ communication clarity
→ information hierarchy
→ readability
→ visual consistency
→ aesthetic polish
```

A beautiful figure that changes the science is a failed figure. A correct figure that cannot be read at publication size is also a failed figure.

---

## 2. Twelve Core Principles

### 2.1 Start from the scientific message

Decide what the figure should make easier to understand before choosing layout, color, icons, or visual style.

### 2.2 Give the figure one dominant communication goal

Supporting ideas may exist, but the reader should quickly understand what the figure is fundamentally about.

### 2.3 Match visual hierarchy to scientific hierarchy

Primary, secondary, and supporting content should differ in space, contrast, detail, and visual weight. Do not give every valid component equal emphasis.

### 2.4 Use the visual relation that best matches the scientific relation

Use containment for hierarchy, alignment for comparison, temporal axes for time, and arrows only for relationships that are genuinely directional.

### 2.5 Use space as structure

Whitespace communicates separation, grouping, hierarchy, and transition. Do not fill every empty area merely to make the figure look complete.

### 2.6 Prefer fewer strong regions

Create a panel only when it answers a distinct scientific question. Avoid one-icon, one-sentence cards and dashboard-like fragmentation.

### 2.7 Make every element earn its place

A panel, icon, label, mini-diagram, or repeated object should add information, structure, recognition, comparison, progression, or intentional emphasis.

A practical test:

> If this element disappears, does scientific understanding or structural clarity become worse?

If not, remove or simplify it.

### 2.8 Treat arrows, colors, shapes, and grouping as semantic objects

Define their meaning when readers could infer a scientific distinction. Keep the number of encodings small and consistent.

### 2.9 Simplify before shrinking

When the figure is crowded, remove optional detail, aggregate repeated structure, or use overview-to-zoom. Do not solve overload only with tiny text.

### 2.10 Design at final size

Inspect single-column, double-column, website, poster, or presentation output at its intended display size. Important labels and relations should not depend on zoom.

### 2.11 Maintain a shared visual grammar across a paper

Reuse terminology, semantic colors, shapes, line styles, and typography where the same concepts recur. Consistency does not require identical layouts.

### 2.12 Preserve revision value

Prefer editable or reproducible sources. Scientific figures change as terminology, results, manuscript order, and reviewer requests evolve.

---

## 3. Reading Order and Composition

The reader should know where to begin without relying entirely on numbered labels.

Common reading structures:

```text
left → right
top → bottom
overview → detail
input → transformation → output
candidate/reference → comparison → evaluation
past → present → future
```

Use a central anchor when one representation or system is scientifically dominant. Use a sequential composition when the story is genuinely sequential.

Controlled asymmetry is often useful:

```text
20% supporting input
50% scientific core
30% output or evaluation
```

This may communicate emphasis better than equal thirds.

---

## 4. Typography

Use a small functional hierarchy:

```text
major region title
panel or section title
object label
annotation
```

Keep labels concise. Long explanations belong in the caption or manuscript.

Use readable, portable fonts and stable terminology. Do not alternate among synonyms such as `Reference Graph`, `Gold Graph`, and `Ground Truth` unless the paper intentionally defines them as equivalent.

---

## 5. Color and Shape

Use a restrained semantic palette. Not every available project color needs to appear in every figure.

Good uses of color:

- Candidate vs Reference;
- observed vs hypothetical;
- input vs output;
- stage or semantic object type;
- evidence vs inference;
- warning or exception.

Critical distinctions should also use labels, shape, position, border style, or line pattern.

Readers assume different shapes carry different meanings. Avoid unnecessary shape diversity and mixed icon styles.

---

## 6. Arrows and Connectors

An arrow should have a defined meaning, such as:

```text
process flow
temporal progression
data flow
transformation
causal influence
information access
prediction
mapping
```

Comparison and containment often need no arrow.

When multiple relation types exist, distinguish only those that matter scientifically. Avoid line crossings, hidden arrowheads, ambiguous attachment points, and spaghetti diagrams.

---

## 7. Repetition and Abstraction

Repetition is useful when differences among repeated objects matter.

Appropriate examples:

- several source cards representing heterogeneous evidence;
- repeated plots under distinct conditions;
- observed vs predicted structures;
- overview and zoomed detail;
- alternative scenarios.

Weak repetition:

- many identical document icons;
- four nearly identical mini-graphs with no distinct message;
- repeated labels that communicate the same fact;
- decorative checkmarks or cards used to fill space.

For dense graphs or hierarchies, prefer representative structure, grouping, or overview-to-detail over microscopic miniaturization.

---

## 8. Medium-Specific Design

### Main-paper figure

Prioritize the central scientific message and essential labels. Move secondary detail to the caption or supplement.

### Supplementary figure

More detail is acceptable, but hierarchy and readability still matter.

### Website or presentation

Larger text, more whitespace, and stronger illustration may be appropriate. Technical labels may be reduced.

### Result figure

Use conventional statistical visualization when it answers the question clearly. Familiarity is an advantage.

---

## 9. Common Failure Modes

### Equal-weight boxes

A row of identical modules often hides the actual hierarchy. Identify the core, inputs, outputs, and supporting context.

### Dashboard composition

Many rounded cards, icons, statistics, and mini-panels can make a paper figure resemble a product UI. Use containers only for meaningful grouping.

### Tiny text everywhere

Shorten, aggregate, remove, or move detail to the caption before reducing font size.

### Too many colors

Different colors should correspond to real scientific distinctions.

### Meaningless arrows

Do not connect adjacent objects merely because an arrow looks natural.

### Repetition without information

One representative graph plus a clear multiplicity label may communicate more than four duplicate mini-graphs.

### Decorative complexity

Avoid gradients, strong shadows, particles, glowing borders, stars, and background patterns unless the medium and message genuinely benefit.

### Literal copying of a reference

Borrow only the declared aspects: composition, palette, typography, line treatment, density, or scientific organization. The current scientific message has priority.

### Diagram as screenshot

Deliver a clean crop, intentional margins, correct canvas, and preserved vector quality where appropriate.

---

## 10. Pre-Render Design Check

Before rendering, answer:

### Message

- What is the one dominant scientific message?
- Which region is the primary visual anchor?

### Structure

- What is the reading order?
- Does the composition match the scientific relationships?

### Necessity

- Does every major element add distinct information or intentional emphasis?
- Can repeated detail be abstracted?

### Semantics

- What do important arrows, colors, shapes, and groupings mean?
- Could any relation be misread?

### Readability

- Will the design work at intended final size?
- Can labels remain concise?

If these answers are unclear, the design is not ready.
