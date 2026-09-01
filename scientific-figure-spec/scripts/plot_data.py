#!/usr/bin/env python3
"""Deterministic local data loading for PlotPlan 1.0.

This is intentionally not a dataframe or analysis layer. It reads declared
authoritative plotting tables, preserves row order, and exposes only the small
set of binding operations supported by the Matplotlib backend.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from figure_runtime import RuntimeIssue, sha256_file


SUPPORTED_FORMATS = {"csv", "tsv", "json-records"}


@dataclass(frozen=True)
class LoadedData:
    source_id: str
    path: Path
    format: str
    sha256: str
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def missing_counts(self, columns: Iterable[str]) -> dict[str, int]:
        return {
            column: sum(is_missing(row.get(column)) for row in self.rows)
            for column in columns
        }


def portable_path(path: Path, base: Path) -> str:
    try:
        return os.path.relpath(path.resolve(), base.resolve())
    except ValueError:
        return str(path.resolve())


def resolve_declared_path(value: str, plan_path: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = plan_path.resolve().parent / path
    return path.resolve()


def is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def numeric_value(value: Any) -> float:
    if isinstance(value, bool) or is_missing(value):
        raise ValueError("missing or boolean value is not numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{value!r} is not numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{value!r} is not a finite numeric value")
    return result


def _read_delimited(path: Path, *, delimiter: str) -> tuple[list[str], list[dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, delimiter=delimiter)
            try:
                header = next(reader)
            except StopIteration:
                return [], []
            columns = [item.strip() for item in header]
            if any(not item for item in columns):
                raise ValueError("column names must be non-empty")
            if len(columns) != len(set(columns)):
                raise ValueError("column names must be unique")
            rows: list[dict[str, Any]] = []
            for row_number, values in enumerate(reader, start=2):
                if len(values) != len(columns):
                    raise ValueError(
                        f"row {row_number} has {len(values)} fields; expected {len(columns)}"
                    )
                rows.append(dict(zip(columns, values, strict=True)))
            return columns, rows
    except UnicodeDecodeError as exc:
        raise ValueError("file is not valid UTF-8") from exc


def _read_json_records(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("file is not valid UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    if not isinstance(value, list):
        raise ValueError("JSON records input must be a top-level array")
    rows: list[dict[str, Any]] = []
    columns: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict) or not all(isinstance(key, str) for key in item):
            raise ValueError(f"JSON record {index} must be an object with string keys")
        rows.append(dict(item))
        for key in item:
            if key not in seen:
                seen.add(key)
                columns.append(key)
    for row in rows:
        for column in columns:
            row.setdefault(column, None)
    return columns, rows


def load_data_source(
    declaration: dict[str, Any],
    plan_path: Path,
) -> tuple[LoadedData | None, list[RuntimeIssue]]:
    """Load one declared local table and verify its identity."""

    issues: list[RuntimeIssue] = []
    source_id = declaration.get("id")
    source_id = source_id if isinstance(source_id, str) else "unknown"
    format_name = declaration.get("format")
    raw_path = declaration.get("path")
    if not isinstance(raw_path, str):
        return None, [
            RuntimeIssue(
                "ERROR",
                "plot.data.path_invalid",
                f"Data source {source_id!r} has no usable local path.",
            )
        ]
    path = resolve_declared_path(raw_path, plan_path)
    if not path.is_file():
        return None, [
            RuntimeIssue(
                "ERROR",
                "plot.data.file_missing",
                f"Declared data source is not a local regular file: {path}",
            )
        ]
    if format_name not in SUPPORTED_FORMATS:
        return None, [
            RuntimeIssue(
                "ERROR",
                "plot.data.format_unsupported",
                f"Data source {source_id!r} uses unsupported format {format_name!r}.",
            )
        ]

    actual_hash = sha256_file(path)
    if declaration.get("sha256") != actual_hash:
        issues.append(
            RuntimeIssue(
                "ERROR",
                "plot.data.hash_mismatch",
                f"Data source {source_id!r} changed after PlotPlan creation.",
            )
        )
    try:
        if format_name == "csv":
            columns, rows = _read_delimited(path, delimiter=",")
        elif format_name == "tsv":
            columns, rows = _read_delimited(path, delimiter="\t")
        else:
            columns, rows = _read_json_records(path)
    except (OSError, ValueError) as exc:
        issues.append(
            RuntimeIssue(
                "ERROR",
                "plot.data.parse_failed",
                f"Could not parse data source {source_id!r}: {exc}",
            )
        )
        return None, issues
    if not columns:
        issues.append(
            RuntimeIssue(
                "ERROR",
                "plot.data.columns_missing",
                f"Data source {source_id!r} has no columns.",
            )
        )
    if not rows:
        issues.append(
            RuntimeIssue(
                "ERROR",
                "plot.data.rows_missing",
                f"Data source {source_id!r} has no records.",
            )
        )
    loaded = LoadedData(
        source_id=source_id,
        path=path,
        format=str(format_name),
        sha256=actual_hash,
        columns=tuple(columns),
        rows=tuple(rows),
    )
    return loaded, issues


def row_matches(row: dict[str, Any], filter_spec: dict[str, Any] | None) -> bool:
    if not filter_spec:
        return True
    column = filter_spec.get("column")
    operator = filter_spec.get("operator")
    actual = row.get(column)
    if operator == "eq":
        return actual == filter_spec.get("value") or str(actual) == str(filter_spec.get("value"))
    if operator == "in":
        values = filter_spec.get("values")
        if not isinstance(values, list):
            return False
        return any(actual == item or str(actual) == str(item) for item in values)
    return False


def filtered_rows(
    data: LoadedData,
    filter_spec: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    return [row for row in data.rows if row_matches(row, filter_spec)]


def value_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
