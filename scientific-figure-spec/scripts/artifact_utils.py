#!/usr/bin/env python3
"""Backend-neutral helpers for vector/raster artifact records and dimensions."""

from __future__ import annotations

import os
import re
import struct
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path
from typing import Any

from figure_runtime import sha256_file


MEDIA_TYPES = {
    "svg": "image/svg+xml",
    "pdf": "application/pdf",
    "png": "image/png",
}
PDF_NUMBER = rb"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
PDF_MEDIA_BOX_RE = re.compile(
    rb"/MediaBox\s*\[\s*(" + PDF_NUMBER + rb")\s+(" + PDF_NUMBER
    + rb")\s+(" + PDF_NUMBER + rb")\s+(" + PDF_NUMBER + rb")\s*\]"
)


def portable_path(path: Path, base: Path) -> str:
    try:
        return os.path.relpath(path.resolve(), base.resolve())
    except ValueError:
        return str(path.resolve())


def file_reference(path: Path, base: Path, media_type: str) -> dict[str, Any]:
    return {
        "path": portable_path(path, base),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "media_type": media_type,
    }


def _dimension_number(value: str | None) -> float | None:
    if value is None:
        return None
    match = re.match(r"^\s*(\d+(?:\.\d+)?)", value)
    return float(match.group(1)) if match else None


def _pdf_dimensions(payload: bytes) -> dict[str, Any] | None:
    def match_dimensions(candidate: bytes) -> dict[str, Any] | None:
        match = PDF_MEDIA_BOX_RE.search(candidate)
        if match is None:
            return None
        x0, y0, x1, y1 = (float(value) for value in match.groups())
        width = abs(x1 - x0)
        height = abs(y1 - y0)
        if width <= 0 or height <= 0:
            return None
        return {"width": width, "height": height, "unit": "pt"}

    direct = match_dimensions(payload)
    if direct is not None:
        return direct

    # Cairo commonly stores the Page dictionary in a compressed object stream.
    # Decode bounded Flate streams only; this is not a general PDF parser.
    for marker in re.finditer(rb"stream\r?\n", payload):
        header_start = payload.rfind(b"<<", max(0, marker.start() - 4096), marker.start())
        if header_start < 0 or b"/FlateDecode" not in payload[header_start : marker.start()]:
            continue
        stream_end = payload.find(b"endstream", marker.end())
        if stream_end < 0:
            continue
        compressed = payload[marker.end() : stream_end].rstrip(b"\r\n")
        try:
            decompressor = zlib.decompressobj()
            decoded = decompressor.decompress(compressed, 2 * 1024 * 1024)
        except zlib.error:
            continue
        dimensions = match_dimensions(decoded)
        if dimensions is not None:
            return dimensions
    return None


def inspect_artifact_dimensions(path: Path, format_name: str) -> dict[str, Any] | None:
    try:
        if format_name == "svg":
            root = ET.parse(path).getroot()
            width = _dimension_number(root.get("width"))
            height = _dimension_number(root.get("height"))
            if width and height:
                return {"width": width, "height": height, "unit": "px"}
            view_box = root.get("viewBox")
            if view_box:
                values = [float(item) for item in view_box.replace(",", " ").split()]
                if len(values) == 4 and values[2] > 0 and values[3] > 0:
                    return {"width": values[2], "height": values[3], "unit": "viewBox"}
        elif format_name == "png":
            payload = path.read_bytes()[:24]
            if payload.startswith(b"\x89PNG\r\n\x1a\n") and len(payload) >= 24:
                width, height = struct.unpack(">II", payload[16:24])
                if width > 0 and height > 0:
                    return {"width": width, "height": height, "unit": "px"}
        elif format_name == "pdf":
            with path.open("rb") as handle:
                payload = handle.read(16 * 1024 * 1024)
            if not payload.startswith(b"%PDF-"):
                return None
            return _pdf_dimensions(payload)
    except (OSError, ET.ParseError, ValueError, struct.error):
        return None
    return None
