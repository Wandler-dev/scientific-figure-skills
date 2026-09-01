#!/usr/bin/env python3
"""Deterministic structural, editability, and geometry lint for native SVG."""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from figure_runtime import RuntimeIssue, read_json, validate_render_plan_contract


FORBIDDEN_ELEMENTS = {
    "image",
    "foreignObject",
    "script",
    "iframe",
    "video",
    "audio",
    "canvas",
}
URL_REFERENCE_RE = re.compile(
    r"url\(\s*(?P<quote>['\"]?)(?P<target>.*?)\1\s*\)",
    re.IGNORECASE,
)
TRANSLATE_RE = re.compile(
    r"^\s*translate\(\s*(?P<x>[-+0-9.eE]+)(?:[\s,]+(?P<y>[-+0-9.eE]+))?\s*\)\s*$"
)
CONNECTOR_PRIMITIVES = {"line", "polyline", "path"}
MARKER_PROPERTIES = {"marker", "marker-start", "marker-mid", "marker-end"}


@dataclass
class SvgLintReport:
    path: Path
    issues: list[RuntimeIssue]
    objects: int = 0
    connectors: int = 0
    live_text: int = 0

    @property
    def errors(self) -> list[RuntimeIssue]:
        return [item for item in self.issues if item.severity == "ERROR"]

    @property
    def warnings(self) -> list[RuntimeIssue]:
        return [item for item in self.issues if item.severity == "WARNING"]

    def as_dict(self, *, strict: bool = False) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "passed": lint_passed(self, strict=strict),
            "strict": strict,
            "summary": {
                "objects": self.objects,
                "connectors": self.connectors,
                "live_text": self.live_text,
                "errors": len(self.errors),
                "warnings": len(self.warnings),
            },
            "issues": [item.as_dict() for item in self.issues],
        }


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _has_arrow_marker(node: ET.Element) -> bool:
    for property_name in MARKER_PROPERTIES:
        value = node.get(property_name)
        if value and value.strip().casefold() != "none":
            return True
    for declaration in (node.get("style") or "").split(";"):
        if ":" not in declaration:
            continue
        property_name, value = declaration.split(":", 1)
        if (
            property_name.strip().casefold() in MARKER_PROPERTIES
            and value.strip()
            and value.strip().casefold() != "none"
        ):
            return True
    return False


def _finite_number(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _view_box(root: ET.Element) -> tuple[float, float, float, float] | None:
    raw = root.get("viewBox")
    if raw is None:
        return None
    try:
        values = [float(item) for item in raw.replace(",", " ").split()]
    except ValueError:
        return None
    if len(values) != 4 or not all(math.isfinite(item) for item in values):
        return None
    if values[2] <= 0 or values[3] <= 0:
        return None
    return values[0], values[1], values[2], values[3]


def _translation(node: ET.Element) -> tuple[float, float] | None:
    raw = node.get("transform")
    if not raw:
        return 0.0, 0.0
    match = TRANSLATE_RE.match(raw)
    if match is None:
        return None
    try:
        return float(match.group("x")), float(match.group("y") or 0)
    except ValueError:
        return None


def _parse_points(value: str | None) -> list[tuple[float, float]] | None:
    if not value:
        return None
    tokens = value.replace(",", " ").split()
    if len(tokens) < 4 or len(tokens) % 2:
        return None
    try:
        values = [float(item) for item in tokens]
    except ValueError:
        return None
    if not all(math.isfinite(item) for item in values):
        return None
    return list(zip(values[0::2], values[1::2]))


def _segment_intersects_box(
    start: tuple[float, float],
    end: tuple[float, float],
    box: tuple[float, float, float, float],
    *,
    padding: float = 2.0,
) -> bool:
    x, y, width, height = box
    left, right = x - padding, x + width + padding
    top, bottom = y - padding, y + height + padding
    x1, y1 = start
    x2, y2 = end
    if abs(y1 - y2) < 1e-6:
        return top < y1 < bottom and max(min(x1, x2), left) < min(max(x1, x2), right)
    if abs(x1 - x2) < 1e-6:
        return left < x1 < right and max(min(y1, y2), top) < min(max(y1, y2), bottom)
    return False


def _load_plan(plan: dict[str, Any] | Path | None) -> dict[str, Any] | None:
    if plan is None:
        return None
    if isinstance(plan, Path):
        loaded = read_json(plan.expanduser().resolve())
    else:
        loaded = plan
    issues = validate_render_plan_contract(loaded)
    if issues:
        details = "; ".join(f"{item.code}: {item.message}" for item in issues)
        raise ValueError(f"Invalid RenderPlan supplied to SVG lint: {details}")
    return loaded


def lint_svg(
    path: Path,
    *,
    plan: dict[str, Any] | Path | None = None,
) -> SvgLintReport:
    path = path.expanduser().resolve()
    report = SvgLintReport(path=path, issues=[])
    try:
        payload = path.read_bytes()
    except FileNotFoundError:
        report.issues.append(RuntimeIssue("ERROR", "svg.xml.file_missing", "SVG file does not exist."))
        return report
    except OSError as exc:
        report.issues.append(RuntimeIssue("ERROR", "svg.xml.file_read", f"Could not read SVG file: {exc}"))
        return report

    upper_prefix = payload[:8192].upper()
    if b"<!DOCTYPE" in upper_prefix or b"<!ENTITY" in upper_prefix:
        report.issues.append(
            RuntimeIssue(
                "ERROR",
                "svg.xml.unsafe_declaration",
                "SVG must not contain DOCTYPE or entity declarations.",
            )
        )
        return report
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        report.issues.append(RuntimeIssue("ERROR", "svg.xml.parse", f"Invalid SVG XML: {exc}"))
        return report
    if _local_name(root.tag) != "svg":
        report.issues.append(RuntimeIssue("ERROR", "svg.structure.root", "Root element must be <svg>."))
        return report

    view_box = _view_box(root)
    if view_box is None:
        report.issues.append(
            RuntimeIssue(
                "ERROR",
                "svg.geometry.viewbox_invalid",
                "SVG requires a finite positive four-number viewBox.",
            )
        )

    nodes = list(root.iter())
    id_nodes: dict[str, ET.Element] = {}
    duplicate_ids: set[str] = set()
    for node in nodes:
        node_id = node.get("id")
        if node_id:
            if node_id in id_nodes:
                duplicate_ids.add(node_id)
            else:
                id_nodes[node_id] = node
    for duplicate in sorted(duplicate_ids):
        report.issues.append(
            RuntimeIssue("ERROR", "svg.structure.duplicate_id", f"SVG ID is duplicated: {duplicate}", duplicate)
        )

    for node in nodes:
        name = _local_name(node.tag)
        node_id = node.get("id") or name
        if name in FORBIDDEN_ELEMENTS:
            code = "svg.asset.embedded_raster" if name == "image" else "svg.editability.forbidden_element"
            report.issues.append(
                RuntimeIssue("ERROR", code, f"Forbidden SVG element <{name}> is present.", node_id)
            )
        if (
            name in CONNECTOR_PRIMITIVES
            and _has_arrow_marker(node)
            and node.get("data-object-kind") != "connector"
        ):
            report.issues.append(
                RuntimeIssue(
                    "ERROR",
                    "svg.connector.unplanned",
                    "Arrow-bearing SVG geometry is not bound to a planned connector.",
                    node_id,
                )
            )
        for attribute, value in node.attrib.items():
            lowered = value.strip().casefold()
            attribute_name = _local_name(attribute).casefold()
            if attribute_name in {"href", "src"} and lowered:
                if lowered.startswith("#"):
                    reference = value.strip()[1:]
                    if reference not in id_nodes:
                        report.issues.append(
                            RuntimeIssue(
                                "ERROR",
                                "svg.reference.broken_url",
                                f"{attribute} references missing SVG ID {reference!r}.",
                                node_id,
                            )
                        )
                else:
                    code = (
                        "svg.asset.embedded_raster"
                        if lowered.startswith("data:image/")
                        else "svg.asset.external_uri"
                    )
                    report.issues.append(
                        RuntimeIssue(
                            "ERROR",
                            code,
                            f"Disallowed external SVG asset reference: {value[:120]}",
                            node_id,
                        )
                    )
            for match in URL_REFERENCE_RE.finditer(value):
                target = match.group("target").strip()
                if target.startswith("#"):
                    reference = target[1:]
                    if reference in id_nodes:
                        continue
                    family = (
                        "marker"
                        if attribute_name.startswith("marker")
                        else "clip"
                        if attribute_name == "clip-path"
                        else "mask"
                        if attribute_name == "mask"
                        else "url"
                    )
                    report.issues.append(
                        RuntimeIssue(
                            "ERROR",
                            f"svg.reference.broken_{family}",
                            f"{attribute} references missing SVG ID {reference!r}.",
                            node_id,
                        )
                    )
                elif target:
                    code = (
                        "svg.asset.embedded_raster"
                        if target.casefold().startswith("data:image/")
                        else "svg.asset.external_uri"
                    )
                    report.issues.append(
                        RuntimeIssue(
                            "ERROR",
                            code,
                            f"Disallowed external SVG url() reference: {target[:120]}",
                            node_id,
                        )
                    )
        if name == "style":
            stylesheet = "".join(node.itertext())
            for match in URL_REFERENCE_RE.finditer(stylesheet):
                target = match.group("target").strip()
                if not target or target.startswith("#"):
                    continue
                code = (
                    "svg.asset.embedded_raster"
                    if target.casefold().startswith("data:image/")
                    else "svg.asset.external_uri"
                )
                report.issues.append(
                    RuntimeIssue(
                        "ERROR",
                        code,
                        f"Disallowed external stylesheet asset: {target[:120]}",
                        node_id,
                    )
                )

    report.live_text = sum(
        1
        for node in nodes
        if _local_name(node.tag) == "text" and "".join(node.itertext()).strip()
    )
    if report.live_text == 0:
        report.issues.append(
            RuntimeIssue("ERROR", "svg.editability.live_text_missing", "SVG contains no live searchable <text> labels.")
        )

    element_nodes: dict[str, ET.Element] = {}
    connector_nodes: dict[str, ET.Element] = {}
    parent_by_id: dict[str, str | None] = {}
    boxes: dict[str, tuple[float, float, float, float]] = {}

    def walk(
        node: ET.Element,
        offset_x: float,
        offset_y: float,
        parent_element_id: str | None,
    ) -> None:
        translation = _translation(node)
        node_id = node.get("id")
        if translation is None:
            report.issues.append(
                RuntimeIssue(
                    "ERROR",
                    "svg.geometry.transform_invalid",
                    "Only deterministic translate(x y) transforms are allowed for authored objects.",
                    node_id,
                )
            )
            translation = (0.0, 0.0)
        current_x = offset_x + translation[0]
        current_y = offset_y + translation[1]
        current_parent = parent_element_id
        if node.get("data-object-kind") == "element" and node_id:
            element_nodes[node_id] = node
            parent_by_id[node_id] = parent_element_id
            width = _finite_number(node.get("data-width"))
            height = _finite_number(node.get("data-height"))
            if width is None or height is None or width <= 0 or height <= 0:
                report.issues.append(
                    RuntimeIssue(
                        "ERROR",
                        "svg.geometry.invalid",
                        f"Element {node_id!r} has invalid or non-positive geometry.",
                        node_id,
                    )
                )
            else:
                boxes[node_id] = (current_x, current_y, width, height)
            current_parent = node_id
        elif node.get("data-object-kind") == "connector" and node_id:
            connector_nodes[node_id] = node
        for child in node:
            walk(child, current_x, current_y, current_parent)

    walk(root, 0.0, 0.0, None)
    report.objects = len(element_nodes)
    report.connectors = len(connector_nodes)

    if view_box is not None:
        origin_x, origin_y, width, height = view_box
        for element_id, (x, y, item_width, item_height) in boxes.items():
            if (
                x < origin_x
                or y < origin_y
                or x + item_width > origin_x + width
                or y + item_height > origin_y + height
            ):
                report.issues.append(
                    RuntimeIssue(
                        "ERROR",
                        "svg.geometry.outside_viewbox",
                        f"Element {element_id!r} extends outside the SVG viewBox.",
                        element_id,
                    )
                )

    for node in nodes:
        if _local_name(node.tag) != "text" or not "".join(node.itertext()).strip():
            continue
        font_size = _finite_number(node.get("font-size"))
        if font_size is None or font_size <= 0:
            report.issues.append(
                RuntimeIssue(
                    "ERROR",
                    "svg.text.font_size_invalid",
                    "Live text requires a finite positive font-size.",
                    node.get("id"),
                )
            )

    loaded_plan = _load_plan(plan)
    if loaded_plan is not None:
        if loaded_plan.get("backend") != "svg":
            report.issues.append(
                RuntimeIssue("ERROR", "svg.structure.backend_mismatch", "SVG lint received a non-SVG RenderPlan.")
            )
        if root.get("data-plan-id") != loaded_plan.get("plan_id"):
            report.issues.append(
                RuntimeIssue("ERROR", "svg.structure.plan_id_mismatch", "SVG plan identity does not match the RenderPlan.")
            )
        expected_elements = {item["id"]: item for item in loaded_plan["elements"]}
        expected_connectors = {item["id"]: item for item in loaded_plan["connectors"]}
        for element_id, element in expected_elements.items():
            if element_id not in element_nodes:
                report.issues.append(
                    RuntimeIssue("ERROR", "svg.structure.plan_object_missing", f"RenderPlan element is missing: {element_id}", element_id)
                )
                continue
            actual_parent = parent_by_id.get(element_id)
            if actual_parent != element.get("parent_id"):
                report.issues.append(
                    RuntimeIssue(
                        "ERROR",
                        "svg.structure.parent_mismatch",
                        f"Element {element_id!r} is nested under {actual_parent!r}; expected {element.get('parent_id')!r}.",
                        element_id,
                    )
                )
            label_nodes = [
                child
                for child in element_nodes[element_id]
                if _local_name(child.tag) == "text"
                and child.get("data-text-role") == "element-label"
            ]
            actual_label = " ".join(
                " ".join(label_nodes[0].itertext()).split()
            ) if label_nodes else ""
            expected_label = " ".join(str(element.get("label", "")).split())
            if expected_label and actual_label != expected_label:
                report.issues.append(
                    RuntimeIssue(
                        "ERROR",
                        "svg.text.plan_label_missing",
                        f"Element {element_id!r} is missing or alters its planned live-text label.",
                        element_id,
                    )
                )
        for element_id in sorted(set(element_nodes) - set(expected_elements)):
            report.issues.append(
                RuntimeIssue(
                    "ERROR",
                    "svg.structure.unplanned_object",
                    f"SVG contains an element object absent from the RenderPlan: {element_id}",
                    element_id,
                )
            )
        for connector_id, connector in expected_connectors.items():
            if connector_id not in connector_nodes:
                report.issues.append(
                    RuntimeIssue("ERROR", "svg.connector.object_missing", f"RenderPlan connector is missing: {connector_id}", connector_id)
                )
                continue
            expected_label = " ".join(str(connector.get("label", "")).split())
            label_id = f"{connector_id}__label"
            label_node = id_nodes.get(label_id)
            actual_label = (
                " ".join(" ".join(label_node.itertext()).split())
                if label_node is not None
                else ""
            )
            if expected_label and actual_label != expected_label:
                report.issues.append(
                    RuntimeIssue(
                        "ERROR",
                        "svg.text.connector_label_missing",
                        f"Connector {connector_id!r} is missing or alters its planned live-text label.",
                        connector_id,
                    )
                )
        for connector_id in sorted(set(connector_nodes) - set(expected_connectors)):
            report.issues.append(
                RuntimeIssue(
                    "ERROR",
                    "svg.connector.unplanned",
                    f"SVG contains a connector absent from the RenderPlan: {connector_id}",
                    connector_id,
                )
            )

        final_size = loaded_plan["final_size"]
        canvas = loaded_plan["canvas"]
        final_width = float(final_size["width"])
        if final_size["unit"] == "mm":
            final_css_width = final_width / 25.4 * 96.0
        elif final_size["unit"] == "in":
            final_css_width = final_width * 96.0
        else:
            final_css_width = final_width
        scale = final_css_width / float(canvas["width"])
        minimum_pt = float(final_size["minimum_text_size_pt"])
        for node in nodes:
            if _local_name(node.tag) != "text" or node.get("data-text-role") not in {"element-label", "connector-label"}:
                continue
            source_px = _finite_number(node.get("font-size"))
            if source_px is None or source_px <= 0:
                continue
            final_pt = source_px * scale * 72.0 / 96.0
            if final_pt + 1e-6 < minimum_pt:
                report.issues.append(
                    RuntimeIssue(
                        "ERROR",
                        "svg.text.final_size_below_threshold",
                        f"Text {node.get('id')!r} renders at {final_pt:.2f} pt, below {minimum_pt:g} pt.",
                        node.get("id"),
                    )
                )

    def ancestors(element_id: str) -> set[str]:
        result: set[str] = set()
        current = parent_by_id.get(element_id)
        while current and current not in result:
            result.add(current)
            current = parent_by_id.get(current)
        return result

    for connector_id, connector in connector_nodes.items():
        source = connector.get("data-source")
        target = connector.get("data-target")
        if not source or not target or source not in element_nodes or target not in element_nodes:
            report.issues.append(
                RuntimeIssue(
                    "ERROR",
                    "svg.connector.endpoint_missing",
                    f"Connector {connector_id!r} has a missing source or target object.",
                    connector_id,
                )
            )
            continue
        directed = connector.get("data-directed") == "true"
        marker_end = connector.get("marker-end")
        if directed and not marker_end:
            report.issues.append(
                RuntimeIssue("ERROR", "svg.connector.marker_missing", f"Directed connector {connector_id!r} has no arrow marker.", connector_id)
            )
        points = _parse_points(connector.get("points"))
        if points is None:
            report.issues.append(
                RuntimeIssue("ERROR", "svg.connector.geometry_invalid", f"Connector {connector_id!r} has invalid polyline points.", connector_id)
            )
            continue
        excluded = {source, target, *ancestors(source), *ancestors(target)}
        collided = [
            element_id
            for element_id, box in boxes.items()
            if element_id not in excluded
            and any(_segment_intersects_box(start, end, box) for start, end in zip(points, points[1:]))
        ]
        if collided:
            report.issues.append(
                RuntimeIssue(
                    "WARNING",
                    "svg.connector.through_unrelated_node",
                    f"Connector {connector_id!r} visibly passes through unrelated object(s): {', '.join(sorted(collided))}.",
                    connector_id,
                )
            )
        if directed and view_box is not None:
            x, y = points[-1]
            vx, vy, vw, vh = view_box
            if x < vx + 4 or x > vx + vw - 4 or y < vy + 4 or y > vy + vh - 4:
                report.issues.append(
                    RuntimeIssue(
                        "WARNING",
                        "svg.connector.arrowhead_clipped",
                        f"Connector {connector_id!r} arrowhead is too close to the viewBox boundary.",
                        connector_id,
                    )
                )
    return report


def lint_passed(report: SvgLintReport, *, strict: bool = False) -> bool:
    return not report.errors and (not strict or not report.warnings)


def format_lint_report(report: SvgLintReport, *, strict: bool = False) -> str:
    lines = [f"[{'PASS' if lint_passed(report, strict=strict) else 'FAIL'}] {report.path}"]
    for issue in report.issues:
        location = f" ({issue.path})" if issue.path else ""
        lines.append(f"[{issue.severity}] {issue.code}{location}: {issue.message}")
    lines.extend(
        [
            "",
            "Summary",
            f"  Objects:    {report.objects}",
            f"  Connectors: {report.connectors}",
            f"  Live text:  {report.live_text}",
            f"  Errors:     {len(report.errors)}",
            f"  Warnings:   {len(report.warnings)}",
        ]
    )
    return "\n".join(lines)
