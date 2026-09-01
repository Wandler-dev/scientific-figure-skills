# Scientific Figure Archetypes v1.0

## 1. Purpose

A figure archetype is a reusable answer to a communication problem, not a fixed visual template.

Select the archetype from the reader's reasoning task:

| Reader question | Primary archetype |
|---|---|
| What is the whole method or benchmark? | Method Overview |
| What components exist and interact? | Architecture |
| What happens first, next, and last? | Workflow / Pipeline |
| What differs between training and inference? | Training–Inference |
| How was the dataset or benchmark built? | Benchmark Construction |
| What is compared and how is quality judged? | Evaluation Framework |
| What contains what? | Hierarchical Structure |
| How does the process evolve over time? | Process / Timeline |
| Through what mechanism does an outcome arise? | Mechanism / Interaction |
| How do alternatives differ? | Comparison / Taxonomy |
| What does one concrete example look like? | Case Study / Example |
| What did experiments reveal? | Results / Diagnostics |

Use one primary archetype. Add supporting archetypes only when they serve the main composition.

---

## 2. Archetype Guidance

### 2.1 Method Overview

Use for a compact mental model of the whole method, often in Figure 1.

Typical structure:

```text
Input / Context → Core Method → Output / Evaluation
```

Prioritize one central story. Do not reproduce the full implementation or combine method, results, ablations, and applications merely because space exists.

### 2.2 Architecture

Use when components and interfaces matter more than chronological order.

Typical structure:

```text
Component A ↔ Component B
        ↓
     Shared Core
        ↓
       Output
```

Do not use sequential arrows when the actual relation is bidirectional, shared, or structural.

### 2.3 Workflow / Pipeline

Use for ordered operations or transformations.

Typical structure:

```text
Input → Step 1 → Step 2 → Output
```

Compress repeated internal detail. Do not force parallel processes into one artificial chain.

### 2.4 Training–Inference

Use when available information and operations differ by phase.

Shared components should look shared. Phase-specific information paths should remain distinct. Prevent label, future-information, or reference leakage into inference.

### 2.5 Benchmark Construction

Use when raw sources become a dataset, benchmark, annotation set, or structured resource.

Typical structure:

```text
Sources → Collection → Filtering / Verification → Construction → Benchmark
```

Avoid turning the figure into a statistics dashboard or implying quality guarantees the process does not establish.

### 2.6 Evaluation Framework

Use when the main question is what is compared and how quality is measured.

Typical structure:

```text
Candidate ─┐
           → Alignment / Comparison → Diagnostics
Reference ─┘
```

Keep the Reference visually outside the evaluated system's reconstruction path. Do not invent scores in a conceptual evaluation figure.

### 2.7 Hierarchical Structure

Use when containment or levels are central.

Prefer nested containers, aligned levels, or overview-to-zoom structures. Containment should look like containment rather than process flow.

### 2.8 Process / Timeline

Use for temporal progression, stages, observed history, or branching futures.

Distinguish temporal order from causal influence. Show uncertainty or alternatives differently from observed facts.

### 2.9 Mechanism / Interaction

Use when relationships explain how or why an effect emerges.

Relations matter more than containers. Use directional or causal arrows only when supported. Simplify dense interaction networks rather than hiding them under thin lines.

### 2.10 Comparison / Taxonomy

Use for alternatives, categories, design spaces, or trade-offs.

Align compared objects and use the same criteria and visual scale. Avoid paragraph-heavy scorecards or taxonomies with unexplained overlap.

### 2.11 Case Study / Example

Use when a concrete instance clarifies an abstract method or representation.

Distinguish real, synthetic, and schematic examples. Keep case-specific detail subordinate to the general scientific point.

### 2.12 Results / Diagnostics

Use for actual empirical findings.

Prefer conventional, data-driven plots such as line plots, bars, scatter plots, distributions, heatmaps, and confidence intervals. Show honest scales, units, baselines, and uncertainty where relevant.

---

## 3. Composition Patterns

Archetypes describe reasoning. Composition patterns describe spatial organization.

### Left-to-right

Best for sequence, transformation, and benchmark construction.

### Top-to-bottom

Useful for narrow layouts, levels, or column-constrained figures.

### Central anchor

Best when one representation or system is conceptually dominant.

### Overview → zoom

Best when readers need both global context and local detail.

### Side-by-side

Best for Candidate / Reference, before / after, or method comparisons.

### Small multiples

Best when the same visual grammar is repeated across meaningful conditions. Avoid when repeated panels communicate no important difference.

### Branching

Best for alternative futures, scenarios, or decision paths. Do not use branching for one deterministic sequence.

---

## 4. Common Confusions

```text
Architecture = what exists and interacts
Pipeline = what happens in sequence

Hierarchy = what contains what
Pipeline = what becomes what

Process = what happens over time
Mechanism = why or through what interaction it happens

Evaluation = how quality is measured
Results = what measurements were obtained

Method Overview = selective mental model
Architecture = internal component organization
```

The visual encoding should preserve these distinctions.

---

## 5. When to Split a Figure

Consider splitting when:

- two unrelated primary messages compete;
- the reader must repeatedly change reading direction;
- conceptual overview and quantitative results fight for space;
- each major region requires a different visual grammar;
- labels become unreadable at target size;
- one region could stand alone with its own caption and scientific purpose.

Do not split automatically. Some overview figures legitimately combine several stages under one coherent story.

---

## 6. Recommended Specification Entry

```text
Primary Archetype:
...

Secondary Archetype(s):
...

Why:
...
```

Rejected alternatives are optional and should be recorded only when the choice is genuinely non-obvious.
