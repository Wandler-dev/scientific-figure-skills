#!/usr/bin/env python3
"""FigureSpec requirement extraction and execution-coverage helpers.

Coverage is deliberately derived from the canonical FigureSpec rather than from
the RenderPlan's own assertions.  This keeps automated QA bound to the
scientific source of truth without changing the FigureSpec 1.0 schema.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import validate_figure_spec as figure_spec_validator


def normalized_requirement_text(value: str) -> str:
    """Return a stable comparison form while preserving scientific wording."""

    value = unicodedata.normalize("NFKC", value).casefold()
    value = value.replace("–", "-").replace("—", "-")
    return " ".join(value.split()).rstrip(".")


def requirement_tokens(value: str) -> set[str]:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return {
        token.casefold()
        for token in re.findall(r"[A-Za-z0-9]+", value)
        if token.casefold()
        not in {
            "a",
            "an",
            "and",
            "as",
            "at",
            "be",
            "by",
            "for",
            "from",
            "in",
            "is",
            "of",
            "or",
            "the",
            "then",
            "through",
            "to",
            "with",
        }
    }


def _bullet_items(body: str | None) -> list[str]:
    if body is None:
        return []
    cleaned = figure_spec_validator.HTML_COMMENT_RE.sub("", body)
    result: list[str] = []
    for line in cleaned.splitlines():
        match = re.match(r"^\s*[-*+]\s+(?P<item>.+?)\s*$", line)
        if match is None:
            continue
        item = match.group("item").strip()
        if item.casefold() in figure_spec_validator.PLACEHOLDER_VALUES:
            continue
        result.append(item)
    return result


def extract_spec_requirements(spec_path: Path) -> dict[str, list[str]]:
    """Read the two canonical FigureSpec sections that form the coverage gate."""

    text = spec_path.read_text(encoding="utf-8")
    headings = figure_spec_validator.collect_headings(text)
    return {
        "must_show": _bullet_items(
            figure_spec_validator.section_body(text, headings, "3.1 Must Show")
        ),
        "relationships": _bullet_items(
            figure_spec_validator.section_body(text, headings, "4.1 Relationships")
        ),
    }


def split_relationship(value: str) -> tuple[str, str]:
    pieces = re.split(r"\.\s*Relation:\s*", value, maxsplit=1, flags=re.I)
    expression = pieces[0].strip().rstrip(".")
    descriptor = pieces[1].strip().rstrip(".") if len(pieces) == 2 else ""
    return expression, descriptor


def classify_relationship(value: str) -> str:
    """Classify only canonical, explicitly signalled relation semantics."""

    expression, descriptor = split_relationship(value)
    combined = f"{expression} {descriptor}".casefold()
    if any(token in combined for token in ("containment", "hierarchy", " contains ")):
        return "containment"
    if any(token in combined for token in ("evidence support", "provenance", " supports ")):
        return "evidence_support"
    if any(token in combined for token in ("independent", "external comparison target")):
        return "independence"
    if any(token in descriptor.casefold() for token in ("evaluation output", "diagnostic output")):
        return "evaluation_output"
    if any(token in combined for token in ("alignment", "comparison")):
        return "comparison"
    if re.search(r"(?:↔|→|<-|->)", expression):
        return "flow"
    return "unknown"


def coverage_summary(
    must_show: Iterable[dict[str, Any]],
    relationships: Iterable[dict[str, Any]],
) -> dict[str, int]:
    must_show_items = list(must_show)
    relationship_items = list(relationships)
    mapped_must_show = sum(item.get("status") == "MAPPED" for item in must_show_items)
    mapped_relationships = sum(
        item.get("status") == "MAPPED" for item in relationship_items
    )
    return {
        "must_show_total": len(must_show_items),
        "must_show_mapped": mapped_must_show,
        "relationships_total": len(relationship_items),
        "relationships_mapped": mapped_relationships,
        "unresolved_total": (
            len(must_show_items)
            - mapped_must_show
            + len(relationship_items)
            - mapped_relationships
        ),
    }


def coverage_is_complete(plan: dict[str, Any]) -> bool:
    coverage = plan.get("spec_coverage")
    if not isinstance(coverage, dict):
        return False
    summary = coverage.get("summary")
    return (
        coverage.get("status") == "COMPLETE"
        and isinstance(summary, dict)
        and summary.get("unresolved_total") == 0
    )


def requirement_multiset(values: Iterable[str]) -> Counter[str]:
    return Counter(normalized_requirement_text(value) for value in values)
