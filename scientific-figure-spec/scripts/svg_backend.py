#!/usr/bin/env python3
"""Native semantic SVG authoring for structured-diagram RenderPlan 1.1."""

from __future__ import annotations

import os
import tempfile
import textwrap
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from figure_coverage import coverage_is_complete
from figure_runtime import RuntimeContractError, read_json, validate_render_plan_contract


SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)


class SvgBackendError(RuntimeError):
    """Raised when a native SVG source cannot be produced safely."""


def _tag(name: str) -> str:
    return f"{{{SVG_NS}}}{name}"


def _number(value: Any) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.3f}".rstrip("0").rstrip(".")


def _absolute_geometries(plan: dict[str, Any]) -> dict[str, dict[str, float]]:
    elements = {item["id"]: item for item in plan["elements"]}
    result: dict[str, dict[str, float]] = {}

    def resolve(element_id: str, visiting: set[str]) -> dict[str, float]:
        if element_id in result:
            return result[element_id]
        if element_id in visiting:
            raise SvgBackendError(f"Element hierarchy contains a cycle at {element_id!r}.")
        visiting.add(element_id)
        element = elements[element_id]
        geometry = element["geometry"]
        x = float(geometry["x"])
        y = float(geometry["y"])
        parent_id = element.get("parent_id")
        if isinstance(parent_id, str):
            parent = resolve(parent_id, visiting)
            x += parent["x"]
            y += parent["y"]
        visiting.remove(element_id)
        resolved = {
            "x": x,
            "y": y,
            "width": float(geometry["width"]),
            "height": float(geometry["height"]),
        }
        result[element_id] = resolved
        return resolved

    for element_id in elements:
        resolve(element_id, set())
    return result


def _dock_points(
    source: dict[str, float], target: dict[str, float]
) -> tuple[tuple[float, float], tuple[float, float], str]:
    sx = source["x"] + source["width"] / 2
    sy = source["y"] + source["height"] / 2
    tx = target["x"] + target["width"] / 2
    ty = target["y"] + target["height"] / 2
    dx = tx - sx
    dy = ty - sy
    if abs(dx) >= abs(dy):
        overlap_top = max(source["y"], target["y"]) + 8
        overlap_bottom = min(
            source["y"] + source["height"],
            target["y"] + target["height"],
        ) - 8
        if overlap_top <= overlap_bottom:
            shared_y = min(max((sy + ty) / 2, overlap_top), overlap_bottom)
            sy = shared_y
            ty = shared_y
        start = (
            source["x"] + source["width"] if dx >= 0 else source["x"],
            sy,
        )
        end = (target["x"] if dx >= 0 else target["x"] + target["width"], ty)
        return start, end, "horizontal"
    overlap_left = max(source["x"], target["x"]) + 8
    overlap_right = min(
        source["x"] + source["width"],
        target["x"] + target["width"],
    ) - 8
    if overlap_left <= overlap_right:
        shared_x = min(max((sx + tx) / 2, overlap_left), overlap_right)
        sx = shared_x
        tx = shared_x
    start = (
        sx,
        source["y"] + source["height"] if dy >= 0 else source["y"],
    )
    end = (tx, target["y"] if dy >= 0 else target["y"] + target["height"])
    return start, end, "vertical"


def _segment_intersects_box(
    start: tuple[float, float],
    end: tuple[float, float],
    box: dict[str, float],
    *,
    padding: float = 3.0,
) -> bool:
    left = box["x"] - padding
    right = box["x"] + box["width"] + padding
    top = box["y"] - padding
    bottom = box["y"] + box["height"] + padding
    x1, y1 = start
    x2, y2 = end
    if abs(y1 - y2) < 1e-6:
        return top < y1 < bottom and max(min(x1, x2), left) < min(max(x1, x2), right)
    if abs(x1 - x2) < 1e-6:
        return left < x1 < right and max(min(y1, y2), top) < min(max(y1, y2), bottom)
    return False


def _route_hits(
    points: list[tuple[float, float]],
    boxes: Iterable[dict[str, float]],
) -> bool:
    return any(
        _segment_intersects_box(start, end, box)
        for start, end in zip(points, points[1:])
        for box in boxes
    )


def _route_length(points: list[tuple[float, float]]) -> float:
    return sum(
        abs(end[0] - start[0]) + abs(end[1] - start[1])
        for start, end in zip(points, points[1:])
    )


def _connector_label_position(
    points: list[tuple[float, float]],
) -> tuple[float, float]:
    start, end = max(
        zip(points, points[1:]),
        key=lambda segment: (
            abs(segment[1][0] - segment[0][0])
            + abs(segment[1][1] - segment[0][1])
        ),
    )
    x = (start[0] + end[0]) / 2
    y = (start[1] + end[1]) / 2
    if abs(end[0] - start[0]) >= abs(end[1] - start[1]):
        y -= 7
    else:
        x += 7
    return x, y


def _route_connector(
    source_id: str,
    target_id: str,
    geometries: dict[str, dict[str, float]],
    parent_by_id: dict[str, str | None],
    canvas: dict[str, Any],
) -> list[tuple[float, float]]:
    source = geometries[source_id]
    target = geometries[target_id]
    start, end, orientation = _dock_points(source, target)
    if orientation == "horizontal" and abs(start[1] - end[1]) < 1e-6:
        candidate_routes = [[start, end]]
    elif orientation == "vertical" and abs(start[0] - end[0]) < 1e-6:
        candidate_routes = [[start, end]]
    elif orientation == "horizontal":
        middle = (start[0] + end[0]) / 2
        candidate_routes = [
            [start, (end[0], start[1]), end],
            [start, (start[0], end[1]), end],
            [start, (middle, start[1]), (middle, end[1]), end],
        ]
    else:
        middle = (start[1] + end[1]) / 2
        candidate_routes = [
            [start, (start[0], end[1]), end],
            [start, (end[0], start[1]), end],
            [start, (start[0], middle), (end[0], middle), end],
        ]

    excluded = {source_id, target_id}
    for endpoint in (source_id, target_id):
        parent_id = parent_by_id.get(endpoint)
        while parent_id and parent_id not in excluded:
            excluded.add(parent_id)
            parent_id = parent_by_id.get(parent_id)
    unrelated = [
        box
        for element_id, box in geometries.items()
        if element_id not in excluded
    ]
    safe_initial = next(
        (
            candidate
            for candidate in candidate_routes
            if not _route_hits(candidate, unrelated)
        ),
        None,
    )
    if safe_initial is not None:
        return safe_initial

    margin = float(canvas.get("margin", 30))
    width = float(canvas["width"])
    height = float(canvas["height"])
    blockers = [
        box
        for box in unrelated
        if any(
            _segment_intersects_box(start, end, box)
            for candidate in candidate_routes
            for start, end in zip(candidate, candidate[1:])
        )
    ]
    local_padding = 18.0
    if orientation == "horizontal":
        top = max(
            margin,
            min(box["y"] for box in blockers) - local_padding,
        )
        bottom = min(
            height - margin,
            max(box["y"] + box["height"] for box in blockers) + local_padding,
        )
        candidates = [
            [start, (start[0], top), (end[0], top), end],
            [start, (start[0], bottom), (end[0], bottom), end],
        ]
    else:
        left = max(
            margin,
            min(box["x"] for box in blockers) - local_padding,
        )
        right = min(
            width - margin,
            max(box["x"] + box["width"] for box in blockers) + local_padding,
        )
        candidates = [
            [start, (left, start[1]), (left, end[1]), end],
            [start, (right, start[1]), (right, end[1]), end],
        ]
    candidates.sort(key=_route_length)
    safe = next(
        (candidate for candidate in candidates if not _route_hits(candidate, unrelated)),
        None,
    )
    if safe is not None:
        return safe

    # One deterministic global corridor is the bounded fallback when a local
    # route remains obstructed. This is intentionally not general graph routing.
    if orientation == "horizontal":
        global_top = max(margin, min(box["y"] for box in unrelated) - 24)
        global_bottom = min(
            height - margin,
            max(box["y"] + box["height"] for box in unrelated) + 24,
        )
        fallback = [
            [start, (start[0], global_top), (end[0], global_top), end],
            [start, (start[0], global_bottom), (end[0], global_bottom), end],
        ]
    else:
        global_left = max(margin, min(box["x"] for box in unrelated) - 24)
        global_right = min(
            width - margin,
            max(box["x"] + box["width"] for box in unrelated) + 24,
        )
        fallback = [
            [start, (global_left, start[1]), (global_left, end[1]), end],
            [start, (global_right, start[1]), (global_right, end[1]), end],
        ]
    fallback.sort(key=_route_length)
    return next(
        (candidate for candidate in fallback if not _route_hits(candidate, unrelated)),
        fallback[0],
    )


def _wrapped_lines(label: str, width: float, font_size: float) -> list[str]:
    if not label:
        return []
    max_chars = max(6, int(max(width - 18, font_size) / max(font_size * 0.56, 1)))
    lines: list[str] = []
    for explicit in label.splitlines() or [label]:
        lines.extend(
            textwrap.wrap(
                explicit,
                width=max_chars,
                break_long_words=False,
                break_on_hyphens=False,
            )
            or [""]
        )
    return lines


def _append_text(
    group: ET.Element,
    element: dict[str, Any],
    theme: dict[str, Any],
) -> None:
    label = element.get("label", "")
    if not label:
        return
    geometry = element["geometry"]
    style = element["style_tokens"]
    width = float(geometry["width"])
    height = float(geometry["height"])
    font_size = float(style.get("font_size_px", theme["font_size_px"]))
    lines = _wrapped_lines(label, width, font_size)
    line_height = font_size * 1.18
    is_container = element["kind"] == "container"
    start_y = font_size + 10 if is_container else (height - line_height * (len(lines) - 1)) / 2
    text = ET.SubElement(
        group,
        _tag("text"),
        {
            "id": f"{element['id']}__label",
            "x": _number(width / 2),
            "y": _number(start_y),
            "text-anchor": "middle",
            "dominant-baseline": "middle",
            "font-family": str(theme["font_family"]),
            "font-size": _number(font_size),
            "font-weight": "700" if style.get("bold") or is_container else "400",
            "fill": str(style.get("font_color", "#000000")),
            "data-text-role": "element-label",
        },
    )
    for index, line in enumerate(lines):
        tspan = ET.SubElement(
            text,
            _tag("tspan"),
            {
                "x": _number(width / 2),
                "y": _number(start_y + index * line_height),
            },
        )
        tspan.text = line


def _append_element(
    parent: ET.Element,
    element: dict[str, Any],
    children: dict[str | None, list[dict[str, Any]]],
    theme: dict[str, Any],
    plan_id: str,
) -> None:
    geometry = element["geometry"]
    style = element["style_tokens"]
    group = ET.SubElement(
        parent,
        _tag("g"),
        {
            "id": element["id"],
            "transform": f"translate({_number(geometry['x'])} {_number(geometry['y'])})",
            "data-plan-id": plan_id,
            "data-object-kind": "element",
            "data-element-kind": element["kind"],
            "data-semantic-role": element["semantic_role"],
            "data-parent-id": element.get("parent_id") or "",
            "data-representation-origin": element.get("representation_origin", ""),
            "data-source-ref": element.get("source_ref") or "",
            "data-width": _number(geometry["width"]),
            "data-height": _number(geometry["height"]),
        },
    )
    ET.SubElement(
        group,
        _tag("rect"),
        {
            "id": f"{element['id']}__shape",
            "x": "0",
            "y": "0",
            "width": _number(geometry["width"]),
            "height": _number(geometry["height"]),
            "rx": "12" if style.get("rounded", True) else "0",
            "fill": str(style.get("fill", "#FFFFFF")),
            "stroke": str(style.get("stroke", "#000000")),
            "stroke-width": _number(style.get("stroke_width_px", theme["line_width_px"])),
            "vector-effect": "non-scaling-stroke",
        },
    )
    _append_text(group, element, theme)
    for child in children.get(element["id"], []):
        _append_element(group, child, children, theme, plan_id)


def svg_tree(plan: dict[str, Any]) -> ET.ElementTree:
    issues = validate_render_plan_contract(plan)
    if issues:
        details = "; ".join(f"{issue.code}: {issue.message}" for issue in issues)
        raise SvgBackendError(f"RenderPlan is invalid: {details}")
    if plan.get("backend") != "svg":
        raise SvgBackendError("Native SVG authoring requires an SVG RenderPlan.")
    if not coverage_is_complete(plan):
        raise SvgBackendError(
            "plan.coverage.blocked: RenderPlan has unresolved FigureSpec requirements; "
            "authoring is refused until coverage is complete."
        )

    canvas = plan["canvas"]
    theme = plan["theme"]
    root = ET.Element(
        _tag("svg"),
        {
            "version": "1.1",
            "width": _number(canvas["width"]),
            "height": _number(canvas["height"]),
            "viewBox": f"0 0 {_number(canvas['width'])} {_number(canvas['height'])}",
            "role": "img",
            "data-plan-id": plan["plan_id"],
            "data-backend": "svg",
            "data-generated-by": "scientific-figure-skills",
        },
    )
    title = ET.SubElement(root, _tag("title"))
    title.text = str(plan.get("metadata", {}).get("working_title") or plan["figure_spec"]["figure_id"])
    defs = ET.SubElement(root, _tag("defs"))
    marker = ET.SubElement(
        defs,
        _tag("marker"),
        {
            "id": "svg-arrowhead",
            "viewBox": "0 0 10 10",
            "refX": "9",
            "refY": "5",
            "markerWidth": "8",
            "markerHeight": "8",
            "markerUnits": "userSpaceOnUse",
            "orient": "auto-start-reverse",
        },
    )
    ET.SubElement(marker, _tag("path"), {"d": "M 0 0 L 10 5 L 0 10 z", "fill": "context-stroke"})
    ET.SubElement(
        root,
        _tag("rect"),
        {
            "id": "svg-canvas-background",
            "x": "0",
            "y": "0",
            "width": _number(canvas["width"]),
            "height": _number(canvas["height"]),
            "fill": str(canvas["background"]),
            "data-object-kind": "technical",
        },
    )

    # SVG painter order is document order. Keep element fills below connectors
    # so a relation that targets a nested child remains visible through its
    # ancestor containers instead of losing its final segment and arrowhead.
    element_layer = ET.SubElement(
        root,
        _tag("g"),
        {"id": "svg-elements", "data-object-kind": "technical"},
    )

    geometries = _absolute_geometries(plan)
    parent_by_id = {item["id"]: item.get("parent_id") for item in plan["elements"]}
    connector_layer = ET.SubElement(root, _tag("g"), {"id": "svg-connectors", "data-object-kind": "technical"})
    for connector in plan["connectors"]:
        points = _route_connector(
            connector["source"],
            connector["target"],
            geometries,
            parent_by_id,
            canvas,
        )
        style = connector["style_tokens"]
        attributes = {
            "id": connector["id"],
            "points": " ".join(f"{_number(x)},{_number(y)}" for x, y in points),
            "fill": "none",
            "stroke": str(style.get("stroke", "#000000")),
            "stroke-width": _number(style.get("stroke_width_px", theme["line_width_px"])),
            "stroke-linejoin": "round",
            "stroke-linecap": "round",
            "vector-effect": "non-scaling-stroke",
            "data-plan-id": plan["plan_id"],
            "data-object-kind": "connector",
            "data-source": connector["source"],
            "data-target": connector["target"],
            "data-relation": connector["relation"],
            "data-directed": "true" if connector["directed"] else "false",
            "data-representation-origin": connector.get("representation_origin", ""),
            "data-source-ref": connector.get("source_ref") or "",
        }
        if style.get("dashed"):
            attributes["stroke-dasharray"] = "7 5"
        if connector["directed"]:
            attributes["marker-end"] = "url(#svg-arrowhead)"
        ET.SubElement(connector_layer, _tag("polyline"), attributes)
        label = connector.get("label", "")
        if label:
            label_x, label_y = _connector_label_position(points)
            final_size = plan["final_size"]
            final_width = float(final_size["width"])
            if final_size["unit"] == "mm":
                final_css_width = final_width / 25.4 * 96.0
            elif final_size["unit"] == "in":
                final_css_width = final_width * 96.0
            else:
                final_css_width = final_width
            scale = final_css_width / float(canvas["width"])
            minimum_source_px = (
                float(final_size["minimum_text_size_pt"]) * 96.0 / 72.0 / scale
            )
            label_font_size = max(
                float(style.get("font_size_px", theme["font_size_px"])),
                minimum_source_px + 0.01,
            )
            text = ET.SubElement(
                connector_layer,
                _tag("text"),
                {
                    "id": f"{connector['id']}__label",
                    "x": _number(label_x),
                    "y": _number(label_y),
                    "text-anchor": "middle",
                    "font-family": str(theme["font_family"]),
                    "font-size": _number(label_font_size),
                    "fill": str(style.get("font_color", "#000000")),
                    "data-text-role": "connector-label",
                },
            )
            tspan = ET.SubElement(text, _tag("tspan"), {"x": text.get("x", "0"), "y": text.get("y", "0")})
            tspan.text = label

    children: dict[str | None, list[dict[str, Any]]] = defaultdict(list)
    for element in plan["elements"]:
        children[element.get("parent_id")].append(element)
    for element in children.get(None, []):
        _append_element(element_layer, element, children, theme, plan["plan_id"])
    return ET.ElementTree(root)


def _indent_xml(element: ET.Element, level: int = 0) -> None:
    indentation = "\n" + "  " * level
    if len(element):
        if not element.text or not element.text.strip():
            element.text = indentation + "  "
        for child in element:
            _indent_xml(child, level + 1)
        if not element[-1].tail or not element[-1].tail.strip():
            element[-1].tail = indentation
    if level and (not element.tail or not element.tail.strip()):
        element.tail = indentation


def svg_bytes(plan: dict[str, Any]) -> bytes:
    tree = svg_tree(plan)
    root = tree.getroot()
    _indent_xml(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def write_svg_source(
    plan: dict[str, Any],
    output_path: Path,
    *,
    overwrite: bool = False,
) -> Path:
    output_path = output_path.expanduser().resolve()
    if output_path.suffix.casefold() != ".svg":
        raise SvgBackendError("Native SVG source path must end in .svg.")
    if output_path.exists() and not overwrite:
        raise SvgBackendError(f"Refusing to overwrite existing file: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = svg_bytes(plan)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, output_path)
    except OSError as exc:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass
        raise SvgBackendError(f"Could not write native SVG source: {exc}") from exc
    return output_path


def author_from_plan_file(
    plan_path: Path,
    output_path: Path | None = None,
    *,
    overwrite: bool = False,
) -> Path:
    plan_path = plan_path.expanduser().resolve()
    try:
        plan = read_json(plan_path)
    except RuntimeContractError as exc:
        raise SvgBackendError(str(exc)) from exc
    if output_path is None:
        output_path = plan_path.parent / plan["outputs"]["source"]
    elif not output_path.is_absolute():
        output_path = Path.cwd() / output_path
    return write_svg_source(plan, output_path, overwrite=overwrite)
