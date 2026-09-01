#!/usr/bin/env python3
"""Backend-neutral structured-diagram planning from FigureSpec 1.0.

This module owns scientific elements, hierarchy, connectors, semantic styles,
assertions, geometry, and exhaustive FigureSpec coverage. Backend adapters must
implement this plan without changing its scientific meaning.
"""

from __future__ import annotations

import os
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import validate_figure_spec as figure_spec_validator
from figure_coverage import (
    classify_relationship,
    coverage_is_complete,
    coverage_summary,
    extract_spec_requirements,
    requirement_tokens,
    split_relationship,
)
from figure_runtime import (
    sha256_file,
    validate_render_plan_contract,
    write_json_atomic,
)


class DiagramPlanError(RuntimeError):
    """Raised when a backend-neutral diagram plan cannot be produced safely."""


DEFAULT_PALETTE = {
    "ink": "#17324D",
    "muted": "#607286",
    "paper": "#FFFFFF",
    "panel": "#F7F9FC",
    "line": "#6B7F93",
    "input_fill": "#FFF5D9",
    "input_stroke": "#C28A24",
    "system_fill": "#E5F6F3",
    "system_stroke": "#2C8A7D",
    "candidate_fill": "#E7F0FF",
    "candidate_stroke": "#2F6FB6",
    "reference_fill": "#F1EAFE",
    "reference_stroke": "#7655A6",
    "diagnostic_fill": "#F4F7FB",
    "diagnostic_stroke": "#7890A8",
}


def _normalized_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in value if character.isalnum())


def _slug(value: str, *, prefix: str = "el") -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    words = re.findall(r"[A-Za-z0-9]+", normalized.lower())
    base = "-".join(words[:8]) or "item"
    return f"{prefix}-{base}"[:120].rstrip("-")


def _unique_id(base: str, used: set[str]) -> str:
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


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


def _find_label(reference: str, labels: Iterable[str]) -> str | None:
    normalized = _normalized_text(reference)
    candidates: list[tuple[int, str]] = []
    for label in labels:
        token = _normalized_text(label)
        if not token:
            continue
        if token in normalized or normalized in token:
            candidates.append((len(token), label))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def _unique_role_label(labels: Iterable[str], role: str) -> str | None:
    matches = [label for label in labels if _semantic_role(label) == role]
    return matches[0] if len(matches) == 1 else None


def _analyze_relationships(
    lines: Iterable[str], labels: list[str]
) -> list[dict[str, Any]]:
    """Parse canonical relations conservatively and retain every source line."""

    result: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        expression, descriptor = split_relationship(line)
        relation_type = classify_relationship(line)
        requirement: dict[str, Any] = {
            "id": f"relationship-{index:03d}",
            "source_ref": f"4.1 Relationships[{index}]",
            "source_text": line,
            "relation_type": relation_type,
            "relation": descriptor or relation_type.replace("_", " "),
            "source_label": None,
            "target_label": None,
            "directed": True,
            "parse_status": "UNRESOLVED",
            "reason": "No supported canonical relation mapping was found.",
        }

        arrow = re.match(
            r"^(?P<left>.+?)\s*(?P<operator>↔|→|<-|->)\s*(?P<right>.+?)$",
            expression,
        )
        if arrow is not None:
            left = _find_label(arrow.group("left"), labels)
            right = _find_label(arrow.group("right"), labels)
            operator = arrow.group("operator")
            if operator == "<-":
                left, right = right, left
            if left is not None and right is not None and left != right:
                requirement.update(
                    {
                        "source_label": left,
                        "target_label": right,
                        "directed": operator != "↔",
                        "parse_status": "MAPPED",
                        "reason": "",
                    }
                )
            elif relation_type == "evaluation_output":
                # The endpoints are explicit conceptual groups rather than exact
                # labels.  The planner maps this only if it can construct the
                # comparison hub and diagnostic container below.
                requirement.update(
                    {
                        "parse_status": "DEFERRED",
                        "reason": "Requires an explicit comparison-to-diagnostics representation.",
                    }
                )

        if relation_type == "containment" and requirement["parse_status"] == "UNRESOLVED":
            containment = re.match(
                r"^(?P<parent>.+?)\s+(?:contains?|includes?|comprises?)\s+(?P<child>.+?)$",
                expression,
                flags=re.I,
            )
            if containment is not None:
                parent = _find_label(containment.group("parent"), labels)
                child = _find_label(containment.group("child"), labels)
                if parent is not None and child is not None and parent != child:
                    requirement.update(
                        {
                            "source_label": parent,
                            "target_label": child,
                            "directed": False,
                            "parse_status": "MAPPED",
                            "reason": "",
                        }
                    )

        if relation_type == "evidence_support" and requirement["parse_status"] == "UNRESOLVED":
            support = re.match(
                r"^(?P<source>.+?)\s+supports?\s+(?P<target>.+?)$",
                expression,
                flags=re.I,
            )
            if support is not None:
                source = _find_label(support.group("source"), labels)
                target = _find_label(support.group("target"), labels)
                if "evidence" in support.group("source").casefold():
                    evidence_label = _unique_role_label(labels, "evidence")
                    if evidence_label is not None:
                        source = evidence_label
                if target is None and "epg" in support.group("target").casefold():
                    target = _unique_role_label(labels, "candidate")
                if source is not None and target is not None and source != target:
                    requirement.update(
                        {
                            "source_label": source,
                            "target_label": target,
                            "directed": True,
                            "parse_status": "MAPPED",
                            "reason": "",
                        }
                    )

        if relation_type == "independence":
            reference = _find_label(expression, labels) or _unique_role_label(
                labels, "reference"
            )
            if reference is not None:
                requirement.update(
                    {
                        "source_label": reference,
                        "parse_status": "DEFERRED",
                        "reason": "Requires a reference-separation assertion.",
                    }
                )

        result.append(requirement)
    return result


def _longest_directed_chain(labels: list[str], relations: list[dict[str, Any]]) -> list[str]:
    adjacency: dict[str, list[str]] = defaultdict(list)
    indegree = {label: 0 for label in labels}
    for relation in relations:
        if not relation["directed"]:
            continue
        source = relation["source_label"]
        target = relation["target_label"]
        adjacency[source].append(target)
        indegree[target] = indegree.get(target, 0) + 1

    best: list[str] = []

    def walk(node: str, path: list[str]) -> None:
        nonlocal best
        if len(path) > len(best):
            best = list(path)
        for target in adjacency.get(node, []):
            if target not in path:
                walk(target, [*path, target])

    starts = [label for label in labels if indegree.get(label, 0) == 0 and adjacency.get(label)]
    for start in starts:
        walk(start, [start])
    return best


def _semantic_role(label: str) -> str:
    lowered = label.casefold()
    if "fidelity" in lowered or "diagnostic" in lowered or "metric" in lowered:
        return "diagnostic"
    if "evidence" in lowered:
        return "evidence"
    if "candidate" in lowered:
        return "candidate"
    if "reference" in lowered or "gold" in lowered:
        return "reference"
    if "reconstruction" in lowered or "system" in lowered or "model" in lowered:
        return "system"
    return "content"


def _style_for_role(role: str, *, container: bool = False) -> dict[str, Any]:
    if container:
        fill = DEFAULT_PALETTE["panel"]
        stroke = "#C8D3DF"
    elif role == "evidence":
        fill = DEFAULT_PALETTE["input_fill"]
        stroke = DEFAULT_PALETTE["input_stroke"]
    elif role == "system":
        fill = DEFAULT_PALETTE["system_fill"]
        stroke = DEFAULT_PALETTE["system_stroke"]
    elif role == "candidate":
        fill = DEFAULT_PALETTE["candidate_fill"]
        stroke = DEFAULT_PALETTE["candidate_stroke"]
    elif role == "reference":
        fill = DEFAULT_PALETTE["reference_fill"]
        stroke = DEFAULT_PALETTE["reference_stroke"]
    elif role == "diagnostic":
        fill = DEFAULT_PALETTE["diagnostic_fill"]
        stroke = DEFAULT_PALETTE["diagnostic_stroke"]
    else:
        fill = DEFAULT_PALETTE["paper"]
        stroke = DEFAULT_PALETTE["line"]
    return {
        "fill": fill,
        "stroke": stroke,
        "font_color": DEFAULT_PALETTE["ink"],
        "font_size_px": 17,
        "bold": role in {"candidate", "reference", "system"},
        "rounded": True,
        "align": "center",
        "vertical_align": "middle",
    }


def _parse_aspect_ratio(value: str | None) -> float:
    if value:
        match = re.search(r"(?P<ratio>\d+(?:\.\d+)?)\s*:\s*1", value)
        if match:
            ratio = float(match.group("ratio"))
            if 0.5 <= ratio <= 5:
                return ratio
    return 1.8


def _parse_formats(value: str | None) -> list[str]:
    lowered = (value or "").casefold()
    formats = [item for item in ("svg", "pdf", "png") if item in lowered]
    return formats or ["svg"]


def _coverage_ref(kind: str, *ids: str) -> dict[str, Any]:
    return {"kind": kind, "ids": list(ids)}


def _dedupe_coverage_refs(values: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for value in values:
        key = (value["kind"], tuple(value["ids"]))
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _label_mentioned(requirement: str, label: str) -> bool:
    requirement_set = requirement_tokens(requirement)
    label_set = requirement_tokens(label)
    if not label_set:
        return False
    return len(requirement_set & label_set) / len(label_set) >= 0.75


def _build_must_show_coverage(
    lines: list[str],
    elements: list[dict[str, Any]],
    connectors: list[dict[str, Any]],
    *,
    hierarchy_refs: list[dict[str, Any]],
    evidence_support_refs: list[dict[str, Any]],
    comparison_refs: list[dict[str, Any]],
    independence_refs: list[dict[str, Any]],
    grouping_refs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    spec_elements = [
        item
        for item in elements
        if item.get("representation_origin") == "SPEC_LABEL" and item.get("label")
    ]
    result: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        lowered = line.casefold()
        references = [
            _coverage_ref("element", element["id"])
            for element in spec_elements
            if _label_mentioned(line, element["label"])
        ]
        missing_dimensions: list[str] = []

        if "hierarch" in lowered or "containment" in lowered:
            references.extend(hierarchy_refs)
            if not hierarchy_refs:
                missing_dimensions.append("hierarchy / containment")
        if any(token in lowered for token in ("evidence-trace", "traceable", "provenance")):
            references.extend(evidence_support_refs)
            if not evidence_support_refs:
                missing_dimensions.append("evidence traceability / provenance")
        if (
            ("candidate" in lowered and "reference" in lowered)
            and any(token in lowered for token in ("alignment", "comparison"))
        ):
            references.extend(comparison_refs)
            if not comparison_refs:
                missing_dimensions.append("Candidate–Reference comparison")
        if "independent" in lowered and "reference" in lowered:
            references.extend(independence_refs)
            if not independence_refs:
                missing_dimensions.append("Reference independence")
        if any(token in lowered for token in ("diagnostic", "fidelity")):
            references.extend(grouping_refs)
        if "system output" in lowered or "generated output" in lowered:
            output_refs = [
                _coverage_ref("connector", connector["id"])
                for connector in connectors
                if connector.get("representation_origin") == "SPEC_RELATIONSHIP"
                and "output" in connector.get("relation", "").casefold()
            ]
            references.extend(output_refs)
            if not output_refs:
                missing_dimensions.append("system-output relation")

        references = _dedupe_coverage_refs(references)
        mapped = bool(references) and not missing_dimensions
        item: dict[str, Any] = {
            "id": f"must-show-{index:03d}",
            "source_ref": f"3.1 Must Show[{index}]",
            "source_text": line,
            "status": "MAPPED" if mapped else "UNRESOLVED",
            "representations": references,
        }
        if not mapped:
            if missing_dimensions:
                item["reason"] = "Missing explicit representation for: " + ", ".join(
                    missing_dimensions
                ) + "."
            else:
                item["reason"] = (
                    "No required label or conservative canonical representation maps this content."
                )
        result.append(item)
    return result


def _assign_layout(
    labels: list[str],
    relations: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, float]], list[str], list[str]]:
    width = 1280.0
    height = 710.0
    node_width = 210.0
    node_height = 88.0
    chain = _longest_directed_chain(labels, relations)
    if not chain:
        chain = labels[: min(3, len(labels))]

    comparison_peers: list[str] = []
    for relation in relations:
        if relation["directed"]:
            continue
        source = relation["source_label"]
        target = relation["target_label"]
        if source in chain and target not in chain:
            comparison_peers.append(target)
        elif target in chain and source not in chain:
            comparison_peers.append(source)

    comparison_peers = list(dict.fromkeys(comparison_peers))
    remaining = [
        label for label in labels if label not in chain and label not in comparison_peers
    ]
    reserve_right = 420.0 if len(remaining) >= 2 else 80.0
    chain_region_width = width - reserve_right - 80.0
    geometry: dict[str, dict[str, float]] = {}

    if len(chain) == 1:
        chain_x = [80.0]
    else:
        available = max(node_width, chain_region_width - node_width)
        chain_x = [80.0 + index * available / (len(chain) - 1) for index in range(len(chain))]
    for index, label in enumerate(chain):
        geometry[label] = {
            "x": chain_x[index],
            "y": 205.0,
            "width": node_width,
            "height": node_height,
        }

    for index, label in enumerate(comparison_peers):
        anchor_x = chain_x[-1] if chain_x else 80.0
        geometry[label] = {
            "x": anchor_x,
            "y": 365.0 + index * 112.0,
            "width": node_width,
            "height": node_height,
        }

    right_x = width - reserve_right + 25.0
    diag_width = 165.0
    for index, label in enumerate(remaining):
        column = index % 2
        row = index // 2
        geometry[label] = {
            "x": right_x + column * (diag_width + 22.0),
            "y": 170.0 + row * 125.0,
            "width": diag_width,
            "height": 82.0,
        }
    return geometry, chain, remaining


def build_render_plan(
    spec_path: Path,
    plan_path: Path,
    *,
    backend: str,
    strict: bool = False,
) -> dict[str, Any]:
    if backend not in {"drawio", "svg"}:
        raise DiagramPlanError(f"Unsupported structured-diagram backend: {backend}")
    spec_path = spec_path.expanduser().resolve()
    plan_path = plan_path.expanduser().resolve()
    report = figure_spec_validator.validate_file(spec_path, project_root=spec_path.parent)
    blocking = list(report.errors) + (list(report.warnings) if strict else [])
    if blocking:
        details = "; ".join(f"{issue.code}: {issue.message}" for issue in blocking)
        raise DiagramPlanError(f"FigureSpec cannot be planned: {details}")

    text = spec_path.read_text(encoding="utf-8")
    metadata, metadata_error = figure_spec_validator.extract_frontmatter(text)
    if metadata is None:
        raise DiagramPlanError(metadata_error or "FigureSpec frontmatter is invalid.")
    headings = figure_spec_validator.collect_headings(text)

    requirements = extract_spec_requirements(spec_path)
    must_show_lines = requirements["must_show"]
    relationship_lines = requirements["relationships"]

    labels = _bullet_items(
        figure_spec_validator.section_body(text, headings, "6.2 Required Figure Labels")
    )
    label_source_ref = "6.2 Required Figure Labels"
    if not labels:
        labels = [
            item.rstrip(".")
            for item in _bullet_items(
                figure_spec_validator.section_body(text, headings, "3.1 Must Show")
            )
        ]
        label_source_ref = "3.1 Must Show (verbatim fallback)"
    if not labels:
        raise DiagramPlanError(
            "The FigureSpec contains neither Required Figure Labels nor Must Show "
            "content, so a scientifically grounded drawing cannot be authored."
        )
    labels = list(dict.fromkeys(labels))
    relationship_requirements = _analyze_relationships(relationship_lines, labels)
    layout_relations = [
        item
        for item in relationship_requirements
        if item["parse_status"] == "MAPPED"
        and item["relation_type"] in {"flow", "comparison"}
    ]
    geometry, chain, remaining = _assign_layout(labels, layout_relations)

    used_ids: set[str] = set()
    label_to_id: dict[str, str] = {}
    elements: list[dict[str, Any]] = []

    diagnostic_container_id: str | None = None
    if len(remaining) >= 2 and all(_semantic_role(label) == "diagnostic" for label in remaining):
        diagnostic_container_id = _unique_id("group-fidelity-diagnostics", used_ids)
        elements.append(
            {
                "id": diagnostic_container_id,
                "kind": "container",
                "label": "Fidelity Diagnostics",
                "semantic_role": "evaluation_group",
                "parent_id": None,
                "representation_origin": "DERIVED_HELPER",
                "geometry": {"x": 855, "y": 90, "width": 395, "height": 510},
                "style_tokens": _style_for_role("evaluation_group", container=True),
                "source_ref": "4.1 Relationships / 5.2 Composition",
            }
        )

    for label in labels:
        role = _semantic_role(label)
        element_id = _unique_id(_slug(label), used_ids)
        label_to_id[label] = element_id
        parent_id = (
            diagnostic_container_id
            if diagnostic_container_id is not None and label in remaining
            else None
        )
        element_geometry = dict(geometry[label])
        if diagnostic_container_id is not None and parent_id == diagnostic_container_id:
            container_geometry = elements[0]["geometry"]
            element_geometry["x"] -= container_geometry["x"]
            element_geometry["y"] -= container_geometry["y"]
        elements.append(
            {
                "id": element_id,
                "kind": "diagnostic" if role == "diagnostic" else "node",
                "label": label,
                "semantic_role": role,
                "parent_id": parent_id,
                "representation_origin": "SPEC_LABEL",
                "geometry": element_geometry,
                "style_tokens": _style_for_role(role),
                "source_ref": label_source_ref,
            }
        )

    element_by_label = {
        element["label"]: element
        for element in elements
        if element.get("representation_origin") == "SPEC_LABEL"
    }
    diagnostic_group_refs = [
        _coverage_ref("parent_child", diagnostic_container_id, element["id"])
        for element in elements
        if diagnostic_container_id is not None
        and element.get("parent_id") == diagnostic_container_id
    ]
    relationship_representations: dict[str, list[dict[str, Any]]] = {
        item["id"]: [] for item in relationship_requirements
    }
    hierarchy_refs: list[dict[str, Any]] = []
    hierarchy_child_counts: dict[str, int] = defaultdict(int)

    for requirement in relationship_requirements:
        if (
            requirement["relation_type"] != "containment"
            or requirement["parse_status"] != "MAPPED"
        ):
            continue
        parent = element_by_label.get(requirement["source_label"])
        child = element_by_label.get(requirement["target_label"])
        if parent is None or child is None:
            requirement["parse_status"] = "UNRESOLVED"
            requirement["reason"] = "Containment endpoints do not resolve to plan elements."
            continue
        existing_parent = child.get("parent_id")
        if existing_parent not in {None, parent["id"]}:
            requirement["parse_status"] = "UNRESOLVED"
            requirement["reason"] = (
                f"Child {child['id']!r} already belongs to container {existing_parent!r}."
            )
            continue
        parent["kind"] = "container"
        parent["geometry"]["width"] = max(260.0, parent["geometry"]["width"])
        child_index = hierarchy_child_counts[parent["id"]]
        hierarchy_child_counts[parent["id"]] += 1
        parent["geometry"]["height"] = max(
            180.0,
            70.0 + hierarchy_child_counts[parent["id"]] * 95.0,
        )
        child["parent_id"] = parent["id"]
        child["geometry"] = {
            "x": 25.0,
            "y": 55.0 + child_index * 95.0,
            "width": parent["geometry"]["width"] - 50.0,
            "height": 72.0,
        }
        reference = _coverage_ref("parent_child", parent["id"], child["id"])
        relationship_representations[requirement["id"]].append(reference)
        hierarchy_refs.append(reference)

    # A hierarchy requirement without explicit named containment still needs a
    # visible, editable EPG-internal cue.  It is added only when one unique
    # Candidate element exists; otherwise the requirement remains unresolved.
    hierarchy_requirement = next(
        (
            (index, line)
            for index, line in enumerate(must_show_lines, start=1)
            if "hierarch" in line.casefold()
        ),
        None,
    )
    synthetic_episode_id: str | None = None
    if hierarchy_requirement is not None and not hierarchy_refs:
        candidate_label = _unique_role_label(labels, "candidate")
        candidate_element = element_by_label.get(candidate_label or "")
        if candidate_element is not None:
            candidate_element["kind"] = "container"
            candidate_element["geometry"]["width"] = max(
                240.0, candidate_element["geometry"]["width"]
            )
            candidate_element["geometry"]["height"] = max(
                180.0, candidate_element["geometry"]["height"]
            )
            source_ref = f"3.1 Must Show[{hierarchy_requirement[0]}]"
            stage_id = _unique_id("cue-stage", used_ids)
            episode_id = _unique_id("cue-episode", used_ids)
            synthetic_episode_id = episode_id
            stage = {
                "id": stage_id,
                "kind": "container",
                "label": "Stage",
                "semantic_role": "hierarchy_cue",
                "parent_id": candidate_element["id"],
                "representation_origin": "SPEC_CONTENT",
                "geometry": {
                    "x": 15.0,
                    "y": 48.0,
                    "width": candidate_element["geometry"]["width"] - 30.0,
                    "height": 115.0,
                },
                "style_tokens": _style_for_role("content", container=True),
                "source_ref": source_ref,
            }
            episode = {
                "id": episode_id,
                "kind": "node",
                "label": "Episode",
                "semantic_role": "hierarchy_cue",
                "parent_id": stage_id,
                "representation_origin": "SPEC_CONTENT",
                "geometry": {
                    "x": 20.0,
                    "y": 43.0,
                    "width": stage["geometry"]["width"] - 40.0,
                    "height": 52.0,
                },
                "style_tokens": _style_for_role("content"),
                "source_ref": source_ref,
            }
            elements.extend([stage, episode])
            hierarchy_refs.extend(
                [
                    _coverage_ref(
                        "parent_child", candidate_element["id"], stage_id
                    ),
                    _coverage_ref("parent_child", stage_id, episode_id),
                ]
            )
            reference_label = _unique_role_label(labels, "reference")
            reference_element = element_by_label.get(reference_label or "")
            if reference_element is not None and reference_element.get("parent_id") is None:
                reference_element["geometry"]["y"] = max(
                    410.0, reference_element["geometry"]["y"]
                )

    connectors: list[dict[str, Any]] = []
    evidence_support_refs: list[dict[str, Any]] = []
    comparison_refs: list[dict[str, Any]] = []
    for relation in relationship_requirements:
        if relation["parse_status"] != "MAPPED" or relation["relation_type"] == "containment":
            continue
        if relation["relation_type"] in {"independence", "evaluation_output"}:
            continue
        connector_id = _unique_id(
            _slug(
                f"{relation['source_label']}-{relation['target_label']}",
                prefix="edge",
            ),
            used_ids,
        )
        target_id = label_to_id[relation["target_label"]]
        if relation["relation_type"] == "evidence_support" and synthetic_episode_id:
            target_id = synthetic_episode_id
        is_evidence_support = relation["relation_type"] == "evidence_support"
        connectors.append(
            {
                "id": connector_id,
                "source": label_to_id[relation["source_label"]],
                "target": target_id,
                "relation": relation["relation"],
                "directed": relation["directed"],
                "label": "provenance" if is_evidence_support else "",
                "representation_origin": "SPEC_RELATIONSHIP",
                "source_ref": relation["source_ref"],
                "style_tokens": {
                    "stroke": (
                        DEFAULT_PALETTE["input_stroke"]
                        if is_evidence_support
                        else DEFAULT_PALETTE["line"]
                    ),
                    "font_color": DEFAULT_PALETTE["muted"],
                    "font_size_px": 12 if is_evidence_support else 13,
                    "dashed": is_evidence_support or not relation["directed"],
                    "stroke_width_px": 1 if is_evidence_support else 2,
                },
            }
        )
        reference = _coverage_ref("connector", connector_id)
        relationship_representations[relation["id"]].append(reference)
        if is_evidence_support:
            evidence_support_refs.append(reference)
        if relation["relation_type"] == "comparison":
            comparison_refs.append(reference)

    # When the specification explicitly presents several Fidelity labels, one
    # non-causal evaluation junction makes their shared origin visible without
    # repeating the Candidate or Reference graph.
    candidate = next((label for label in labels if _semantic_role(label) == "candidate"), None)
    reference = next((label for label in labels if _semantic_role(label) == "reference"), None)
    if diagnostic_container_id and candidate and reference:
        hub_id = _unique_id("el-alignment-comparison", used_ids)
        elements.append(
            {
                "id": hub_id,
                "kind": "node",
                "label": "Alignment / Comparison",
                "semantic_role": "evaluation",
                "parent_id": None,
                "representation_origin": "DERIVED_HELPER",
                "geometry": {"x": 700, "y": 540, "width": 145, "height": 74},
                "style_tokens": _style_for_role("content"),
                "source_ref": "4.1 Relationships",
            }
        )
        for label in (candidate, reference):
            connectors.append(
                {
                    "id": _unique_id(_slug(f"{label}-alignment", prefix="edge"), used_ids),
                    "source": label_to_id[label],
                    "target": hub_id,
                    "relation": "alignment and comparison",
                    "directed": False,
                    "label": "",
                    "representation_origin": "DERIVED_HELPER",
                    "source_ref": "4.1 Relationships (derived comparison junction)",
                    "style_tokens": {
                        "stroke": DEFAULT_PALETTE["line"],
                        "font_color": DEFAULT_PALETTE["muted"],
                        "font_size_px": 13,
                        "dashed": True,
                    },
                }
            )
        evaluation_connector_id = _unique_id("edge-comparison-diagnostics", used_ids)
        evaluation_requirement = next(
            (
                item
                for item in relationship_requirements
                if item["relation_type"] == "evaluation_output"
                and item["parse_status"] == "DEFERRED"
            ),
            None,
        )
        connectors.append(
            {
                "id": evaluation_connector_id,
                "source": hub_id,
                "target": diagnostic_container_id,
                "relation": "evaluation output",
                "directed": True,
                "label": "",
                "representation_origin": (
                    "SPEC_RELATIONSHIP"
                    if evaluation_requirement is not None
                    else "DERIVED_HELPER"
                ),
                "source_ref": (
                    evaluation_requirement["source_ref"]
                    if evaluation_requirement is not None
                    else "4.1 Relationships (derived evaluation junction)"
                ),
                "style_tokens": {
                    "stroke": DEFAULT_PALETTE["line"],
                    "font_color": DEFAULT_PALETTE["muted"],
                    "font_size_px": 13,
                    "dashed": False,
                },
            }
        )
        if evaluation_requirement is not None:
            evaluation_requirement["parse_status"] = "MAPPED"
            evaluation_requirement["reason"] = ""
            relationship_representations[evaluation_requirement["id"]].append(
                _coverage_ref("connector", evaluation_connector_id)
            )

    assertions: list[dict[str, Any]] = []
    for element in elements:
        if element["label"] and element.get("representation_origin") == "SPEC_LABEL":
            assertions.append(
                {
                    "id": _unique_id(_slug(element["label"], prefix="assert-label"), used_ids),
                    "kind": "required_label",
                    "severity": "BLOCKING",
                    "params": {"element_id": element["id"], "label": element["label"]},
                    "why": "The label is explicitly required or directly grounded in the FigureSpec.",
                }
            )
    for connector in connectors:
        if connector.get("representation_origin") != "SPEC_RELATIONSHIP":
            continue
        assertions.append(
            {
                "id": _unique_id(_slug(connector["id"], prefix="assert-relation"), used_ids),
                "kind": "required_relation",
                "severity": "BLOCKING",
                "params": {
                    "source": connector["source"],
                    "target": connector["target"],
                    "directed": connector["directed"],
                    "relation": connector["relation"],
                },
                "why": "The connector implements an explicit scientific or evaluation relation.",
            }
        )

    avoid_body = figure_spec_validator.section_body(
        text, headings, "6.3 Must Not Imply / Avoid"
    )
    avoid_text = "\n".join(_bullet_items(avoid_body)).casefold()
    system = next((label for label in labels if _semantic_role(label) == "system"), None)
    independence_requirements = [
        item
        for item in relationship_requirements
        if item["relation_type"] == "independence"
    ]
    independence_refs: list[dict[str, Any]] = []
    if reference and system and (
        independence_requirements
        or ("reference" in avoid_text and "available" in avoid_text)
    ):
        independence_assertion_id = _unique_id("assert-no-reference-leakage", used_ids)
        assertions.append(
            {
                "id": independence_assertion_id,
                "kind": "forbidden_relation",
                "severity": "BLOCKING",
                "params": {
                    "source": label_to_id[reference],
                    "target": label_to_id[system],
                    "directed": True,
                },
                "why": "The Reference must not appear available to the reconstruction system.",
            }
        )
        independence_refs = [
            _coverage_ref("element", label_to_id[reference]),
            _coverage_ref("assertion", independence_assertion_id),
        ]
        for requirement in independence_requirements:
            requirement["parse_status"] = "MAPPED"
            requirement["reason"] = ""
            relationship_representations[requirement["id"]].extend(
                independence_refs
            )
    for element in elements:
        if element["semantic_role"] in {"evidence", "candidate", "reference"}:
            assertions.append(
                {
                    "id": _unique_id(
                        _slug(element["id"], prefix="assert-color"), used_ids
                    ),
                    "kind": "role_color",
                    "severity": "MAJOR",
                    "params": {
                        "element_id": element["id"],
                        "expected_fill": element["style_tokens"]["fill"],
                        "expected_stroke": element["style_tokens"]["stroke"],
                    },
                    "why": "This color distinction carries an explicit semantic role.",
                }
            )
    assertions.extend(
        [
            {
                "id": _unique_id("assert-no-raster", used_ids),
                "kind": "no_embedded_raster",
                "severity": "BLOCKING",
                "params": {},
                "why": "The Draw.io source must remain natively editable.",
            },
            {
                "id": _unique_id("assert-within-canvas", used_ids),
                "kind": "within_canvas",
                "severity": "MAJOR",
                "params": {},
                "why": "Required content must not be clipped.",
            },
            {
                "id": _unique_id("assert-minimum-text-size", used_ids),
                "kind": "minimum_text_size",
                "severity": "MAJOR",
                "params": {},
                "why": "Labels must remain readable at intended final size.",
            },
        ]
    )

    must_show_coverage = _build_must_show_coverage(
        must_show_lines,
        elements,
        connectors,
        hierarchy_refs=hierarchy_refs,
        evidence_support_refs=evidence_support_refs,
        comparison_refs=comparison_refs,
        independence_refs=independence_refs,
        grouping_refs=diagnostic_group_refs,
    )
    relationship_coverage: list[dict[str, Any]] = []
    for requirement in relationship_requirements:
        representations = _dedupe_coverage_refs(
            relationship_representations[requirement["id"]]
        )
        mapped = requirement["parse_status"] == "MAPPED" and bool(representations)
        item: dict[str, Any] = {
            "id": requirement["id"],
            "source_ref": requirement["source_ref"],
            "source_text": requirement["source_text"],
            "relation_type": requirement["relation_type"],
            "status": "MAPPED" if mapped else "UNRESOLVED",
            "representations": representations,
        }
        if not mapped:
            item["reason"] = requirement["reason"] or (
                "The relation has no explicit RenderPlan representation."
            )
        relationship_coverage.append(item)
    coverage_counts = coverage_summary(must_show_coverage, relationship_coverage)
    spec_coverage = {
        "status": (
            "COMPLETE" if coverage_counts["unresolved_total"] == 0 else "BLOCKED"
        ),
        "must_show": must_show_coverage,
        "relationships": relationship_coverage,
        "summary": coverage_counts,
    }

    render_body = figure_spec_validator.section_body(
        text, headings, "7.3 Rendering Requirements"
    )
    target_size = figure_spec_validator.extract_bold_field(
        render_body, "Target Size / Aspect Ratio"
    )
    preferred_backend = figure_spec_validator.extract_bold_field(
        render_body, "Preferred Backend"
    )
    required_outputs = figure_spec_validator.extract_bold_field(
        render_body, "Required Outputs"
    )
    ratio = _parse_aspect_ratio(target_size)
    final_width = 180.0
    final_height = round(final_width / ratio, 3)
    stem = spec_path.stem

    try:
        relative_spec = os.path.relpath(spec_path, plan_path.parent)
    except ValueError:
        relative_spec = str(spec_path)
    plan = {
        "schema_version": "1.1",
        "plan_id": f"{metadata['figure_id']}-{backend}-v1",
        "backend": backend,
        "figure_spec": {
            "path": relative_spec,
            "sha256": sha256_file(spec_path),
            "spec_version": metadata["spec_version"],
            "figure_id": metadata["figure_id"],
        },
        "spec_coverage": spec_coverage,
        "canvas": {
            "width": 1280,
            "height": 710,
            "unit": "px",
            "margin": 30,
            "background": DEFAULT_PALETTE["paper"],
        },
        "final_size": {
            "width": final_width,
            "height": final_height,
            "unit": "mm",
            "minimum_text_size_pt": 6.5,
        },
        "theme": {
            "font_family": "Arial",
            "font_size_px": 17,
            "title_font_size_px": 21,
            "line_width_px": 2,
            "palette": DEFAULT_PALETTE,
        },
        "elements": elements,
        "connectors": connectors,
        "semantic_assertions": assertions,
        "outputs": {
            "source": f"{stem}.{'drawio' if backend == 'drawio' else 'svg'}",
            "formats": _parse_formats(required_outputs),
            "manifest": f"{stem}.manifest.json",
            "qa_report": f"{stem}.qa.json",
        },
        "metadata": {
            "generated_by": "scientific-figure-skills",
            "source_status": metadata["status"],
            "working_title": metadata["working_title"],
            "preferred_backend_in_spec": preferred_backend,
            "selected_backend_is_explicit": True,
            "layout_strategy": "relationship-aware deterministic layout",
            "coverage_gate": spec_coverage["status"],
        },
    }
    issues = validate_render_plan_contract(plan)
    if issues:
        details = "; ".join(f"{issue.code}: {issue.message}" for issue in issues)
        raise DiagramPlanError(f"Generated RenderPlan is invalid: {details}")
    return plan


def create_render_plan_file(
    spec_path: Path,
    plan_path: Path,
    *,
    backend: str,
    strict: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    plan = build_render_plan(
        spec_path,
        plan_path,
        backend=backend,
        strict=strict,
    )
    write_json_atomic(plan_path, plan, overwrite=overwrite)
    return plan
