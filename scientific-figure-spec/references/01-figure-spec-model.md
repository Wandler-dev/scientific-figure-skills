# FigureSpec Model v1.0

## 1. Purpose

A `FigureSpec` is the durable scientific and visual definition for one figure.

It connects:

```text
Scientific intent
→ required content and relationships
→ visual design
→ rendering requirements
→ rendered artifact
```

It is not:

- a raw image prompt;
- a transcript of every conversation;
- a mandatory approval form;
- a substitute for authoritative data;
- a guarantee that the final rendering is correct.

The specification should remain concise enough to maintain and precise enough to prevent scientific drift.

---

## 2. One Source of Truth

Version 1.0 uses one canonical seven-section model:

```text
1. Figure Identity
2. Scientific Purpose
3. Required Content
4. Scientific Structure & Relationships
5. Figure Design
6. Visual & Content Constraints
7. References & Rendering Requirements
```

Do not create parallel fields such as separate `Core Intent` and `Primary Message` sections that compete to define the same idea.

Each section has a distinct responsibility:

- Purpose explains why the figure exists.
- Required Content controls what must survive.
- Relationships control scientific meaning.
- Figure Design controls information architecture.
- Constraints prevent misleading encodings.
- Rendering Requirements control delivery.

---

## 3. Minimum Input

The minimum useful starting point is normally one concise `Core Message`.

A good Core Message explains:

- why the figure is needed;
- the central scientific point;
- what must remain clear after simplification.

The author does not need to solve layout, color, or backend selection before the agent can help.

When non-blocking details are missing, continue with restrained, clearly marked assumptions. Ask for input only when the gap prevents scientifically valid progress.

---

## 4. Author and Agent Responsibilities

The author remains authoritative for:

- scientific claims;
- required facts and terminology;
- interpretation of causal, temporal, and evidential relations;
- acceptance of the final artifact.

The agent may:

- clarify the intended message;
- identify overload or contradiction;
- recommend a figure archetype;
- simplify and group content;
- propose composition and visual hierarchy;
- select a backend;
- render and inspect the artifact;
- challenge a design that would miscommunicate the science.

The agent must not silently:

- remove Must Show content;
- change exact facts or terminology;
- convert temporal order into causality;
- turn an unresolved assumption into a fact;
- rewrite the scientific purpose merely to obtain a cleaner layout.

The agent may physically write author-supplied information into the FigureSpec. Ownership of the meaning does not require manual typing by the author.

---

## 5. Required and Optional Precision

Specify explicitly when scientific meaning could be lost:

- dominant message;
- Must Show content;
- exact labels and values;
- source binding;
- important relationships;
- primary visual anchor;
- semantic colors or connectors;
- misleading interpretations;
- intended use and required outputs.

Leave routine implementation flexible when it does not affect meaning:

- exact coordinates;
- minor spacing;
- decorative colors;
- connector bends;
- icon style;
- small typography refinements.

Complexity should follow the figure. Do not force every figure to use object IDs, exhaustive arrow taxonomies, or detailed geometry.

---

## 6. Status Model

FigureSpec v1.0 uses four states:

```text
DRAFT
READY
RENDERED
FINAL
```

### `DRAFT`

The definition may be incomplete.

### `READY`

The Core Message, Must Show content, important relationships, and visual design are sufficiently clear for rendering or deliberate design review.

`READY` does not claim formal human approval. It means the specification is usable.

### `RENDERED`

At least one concrete artifact exists, its path is recorded, and the artifact has been inspected.

### `FINAL`

The author accepts the current rendered artifact.

Automated validation can check structure and artifacts, but it cannot prove human acceptance.

---

## 7. What Belongs Outside the FigureSpec

Do not place the following in every core specification unless they are genuinely needed:

- a full conversation transcript;
- a log of every spacing change;
- repeated design-manual content;
- exhaustive backend instructions;
- arbitrary numeric quality scores;
- routine approval paperwork.

Meaningful decisions may remain in project notes, issue history, version control, or a short optional decision note. The core FigureSpec should continue to describe the current figure.

---

## 8. Completeness Standard

A specification is ready when another competent researcher or agent can determine:

1. why the figure exists;
2. what the reader should understand;
3. what cannot be omitted;
4. what must remain exact and where it comes from;
5. how the important elements relate;
6. what the reader sees first and how the eye should move;
7. what should be simplified;
8. what visual encodings carry meaning;
9. what the figure must not imply;
10. how and for what medium it should be delivered.

A short specification that answers these questions is better than a long file that duplicates itself.
