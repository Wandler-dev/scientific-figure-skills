#!/usr/bin/env python3
"""Normalize Draw.io and native SVG sources into one scientific object model."""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


class FigureSourceError(RuntimeError):
    """Raised when an editable source cannot be normalized safely."""


URL_REFERENCE_RE = re.compile(
    r"url\(\s*(?P<quote>['\"]?)(?P<target>.*?)\1\s*\)",
    re.IGNORECASE,
)
CONNECTOR_PRIMITIVES = {"line", "polyline", "path"}
MARKER_PROPERTIES = {"marker", "marker-start", "marker-mid", "marker-end"}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _plain_text(value: str | None) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(value.split())


def _style_map(value: str | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for token in (value or "").split(";"):
        if "=" in token:
            key, item = token.split("=", 1)
            result[key.strip()] = item.strip()
    return result


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


def _number(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except ValueError:
        return default


def _plan_maps(plan: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    if plan is None:
        return {}, {}
    return (
        {item["id"]: item for item in plan.get("elements", [])},
        {item["id"]: item for item in plan.get("connectors", [])},
    )


def _normalize_drawio(
    source_path: Path,
    plan: dict[str, Any] | None,
) -> dict[str, Any]:
    try:
        document = ET.parse(source_path)
    except (OSError, ET.ParseError) as exc:
        raise FigureSourceError(f"Could not parse Draw.io source: {exc}") from exc
    root = document.getroot()
    graph_root = root.find("./diagram/mxGraphModel/root")
    if graph_root is None:
        raise FigureSourceError("Draw.io source is missing mxGraphModel/root.")
    cells = graph_root.findall("mxCell")
    cell_by_id = {cell.get("id"): cell for cell in cells if cell.get("id")}
    plan_elements, plan_connectors = _plan_maps(plan)
    objects: dict[str, dict[str, Any]] = {}
    connectors: dict[str, dict[str, Any]] = {}
    embedded_raster = False

    for cell in cells:
        cell_id = cell.get("id")
        if not cell_id:
            continue
        style = _style_map(cell.get("style"))
        raw_style = (cell.get("style") or "").casefold()
        raw_value = (cell.get("value") or "").casefold()
        if "image=" in raw_style or "data:image/" in raw_style or "data:image/" in raw_value:
            embedded_raster = True
        if cell.get("vertex") == "1":
            geometry = cell.find("mxGeometry")
            if geometry is None:
                local = {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0}
            else:
                local = {
                    "x": _number(geometry.get("x")),
                    "y": _number(geometry.get("y")),
                    "width": _number(geometry.get("width")),
                    "height": _number(geometry.get("height")),
                }
            planned = plan_elements.get(cell_id, {})
            parent = cell.get("parent")
            parent_id = parent if parent in plan_elements or parent in cell_by_id and parent not in {"0", "1"} else None
            objects[cell_id] = {
                "id": cell_id,
                "label": _plain_text(cell.get("value")),
                "parent_id": parent_id,
                "kind": planned.get("kind") or ("container" if style.get("container") == "1" else "node"),
                "semantic_role": cell.get("data-semantic-role") or planned.get("semantic_role") or "content",
                "representation_origin": planned.get("representation_origin"),
                "source_ref": cell.get("data-source-ref") or planned.get("source_ref"),
                "geometry": local,
                "fill": style.get("fillColor"),
                "stroke": style.get("strokeColor"),
                "font_size_px": _number(style.get("fontSize"), 0.0),
            }
        elif cell.get("edge") == "1":
            planned = plan_connectors.get(cell_id, {})
            directed_value = cell.get("data-directed")
            directed = (
                directed_value == "true"
                if directed_value is not None
                else style.get("endArrow") not in {None, "none"}
            )
            connectors[cell_id] = {
                "id": cell_id,
                "source": cell.get("source"),
                "target": cell.get("target"),
                "relation": cell.get("data-relation") or planned.get("relation") or "relation",
                "directed": directed,
                "label": _plain_text(cell.get("value")),
                "representation_origin": planned.get("representation_origin"),
                "stroke": style.get("strokeColor"),
            }

    absolute: dict[str, dict[str, float]] = {}

    def resolve(object_id: str, visiting: set[str]) -> dict[str, float]:
        if object_id in absolute:
            return absolute[object_id]
        if object_id in visiting:
            raise FigureSourceError(f"Draw.io object hierarchy cycles at {object_id!r}.")
        visiting.add(object_id)
        item = objects[object_id]
        geometry = dict(item["geometry"])
        parent_id = item.get("parent_id")
        if isinstance(parent_id, str) and parent_id in objects:
            parent = resolve(parent_id, visiting)
            geometry["x"] += parent["x"]
            geometry["y"] += parent["y"]
        visiting.remove(object_id)
        absolute[object_id] = geometry
        return geometry

    for object_id in objects:
        objects[object_id]["absolute_geometry"] = resolve(object_id, set())

    return {
        "backend": "drawio",
        "path": source_path,
        "plan_id": root.get("data-plan-id"),
        "objects": objects,
        "connectors": connectors,
        "extra_labels": [],
        "embedded_raster": embedded_raster,
        "external_references": [],
        "live_text_count": sum(bool(item["label"]) for item in objects.values()),
    }


def _normalize_svg(
    source_path: Path,
    plan: dict[str, Any] | None,
) -> dict[str, Any]:
    try:
        document = ET.parse(source_path)
    except (OSError, ET.ParseError) as exc:
        raise FigureSourceError(f"Could not parse SVG source: {exc}") from exc
    root = document.getroot()
    if _local_name(root.tag) != "svg":
        raise FigureSourceError("Native SVG source root must be <svg>.")
    plan_elements, plan_connectors = _plan_maps(plan)
    objects: dict[str, dict[str, Any]] = {}
    connectors: dict[str, dict[str, Any]] = {}
    known_label_ids: set[str] = set()
    external_references: list[str] = []
    embedded_raster = False
    anonymous_relation_index = 0
    nodes_by_id = {
        str(node.get("id")): node
        for node in root.iter()
        if node.get("id")
    }

    def direct_child(node: ET.Element, name: str) -> ET.Element | None:
        return next((child for child in node if _local_name(child.tag) == name), None)

    def walk(
        node: ET.Element,
        offset_x: float,
        offset_y: float,
        parent_element_id: str | None,
    ) -> None:
        nonlocal anonymous_relation_index, embedded_raster
        name = _local_name(node.tag)
        if name == "image":
            embedded_raster = True
        for attribute, value in node.attrib.items():
            attribute_name = _local_name(attribute).casefold()
            lowered = value.strip().casefold()
            if attribute_name in {"href", "src"} and lowered and not lowered.startswith("#"):
                if lowered.startswith("data:image/"):
                    embedded_raster = True
                else:
                    external_references.append(value)
            for match in URL_REFERENCE_RE.finditer(value):
                target = match.group("target").strip()
                if not target or target.startswith("#"):
                    continue
                if target.casefold().startswith("data:image/"):
                    embedded_raster = True
                else:
                    external_references.append(target)
        if name == "style":
            stylesheet = "".join(node.itertext())
            for match in URL_REFERENCE_RE.finditer(stylesheet):
                target = match.group("target").strip()
                if not target or target.startswith("#"):
                    continue
                if target.casefold().startswith("data:image/"):
                    embedded_raster = True
                else:
                    external_references.append(target)

        translation_x = 0.0
        translation_y = 0.0
        transform = node.get("transform") or ""
        match = re.match(r"^\s*translate\(\s*([-+0-9.eE]+)(?:[\s,]+([-+0-9.eE]+))?\s*\)\s*$", transform)
        if match:
            translation_x = _number(match.group(1))
            translation_y = _number(match.group(2))
        current_x = offset_x + translation_x
        current_y = offset_y + translation_y
        current_parent = parent_element_id
        node_id = node.get("id")
        if node.get("data-object-kind") == "element" and node_id:
            planned = plan_elements.get(node_id, {})
            width = _number(node.get("data-width"))
            height = _number(node.get("data-height"))
            shape = direct_child(node, "rect")
            label_node = next(
                (
                    child
                    for child in node
                    if _local_name(child.tag) == "text"
                    and child.get("data-text-role") == "element-label"
                ),
                None,
            )
            if label_node is not None and label_node.get("id"):
                known_label_ids.add(str(label_node.get("id")))
            objects[node_id] = {
                "id": node_id,
                "label": _plain_text(" ".join(label_node.itertext())) if label_node is not None else "",
                "parent_id": parent_element_id,
                "kind": node.get("data-element-kind") or planned.get("kind") or "node",
                "semantic_role": node.get("data-semantic-role") or planned.get("semantic_role") or "content",
                "representation_origin": node.get("data-representation-origin") or planned.get("representation_origin"),
                "source_ref": node.get("data-source-ref") or planned.get("source_ref"),
                "geometry": {
                    "x": translation_x,
                    "y": translation_y,
                    "width": width,
                    "height": height,
                },
                "absolute_geometry": {
                    "x": current_x,
                    "y": current_y,
                    "width": width,
                    "height": height,
                },
                "fill": shape.get("fill") if shape is not None else None,
                "stroke": shape.get("stroke") if shape is not None else None,
                "font_size_px": _number(label_node.get("font-size")) if label_node is not None else 0.0,
            }
            current_parent = node_id
        elif node.get("data-object-kind") == "connector" and node_id:
            planned = plan_connectors.get(node_id, {})
            label_id = f"{node_id}__label"
            candidate = nodes_by_id.get(label_id)
            label_node = (
                candidate
                if candidate is not None and _local_name(candidate.tag) == "text"
                else None
            )
            if label_node is not None:
                known_label_ids.add(label_id)
            connectors[node_id] = {
                "id": node_id,
                "source": node.get("data-source"),
                "target": node.get("data-target"),
                "relation": node.get("data-relation") or planned.get("relation") or "relation",
                "directed": node.get("data-directed") == "true",
                "label": (
                    _plain_text(" ".join(label_node.itertext()))
                    if label_node is not None
                    else ""
                ),
                "representation_origin": node.get("data-representation-origin") or planned.get("representation_origin"),
                "stroke": node.get("stroke"),
            }
        elif name in CONNECTOR_PRIMITIVES and _has_arrow_marker(node):
            anonymous_relation_index += 1
            connector_id = node_id or f"svg-unplanned-relation-{anonymous_relation_index:03d}"
            connectors[connector_id] = {
                "id": connector_id,
                "source": node.get("data-source"),
                "target": node.get("data-target"),
                "relation": node.get("data-relation") or "unplanned arrow",
                "directed": True,
                "label": "",
                "representation_origin": node.get("data-representation-origin")
                or "SOURCE_ONLY",
                "stroke": node.get("stroke"),
            }
        for child in node:
            walk(child, current_x, current_y, current_parent)

    walk(root, 0.0, 0.0, None)
    extra_labels = [
        _plain_text(" ".join(node.itertext()))
        for node in root.iter()
        if _local_name(node.tag) == "text"
        and node.get("id") not in known_label_ids
        and node.get("data-text-role") not in {"technical", "decorative", "metadata"}
        and _plain_text(" ".join(node.itertext()))
    ]
    live_text_count = sum(
        1
        for node in root.iter()
        if _local_name(node.tag) == "text" and _plain_text(" ".join(node.itertext()))
    )
    return {
        "backend": "svg",
        "path": source_path,
        "plan_id": root.get("data-plan-id"),
        "objects": objects,
        "connectors": connectors,
        "extra_labels": extra_labels,
        "embedded_raster": embedded_raster,
        "external_references": external_references,
        "live_text_count": live_text_count,
    }


def normalize_source(
    source_path: Path,
    *,
    backend: str | None = None,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_path = source_path.expanduser().resolve()
    selected = backend
    if selected is None:
        selected = "drawio" if source_path.suffix.casefold() == ".drawio" else "svg" if source_path.suffix.casefold() == ".svg" else None
    if selected == "drawio":
        return _normalize_drawio(source_path, plan)
    if selected == "svg":
        return _normalize_svg(source_path, plan)
    raise FigureSourceError(f"Unsupported editable source backend: {selected!r}")


def normalized_semantic_signature(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "objects": [
            {
                "id": item["id"],
                "label": item["label"],
                "parent_id": item.get("parent_id"),
                "kind": item["kind"],
                "semantic_role": item["semantic_role"],
                "representation_origin": item.get("representation_origin"),
                "fill": item.get("fill"),
                "stroke": item.get("stroke"),
            }
            for item in sorted(source["objects"].values(), key=lambda value: value["id"])
        ],
        "connectors": [
            {
                "id": item["id"],
                "source": item.get("source"),
                "target": item.get("target"),
                "relation": item["relation"],
                "directed": item["directed"],
                "label": item.get("label", ""),
                "representation_origin": item.get("representation_origin"),
            }
            for item in sorted(source["connectors"].values(), key=lambda value: value["id"])
        ],
    }
