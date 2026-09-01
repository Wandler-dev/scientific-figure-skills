#!/usr/bin/env python3
"""Test-only Draw.io CLI double.

This is not a production exporter. It exists solely to exercise subprocess,
manifest, inspection, and failure behavior without pretending that Draw.io
Desktop is installed in the test environment.
"""

from __future__ import annotations

import html
import re
import struct
import sys
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path


def style_map(value: str | None) -> dict[str, str]:
    result = {}
    for token in (value or "").split(";"):
        if "=" in token:
            key, item = token.split("=", 1)
            result[key] = item
    return result


def source_model(path: Path):
    document = ET.parse(path)
    model = document.getroot().find("./diagram/mxGraphModel")
    if model is None:
        raise RuntimeError("missing mxGraphModel")
    width = int(float(model.get("pageWidth", "1000")))
    height = int(float(model.get("pageHeight", "600")))
    root = model.find("root")
    if root is None:
        raise RuntimeError("missing graph root")
    return width, height, root


def absolute_geometry(
    cell: ET.Element,
    cells: dict[str | None, ET.Element],
    cache: dict[str, tuple[float, float, float, float]],
) -> tuple[float, float, float, float]:
    cell_id = cell.get("id") or ""
    if cell_id in cache:
        return cache[cell_id]
    geometry = cell.find("mxGeometry")
    if geometry is None:
        return (0.0, 0.0, 0.0, 0.0)
    x = float(geometry.get("x", "0"))
    y = float(geometry.get("y", "0"))
    width = float(geometry.get("width", "0"))
    height = float(geometry.get("height", "0"))
    parent = cells.get(cell.get("parent"))
    if parent is not None and parent.get("vertex") == "1":
        parent_x, parent_y, _, _ = absolute_geometry(parent, cells, cache)
        x += parent_x
        y += parent_y
    result = (x, y, width, height)
    cache[cell_id] = result
    return result


def write_svg(source: Path, output: Path) -> None:
    width, height, graph_root = source_model(source)
    svg = ET.Element(
        "svg",
        {
            "xmlns": "http://www.w3.org/2000/svg",
            "width": str(width),
            "height": str(height),
            "viewBox": f"0 0 {width} {height}",
        },
    )
    ET.SubElement(
        svg,
        "rect",
        {"x": "0", "y": "0", "width": str(width), "height": str(height), "fill": "#FFFFFF"},
    )
    cells = {cell.get("id"): cell for cell in graph_root.findall("mxCell") if cell.get("id")}
    geometry_cache: dict[str, tuple[float, float, float, float]] = {}
    for cell in graph_root.findall("mxCell"):
        if cell.get("edge") != "1":
            continue
        source_cell = cells.get(cell.get("source"))
        target_cell = cells.get(cell.get("target"))
        if source_cell is None or target_cell is None:
            continue
        source_x, source_y, source_width, source_height = absolute_geometry(
            source_cell, cells, geometry_cache
        )
        target_x, target_y, target_width, target_height = absolute_geometry(
            target_cell, cells, geometry_cache
        )
        sx = source_x + source_width / 2
        sy = source_y + source_height / 2
        tx = target_x + target_width / 2
        ty = target_y + target_height / 2
        style = style_map(cell.get("style"))
        ET.SubElement(
            svg,
            "line",
            {
                "x1": str(sx),
                "y1": str(sy),
                "x2": str(tx),
                "y2": str(ty),
                "stroke": style.get("strokeColor", "#6B7F93"),
                "stroke-width": style.get("strokeWidth", "2"),
                "data-source": cell.get("source", ""),
                "data-target": cell.get("target", ""),
            },
        )
    for cell in graph_root.findall("mxCell"):
        if cell.get("vertex") != "1":
            continue
        x, y, cell_width, cell_height = absolute_geometry(
            cell, cells, geometry_cache
        )
        style = style_map(cell.get("style"))
        group = ET.SubElement(svg, "g", {"data-cell-id": cell.get("id", "")})
        ET.SubElement(
            group,
            "rect",
            {
                "x": str(x),
                "y": str(y),
                "width": str(cell_width),
                "height": str(cell_height),
                "rx": "12" if style.get("rounded") == "1" else "0",
                "fill": style.get("fillColor", "#FFFFFF"),
                "stroke": style.get("strokeColor", "#17324D"),
                "stroke-width": style.get("strokeWidth", "2"),
            },
        )
        label = re.sub(r"<[^>]+>", "", html.unescape(cell.get("value", "")))
        text = ET.SubElement(
            group,
            "text",
            {
                "x": str(x + cell_width / 2),
                "y": str(y + cell_height / 2),
                "text-anchor": "middle",
                "dominant-baseline": "middle",
                "font-family": style.get("fontFamily", "Arial"),
                "font-size": style.get("fontSize", "16"),
                "fill": style.get("fontColor", "#17324D"),
            },
        )
        text.text = label
    ET.ElementTree(svg).write(output, encoding="utf-8", xml_declaration=True)


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def write_png(source: Path, output: Path) -> None:
    width, height, _ = source_model(source)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row = b"\x00" + b"\xff\xff\xff" * width
    payload = zlib.compress(row * height, level=9)
    output.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", payload)
        + png_chunk(b"IEND", b"")
    )


def write_pdf(source: Path, output: Path) -> None:
    width, height, _ = source_model(source)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] /Contents 4 0 R >>".encode(),
        b"<< /Length 0 >>\nstream\n\nendstream",
    ]
    payload = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(payload))
        payload.extend(f"{index} 0 obj\n".encode())
        payload.extend(body)
        payload.extend(b"\nendobj\n")
    xref = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    payload.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode())
    payload.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    output.write_bytes(payload)


def main() -> int:
    arguments = sys.argv[1:]
    if arguments == ["--version"]:
        print("draw.io test-double 0.1")
        return 0
    try:
        format_name = arguments[arguments.index("--format") + 1]
        output = Path(arguments[arguments.index("--output") + 1])
        source = Path(arguments[-1])
    except (ValueError, IndexError):
        print("invalid fake Draw.io CLI arguments", file=sys.stderr)
        return 2
    if "--export" not in arguments:
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)
    if format_name == "svg":
        write_svg(source, output)
    elif format_name == "png":
        write_png(source, output)
    elif format_name == "pdf":
        write_pdf(source, output)
    else:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
