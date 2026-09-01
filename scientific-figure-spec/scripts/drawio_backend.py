#!/usr/bin/env python3
"""Draw.io adapter for the shared structured-diagram RenderPlan."""

from __future__ import annotations

import os
import importlib.util
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

try:
    from diagram_plan import DiagramPlanError
    from diagram_plan import build_render_plan as _build_shared_render_plan
    from diagram_plan import create_render_plan_file as _create_shared_render_plan_file
except ModuleNotFoundError as exc:
    if exc.name != "diagram_plan":
        raise
    module_path = Path(__file__).resolve().with_name("diagram_plan.py")
    module_spec = importlib.util.spec_from_file_location("diagram_plan", module_path)
    if module_spec is None or module_spec.loader is None:
        raise ImportError(f"Could not load shared diagram planner: {module_path}") from exc
    diagram_plan = importlib.util.module_from_spec(module_spec)
    sys.modules["diagram_plan"] = diagram_plan
    module_spec.loader.exec_module(diagram_plan)
    DiagramPlanError = diagram_plan.DiagramPlanError
    _build_shared_render_plan = diagram_plan.build_render_plan
    _create_shared_render_plan_file = diagram_plan.create_render_plan_file
from figure_coverage import coverage_is_complete
from figure_runtime import (
    RuntimeContractError,
    read_json,
    validate_render_plan_contract,
)


DrawioBackendError = DiagramPlanError


def build_render_plan(
    spec_path: Path,
    plan_path: Path,
    *,
    backend: str,
    strict: bool = False,
) -> dict[str, Any]:
    """Compatibility wrapper for legacy Draw.io planner callers."""

    if backend != "drawio":
        raise DrawioBackendError("Draw.io planner wrapper requires backend='drawio'.")
    return _build_shared_render_plan(
        spec_path,
        plan_path,
        backend=backend,
        strict=strict,
    )


def create_render_plan_file(
    spec_path: Path,
    plan_path: Path,
    *,
    backend: str,
    strict: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Compatibility wrapper for legacy Draw.io planner callers."""

    if backend != "drawio":
        raise DrawioBackendError("Draw.io planner wrapper requires backend='drawio'.")
    return _create_shared_render_plan_file(
        spec_path,
        plan_path,
        backend=backend,
        strict=strict,
        overwrite=overwrite,
    )


def _bool_token(value: Any) -> str:
    return "1" if bool(value) else "0"


def _element_style(element: dict[str, Any], theme: dict[str, Any]) -> str:
    style = element["style_tokens"]
    tokens = [
        f"rounded={_bool_token(style.get('rounded', True))}",
        "whiteSpace=wrap",
        "html=1",
        f"fillColor={style.get('fill', '#FFFFFF')}",
        f"strokeColor={style.get('stroke', '#000000')}",
        f"fontColor={style.get('font_color', '#000000')}",
        f"fontSize={style.get('font_size_px', theme['font_size_px'])}",
        f"fontFamily={theme['font_family']}",
        f"fontStyle={1 if style.get('bold') else 0}",
        f"strokeWidth={style.get('stroke_width_px', theme['line_width_px'])}",
        f"align={style.get('align', 'center')}",
        f"verticalAlign={style.get('vertical_align', 'middle')}",
        "spacing=8",
    ]
    if element["kind"] == "container":
        tokens.extend(["container=1", "collapsible=0", "fontStyle=1", "verticalAlign=top"])
    return ";".join(tokens) + ";"


def _connector_style(connector: dict[str, Any], theme: dict[str, Any]) -> str:
    style = connector["style_tokens"]
    directed = connector["directed"]
    tokens = [
        "edgeStyle=orthogonalEdgeStyle",
        "rounded=0",
        "orthogonalLoop=1",
        "jettySize=auto",
        "html=1",
        f"strokeColor={style.get('stroke', '#000000')}",
        f"strokeWidth={style.get('stroke_width_px', theme['line_width_px'])}",
        f"fontColor={style.get('font_color', '#000000')}",
        f"fontSize={style.get('font_size_px', theme['font_size_px'])}",
        f"fontFamily={theme['font_family']}",
        f"dashed={_bool_token(style.get('dashed', False))}",
        f"endArrow={'block' if directed else 'none'}",
        f"endFill={1 if directed else 0}",
        "startArrow=none",
    ]
    return ";".join(tokens) + ";"


def drawio_tree(plan: dict[str, Any]) -> ET.ElementTree:
    issues = validate_render_plan_contract(plan)
    if issues:
        details = "; ".join(f"{issue.code}: {issue.message}" for issue in issues)
        raise DrawioBackendError(f"RenderPlan is invalid: {details}")
    if plan.get("backend") != "drawio":
        raise DrawioBackendError("Draw.io authoring requires a Draw.io RenderPlan.")
    if not coverage_is_complete(plan):
        raise DrawioBackendError(
            "plan.coverage.blocked: RenderPlan has unresolved FigureSpec requirements; "
            "authoring is refused until coverage is complete."
        )

    canvas = plan["canvas"]
    theme = plan["theme"]
    mxfile = ET.Element(
        "mxfile",
        {
            "host": "app.diagrams.net",
            "agent": "scientific-figure-skills",
            "type": "device",
            "compressed": "false",
            "data-plan-id": plan["plan_id"],
        },
    )
    diagram = ET.SubElement(mxfile, "diagram", {"id": plan["plan_id"], "name": "Page-1"})
    model = ET.SubElement(
        diagram,
        "mxGraphModel",
        {
            "dx": "1200",
            "dy": "800",
            "grid": "1",
            "gridSize": "10",
            "guides": "1",
            "tooltips": "1",
            "connect": "1",
            "arrows": "1",
            "fold": "1",
            "page": "1",
            "pageScale": "1",
            "pageWidth": str(canvas["width"]),
            "pageHeight": str(canvas["height"]),
            "background": canvas["background"],
            "math": "0",
            "shadow": "0",
        },
    )
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    ordered_elements = sorted(
        enumerate(plan["elements"]),
        key=lambda item: (item[1]["kind"] != "container", item[0]),
    )
    for _, element in ordered_elements:
        cell = ET.SubElement(
            root,
            "mxCell",
            {
                "id": element["id"],
                "value": element["label"],
                "style": _element_style(element, theme),
                "vertex": "1",
                "parent": element.get("parent_id") or "1",
                "data-semantic-role": element["semantic_role"],
                "data-source-ref": element.get("source_ref") or "",
            },
        )
        geometry = element["geometry"]
        ET.SubElement(
            cell,
            "mxGeometry",
            {
                "x": str(geometry["x"]),
                "y": str(geometry["y"]),
                "width": str(geometry["width"]),
                "height": str(geometry["height"]),
                "as": "geometry",
            },
        )

    for connector in plan["connectors"]:
        cell = ET.SubElement(
            root,
            "mxCell",
            {
                "id": connector["id"],
                "value": connector.get("label", ""),
                "style": _connector_style(connector, theme),
                "edge": "1",
                "parent": "1",
                "source": connector["source"],
                "target": connector["target"],
                "data-relation": connector["relation"],
                "data-directed": "true" if connector["directed"] else "false",
            },
        )
        ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
    return ET.ElementTree(mxfile)


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


def drawio_bytes(plan: dict[str, Any]) -> bytes:
    tree = drawio_tree(plan)
    root = tree.getroot()
    _indent_xml(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def write_drawio_source(
    plan: dict[str, Any],
    output_path: Path,
    *,
    overwrite: bool = False,
) -> Path:
    output_path = output_path.expanduser().resolve()
    if output_path.suffix.casefold() != ".drawio":
        raise DrawioBackendError("Draw.io source path must end in .drawio.")
    if output_path.exists() and not overwrite:
        raise DrawioBackendError(f"Refusing to overwrite existing file: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = drawio_bytes(plan)
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
        raise DrawioBackendError(f"Could not write Draw.io source: {exc}") from exc
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
        raise DrawioBackendError(str(exc)) from exc
    if output_path is None:
        output_path = plan_path.parent / plan["outputs"]["source"]
    elif not output_path.is_absolute():
        output_path = Path.cwd() / output_path
    return write_drawio_source(plan, output_path, overwrite=overwrite)
