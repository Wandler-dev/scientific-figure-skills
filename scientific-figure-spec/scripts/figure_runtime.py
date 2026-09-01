#!/usr/bin/env python3
"""Shared runtime contracts for the Scientific Figure Skills execution loop.

The module intentionally depends only on the Python standard library. It
validates the JSON Schema subset used by the three execution sidecars and adds
cross-field checks that JSON Schema cannot express conveniently.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import importlib.metadata
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SKILL_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_ROOT = SKILL_ROOT / "schemas"
CAPABILITY_REGISTRY_PATH = SKILL_ROOT / "capabilities.json"

SCHEMA_FILES = {
    "render-plan": SCHEMA_ROOT / "render-plan.schema.json",
    "plot-plan": SCHEMA_ROOT / "plot-plan.schema.json",
    "manifest": SCHEMA_ROOT / "artifact-manifest.schema.json",
    "qa": SCHEMA_ROOT / "qa-report.schema.json",
}


@dataclass(frozen=True)
class RuntimeIssue:
    severity: str
    code: str
    message: str
    path: str | None = None

    def as_dict(self) -> dict[str, str]:
        result = {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }
        if self.path is not None:
            result["path"] = self.path
        return result


class RuntimeContractError(RuntimeError):
    """Raised when a runtime file cannot be read or written safely."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeContractError(f"JSON file does not exist: {path}") from exc
    except UnicodeDecodeError as exc:
        raise RuntimeContractError(f"JSON file is not valid UTF-8: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeContractError(
            f"Invalid JSON in {path} at line {exc.lineno}, column {exc.colno}: "
            f"{exc.msg}"
        ) from exc
    except OSError as exc:
        raise RuntimeContractError(f"Could not read JSON file {path}: {exc}") from exc


def write_json_atomic(path: Path, value: Any, *, overwrite: bool = False) -> None:
    path = path.resolve()
    if path.exists() and not overwrite:
        raise RuntimeContractError(f"Refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, path)
    except OSError as exc:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass
        raise RuntimeContractError(f"Could not write JSON file {path}: {exc}") from exc


def _json_path(parent: str, token: str | int) -> str:
    if isinstance(token, int):
        return f"{parent}[{token}]"
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", token):
        return f"{parent}.{token}"
    return f"{parent}[{json.dumps(token)}]"


def _resolve_local_ref(root_schema: Mapping[str, Any], ref: str) -> Mapping[str, Any]:
    if not ref.startswith("#/"):
        raise RuntimeContractError(f"Only local schema references are supported: {ref}")
    node: Any = root_schema
    for raw_token in ref[2:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, Mapping) or token not in node:
            raise RuntimeContractError(f"Unresolvable schema reference: {ref}")
        node = node[token]
    if not isinstance(node, Mapping):
        raise RuntimeContractError(f"Schema reference does not identify an object: {ref}")
    return node


def _matches_type(instance: Any, expected: str) -> bool:
    if expected == "null":
        return instance is None
    if expected == "boolean":
        return isinstance(instance, bool)
    if expected == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if expected == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    if expected == "string":
        return isinstance(instance, str)
    if expected == "array":
        return isinstance(instance, list)
    if expected == "object":
        return isinstance(instance, dict)
    return False


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def validate_schema_instance(
    instance: Any,
    schema: Mapping[str, Any],
) -> list[RuntimeIssue]:
    """Validate the JSON Schema subset used by bundled sidecar contracts."""

    issues: list[RuntimeIssue] = []

    def add(code: str, message: str, path: str) -> None:
        issues.append(RuntimeIssue("ERROR", code, message, path))

    def visit(value: Any, rule: Mapping[str, Any], path: str) -> None:
        if "$ref" in rule:
            try:
                target = _resolve_local_ref(schema, str(rule["$ref"]))
            except RuntimeContractError as exc:
                add("schema.ref", str(exc), path)
                return
            visit(value, target, path)
            remaining = {key: item for key, item in rule.items() if key != "$ref"}
            if remaining:
                visit(value, remaining, path)
            return

        for subrule in rule.get("allOf", []):
            if isinstance(subrule, Mapping):
                visit(value, subrule, path)

        if "const" in rule and value != rule["const"]:
            add(
                "schema.const",
                f"Expected constant {rule['const']!r}; found {value!r}.",
                path,
            )
        if "enum" in rule and value not in rule["enum"]:
            add(
                "schema.enum",
                f"Expected one of {rule['enum']!r}; found {value!r}.",
                path,
            )

        expected = rule.get("type")
        if expected is not None:
            expected_types = [expected] if isinstance(expected, str) else list(expected)
            if not any(_matches_type(value, item) for item in expected_types):
                add(
                    "schema.type",
                    f"Expected type {expected_types!r}; found {_type_name(value)!r}.",
                    path,
                )
                return

        if isinstance(value, str):
            minimum = rule.get("minLength")
            if isinstance(minimum, int) and len(value) < minimum:
                add("schema.min_length", f"String is shorter than {minimum}.", path)
            pattern = rule.get("pattern")
            if isinstance(pattern, str) and re.search(pattern, value) is None:
                add("schema.pattern", f"Value does not match {pattern!r}.", path)
            if rule.get("format") == "date-time":
                try:
                    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        raise ValueError("timezone is required")
                except ValueError:
                    add("schema.format", "Expected an RFC 3339 date-time.", path)

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            minimum = rule.get("minimum")
            if isinstance(minimum, (int, float)) and value < minimum:
                add("schema.minimum", f"Value must be at least {minimum}.", path)
            exclusive = rule.get("exclusiveMinimum")
            if isinstance(exclusive, (int, float)) and value <= exclusive:
                add(
                    "schema.exclusive_minimum",
                    f"Value must be greater than {exclusive}.",
                    path,
                )

        if isinstance(value, list):
            minimum = rule.get("minItems")
            maximum = rule.get("maxItems")
            if isinstance(minimum, int) and len(value) < minimum:
                add("schema.min_items", f"Array needs at least {minimum} items.", path)
            if isinstance(maximum, int) and len(value) > maximum:
                add("schema.max_items", f"Array allows at most {maximum} items.", path)
            if rule.get("uniqueItems"):
                serialized = [json.dumps(item, sort_keys=True) for item in value]
                if len(serialized) != len(set(serialized)):
                    add("schema.unique_items", "Array items must be unique.", path)
            prefix_items = rule.get("prefixItems", [])
            if isinstance(prefix_items, list):
                for index, subrule in enumerate(prefix_items):
                    if index < len(value) and isinstance(subrule, Mapping):
                        visit(value[index], subrule, _json_path(path, index))
            item_rule = rule.get("items")
            if isinstance(item_rule, Mapping):
                for index, item in enumerate(value):
                    visit(item, item_rule, _json_path(path, index))

        if isinstance(value, dict):
            required = rule.get("required", [])
            for key in required:
                if key not in value:
                    add(
                        "schema.required",
                        f"Missing required property {key!r}.",
                        _json_path(path, key),
                    )
            properties = rule.get("properties", {})
            if isinstance(properties, Mapping):
                for key, subrule in properties.items():
                    if key in value and isinstance(subrule, Mapping):
                        visit(value[key], subrule, _json_path(path, key))
                if rule.get("additionalProperties") is False:
                    for key in value:
                        if key not in properties:
                            add(
                                "schema.additional_property",
                                f"Unexpected property {key!r}.",
                                _json_path(path, key),
                            )
                additional = rule.get("additionalProperties")
                if isinstance(additional, Mapping):
                    for key in value:
                        if key not in properties:
                            visit(value[key], additional, _json_path(path, key))
            minimum_properties = rule.get("minProperties")
            if isinstance(minimum_properties, int) and len(value) < minimum_properties:
                add(
                    "schema.min_properties",
                    f"Object needs at least {minimum_properties} properties.",
                    path,
                )

    visit(instance, schema, "$")
    return issues


def _duplicate_values(values: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def validate_render_plan_contract(plan: Any) -> list[RuntimeIssue]:
    schema = read_json(SCHEMA_FILES["render-plan"])
    issues = validate_schema_instance(plan, schema)
    if not isinstance(plan, dict):
        return issues

    elements = plan.get("elements")
    connectors = plan.get("connectors")
    assertions = plan.get("semantic_assertions")
    coverage = plan.get("spec_coverage")
    if not isinstance(elements, list) or not isinstance(connectors, list):
        return issues

    element_ids = [item.get("id") for item in elements if isinstance(item, dict)]
    connector_ids = [item.get("id") for item in connectors if isinstance(item, dict)]
    string_element_ids = [item for item in element_ids if isinstance(item, str)]
    all_ids = string_element_ids + [item for item in connector_ids if isinstance(item, str)]
    for duplicate in sorted(_duplicate_values(all_ids)):
        issues.append(
            RuntimeIssue(
                "ERROR",
                "plan.id_duplicate",
                f"RenderPlan ID is not unique: {duplicate}",
                "$.elements/$.connectors",
            )
        )

    known_elements = set(string_element_ids)
    known_connectors = {
        item for item in connector_ids if isinstance(item, str)
    }
    element_by_id = {
        item.get("id"): item
        for item in elements
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    for index, connector in enumerate(connectors):
        if not isinstance(connector, dict):
            continue
        for endpoint in ("source", "target"):
            value = connector.get(endpoint)
            if isinstance(value, str) and value not in known_elements:
                issues.append(
                    RuntimeIssue(
                        "ERROR",
                        "plan.connector.endpoint_missing",
                        f"Connector {connector.get('id')!r} references missing "
                        f"{endpoint} element {value!r}.",
                        f"$.connectors[{index}].{endpoint}",
                    )
                )

    for index, element in enumerate(elements):
        if not isinstance(element, dict):
            continue
        parent = element.get("parent_id")
        if isinstance(parent, str) and parent not in known_elements:
            issues.append(
                RuntimeIssue(
                    "ERROR",
                    "plan.element.parent_missing",
                    f"Element {element.get('id')!r} references missing parent {parent!r}.",
                    f"$.elements[{index}].parent_id",
                )
            )
        elif isinstance(parent, str):
            parent_element = element_by_id.get(parent)
            if isinstance(parent_element, dict) and parent_element.get("kind") != "container":
                issues.append(
                    RuntimeIssue(
                        "ERROR",
                        "plan.element.parent_not_container",
                        f"Element {element.get('id')!r} parent {parent!r} is not a container.",
                        f"$.elements[{index}].parent_id",
                    )
                )
            child_geometry = element.get("geometry")
            parent_geometry = (
                parent_element.get("geometry") if isinstance(parent_element, dict) else None
            )
            if isinstance(child_geometry, dict) and isinstance(parent_geometry, dict):
                try:
                    child_inside = (
                        float(child_geometry["x"]) >= 0
                        and float(child_geometry["y"]) >= 0
                        and float(child_geometry["x"]) + float(child_geometry["width"])
                        <= float(parent_geometry["width"])
                        and float(child_geometry["y"]) + float(child_geometry["height"])
                        <= float(parent_geometry["height"])
                    )
                except (KeyError, TypeError, ValueError):
                    child_inside = True
                if not child_inside:
                    issues.append(
                        RuntimeIssue(
                            "ERROR",
                            "plan.element.child_out_of_parent",
                            f"Element {element.get('id')!r} geometry is not contained by parent {parent!r}.",
                            f"$.elements[{index}].geometry",
                        )
                    )

    for element_id in string_element_ids:
        seen: set[str] = set()
        current = element_id
        while current in element_by_id:
            if current in seen:
                issues.append(
                    RuntimeIssue(
                        "ERROR",
                        "plan.element.parent_cycle",
                        f"Element parent hierarchy contains a cycle at {current!r}.",
                        "$.elements",
                    )
                )
                break
            seen.add(current)
            parent = element_by_id[current].get("parent_id")
            if not isinstance(parent, str):
                break
            current = parent

    known_assertions: set[str] = set()
    if isinstance(assertions, list):
        assertion_ids = [
            item.get("id") for item in assertions if isinstance(item, dict)
        ]
        known_assertions = {
            item for item in assertion_ids if isinstance(item, str)
        }
        for duplicate in sorted(
            _duplicate_values(item for item in assertion_ids if isinstance(item, str))
        ):
            issues.append(
                RuntimeIssue(
                    "ERROR",
                    "plan.assertion.id_duplicate",
                    f"Semantic assertion ID is not unique: {duplicate}",
                    "$.semantic_assertions",
                )
            )

    if isinstance(coverage, dict):
        must_show = coverage.get("must_show")
        relationships = coverage.get("relationships")
        if isinstance(must_show, list) and isinstance(relationships, list):
            all_items = [*must_show, *relationships]
            coverage_ids = [
                item.get("id") for item in all_items if isinstance(item, dict)
            ]
            for duplicate in sorted(
                _duplicate_values(item for item in coverage_ids if isinstance(item, str))
            ):
                issues.append(
                    RuntimeIssue(
                        "ERROR",
                        "plan.coverage.id_duplicate",
                        f"Coverage item ID is not unique: {duplicate}",
                        "$.spec_coverage",
                    )
                )

            expected_summary = {
                "must_show_total": len(must_show),
                "must_show_mapped": sum(
                    isinstance(item, dict) and item.get("status") == "MAPPED"
                    for item in must_show
                ),
                "relationships_total": len(relationships),
                "relationships_mapped": sum(
                    isinstance(item, dict) and item.get("status") == "MAPPED"
                    for item in relationships
                ),
            }
            expected_summary["unresolved_total"] = (
                expected_summary["must_show_total"]
                - expected_summary["must_show_mapped"]
                + expected_summary["relationships_total"]
                - expected_summary["relationships_mapped"]
            )
            if coverage.get("summary") != expected_summary:
                issues.append(
                    RuntimeIssue(
                        "ERROR",
                        "plan.coverage.summary_mismatch",
                        "Coverage summary does not match the recorded requirement statuses.",
                        "$.spec_coverage.summary",
                    )
                )
            expected_status = (
                "COMPLETE" if expected_summary["unresolved_total"] == 0 else "BLOCKED"
            )
            if coverage.get("status") != expected_status:
                issues.append(
                    RuntimeIssue(
                        "ERROR",
                        "plan.coverage.status_mismatch",
                        f"Coverage status must be {expected_status!r} for the recorded summary.",
                        "$.spec_coverage.status",
                    )
                )

            for item_index, item in enumerate(all_items):
                if not isinstance(item, dict):
                    continue
                base_path = f"$.spec_coverage.items[{item_index}]"
                representations = item.get("representations")
                if item.get("status") == "MAPPED" and representations == []:
                    issues.append(
                        RuntimeIssue(
                            "ERROR",
                            "plan.coverage.representation_missing",
                            f"Mapped coverage item {item.get('id')!r} has no representation.",
                            f"{base_path}.representations",
                        )
                    )
                if item.get("status") == "UNRESOLVED" and not item.get("reason"):
                    issues.append(
                        RuntimeIssue(
                            "ERROR",
                            "plan.coverage.unresolved_reason_missing",
                            f"Unresolved coverage item {item.get('id')!r} needs a reason.",
                            f"{base_path}.reason",
                        )
                    )
                if not isinstance(representations, list):
                    continue
                for ref_index, reference in enumerate(representations):
                    if not isinstance(reference, dict):
                        continue
                    kind = reference.get("kind")
                    ids = reference.get("ids")
                    if not isinstance(ids, list):
                        continue
                    valid = False
                    if kind == "element" and len(ids) == 1:
                        valid = ids[0] in known_elements
                    elif kind == "connector" and len(ids) == 1:
                        valid = ids[0] in known_connectors
                    elif kind == "assertion" and len(ids) == 1:
                        valid = ids[0] in known_assertions
                    elif kind == "parent_child" and len(ids) == 2:
                        parent, child = ids
                        valid = (
                            parent in known_elements
                            and child in known_elements
                            and element_by_id.get(child, {}).get("parent_id") == parent
                        )
                    if not valid:
                        issues.append(
                            RuntimeIssue(
                                "ERROR",
                                "plan.coverage.representation_missing",
                                f"Coverage reference {kind!r} {ids!r} does not resolve in the RenderPlan.",
                                f"{base_path}.representations[{ref_index}]",
                            )
                        )

    backend = plan.get("backend")
    registry = load_capability_registry()
    if isinstance(backend, str) and backend not in registry.get("backends", {}):
        issues.append(
            RuntimeIssue(
                "ERROR",
                "plan.backend.unsupported",
                f"Backend is not registered: {backend}",
                "$.backend",
            )
        )

    outputs = plan.get("outputs")
    if backend == "drawio" and isinstance(outputs, dict):
        source = outputs.get("source")
        if isinstance(source, str) and not source.lower().endswith(".drawio"):
            issues.append(
                RuntimeIssue(
                    "ERROR",
                    "plan.output.source_extension",
                    "Draw.io source output must use the .drawio extension.",
                    "$.outputs.source",
                )
            )
    if backend == "svg" and isinstance(outputs, dict):
        source = outputs.get("source")
        if isinstance(source, str) and not source.lower().endswith(".svg"):
            issues.append(
                RuntimeIssue(
                    "ERROR",
                    "plan.output.source_extension",
                    "Native SVG source output must use the .svg extension.",
                    "$.outputs.source",
                )
            )
    return issues


def validate_plot_plan_contract(plan: Any) -> list[RuntimeIssue]:
    """Validate PlotPlan 1.0 without treating it as a diagram RenderPlan."""

    schema = read_json(SCHEMA_FILES["plot-plan"])
    issues = validate_schema_instance(plan, schema)
    if not isinstance(plan, dict):
        return issues

    def add(code: str, message: str, path: str, severity: str = "ERROR") -> None:
        issues.append(RuntimeIssue(severity, code, message, path))

    figure_id = plan.get("figure_id")
    figure_spec = plan.get("figure_spec")
    if isinstance(figure_spec, dict) and figure_spec.get("figure_id") != figure_id:
        add(
            "plot.plan.figure_id_mismatch",
            "PlotPlan figure_id must match figure_spec.figure_id.",
            "$.figure_id",
        )

    data_sources = plan.get("data_sources")
    source_ids = [
        item.get("id")
        for item in data_sources
        if isinstance(data_sources, list) and isinstance(item, dict)
    ] if isinstance(data_sources, list) else []
    string_source_ids = [item for item in source_ids if isinstance(item, str)]
    for duplicate in sorted(_duplicate_values(string_source_ids)):
        add(
            "plot.data.id_duplicate",
            f"Data source ID is not unique: {duplicate}",
            "$.data_sources",
        )
    known_sources = set(string_source_ids)

    layout = plan.get("layout")
    rows = layout.get("rows") if isinstance(layout, dict) else None
    columns = layout.get("columns") if isinstance(layout, dict) else None
    panels = plan.get("panels")
    if not isinstance(panels, list):
        return issues

    panel_ids = [item.get("id") for item in panels if isinstance(item, dict)]
    string_panel_ids = [item for item in panel_ids if isinstance(item, str)]
    for duplicate in sorted(_duplicate_values(string_panel_ids)):
        add("plot.panel.id_duplicate", f"Panel ID is not unique: {duplicate}", "$.panels")
    known_panels = set(string_panel_ids)
    known_series: set[str] = set()
    known_axes: set[str] = set()
    known_legends: set[str] = set()
    known_annotations: set[str] = set()
    known_reference_lines: set[str] = set()
    design_reference_lines: set[str] = set()
    known_bindings: set[str] = set(known_sources)

    required_encodings = {
        "line": {"x", "y"},
        "scatter": {"x", "y"},
        "bar": {"category", "value"},
        "heatmap": {"x", "y", "value"},
    }
    allowed_encodings = {
        "line": {"x", "y", "group"},
        "scatter": {"x", "y", "group", "size"},
        "bar": {"category", "value", "group"},
        "heatmap": {"x", "y", "value"},
    }
    figure_legend_panels: set[str] = set()
    for index, panel in enumerate(panels):
        if not isinstance(panel, dict):
            continue
        path = f"$.panels[{index}]"
        panel_id = panel.get("id")
        source_id = panel.get("data_source")
        if isinstance(source_id, str) and source_id not in known_sources:
            add(
                "plot.panel.data_source_missing",
                f"Panel {panel_id!r} references unknown data source {source_id!r}.",
                f"{path}.data_source",
            )
        if isinstance(panel_id, str):
            known_axes.update({f"{panel_id}:x", f"{panel_id}:y"})

        grid = panel.get("grid")
        if isinstance(grid, dict) and isinstance(rows, int) and isinstance(columns, int):
            row = grid.get("row")
            column = grid.get("column")
            rowspan = grid.get("rowspan", 1)
            colspan = grid.get("colspan", 1)
            if (
                isinstance(row, int)
                and isinstance(column, int)
                and isinstance(rowspan, int)
                and isinstance(colspan, int)
                and (row + rowspan > rows or column + colspan > columns)
            ):
                add(
                    "plot.panel.grid_out_of_bounds",
                    f"Panel {panel_id!r} exceeds the declared layout grid.",
                    f"{path}.grid",
                )

        plot_type = panel.get("plot_type")
        encoding = panel.get("encoding")
        if isinstance(plot_type, str) and isinstance(encoding, dict):
            missing = required_encodings.get(plot_type, set()) - set(encoding)
            if missing:
                add(
                    "plot.panel.encoding_missing",
                    f"{plot_type} panel {panel_id!r} is missing encodings: {sorted(missing)}.",
                    f"{path}.encoding",
                )
            unsupported = set(encoding) - allowed_encodings.get(plot_type, set())
            if unsupported:
                add(
                    "plot.panel.encoding_unsupported",
                    f"{plot_type} panel {panel_id!r} has unsupported encodings: {sorted(unsupported)}.",
                    f"{path}.encoding",
                )

        series = panel.get("series")
        if plot_type != "heatmap" and isinstance(series, list) and not series:
            add(
                "plot.series.missing",
                f"Panel {panel_id!r} needs at least one explicit series.",
                f"{path}.series",
            )
        if plot_type == "heatmap" and isinstance(series, list) and series:
            add(
                "plot.series.heatmap_unsupported",
                "Heatmap cells come directly from x/y/value bindings; series entries are not supported.",
                f"{path}.series",
            )
        local_series_ids = [
            item.get("id") for item in series if isinstance(series, list) and isinstance(item, dict)
        ] if isinstance(series, list) else []
        for duplicate in sorted(
            _duplicate_values(item for item in local_series_ids if isinstance(item, str))
        ):
            add(
                "plot.series.id_duplicate",
                f"Series ID is not unique within panel {panel_id!r}: {duplicate}",
                f"{path}.series",
            )
        local_series_labels = [
            item.get("label")
            for item in series
            if isinstance(series, list) and isinstance(item, dict)
        ] if isinstance(series, list) else []
        for duplicate in sorted(
            _duplicate_values(item for item in local_series_labels if isinstance(item, str))
        ):
            add(
                "plot.series.label_duplicate",
                f"Series label is not unique within panel {panel_id!r}: {duplicate}",
                f"{path}.series",
            )
        for series_index, item in enumerate(series if isinstance(series, list) else []):
            if not isinstance(item, dict):
                continue
            series_id = item.get("id")
            if isinstance(series_id, str) and isinstance(panel_id, str):
                qualified = f"{panel_id}:{series_id}"
                if qualified in known_series:
                    add(
                        "plot.series.id_duplicate",
                        f"Qualified series ID is not unique: {qualified}",
                        f"{path}.series[{series_index}].id",
                    )
                known_series.add(qualified)
            series_source = item.get("data_source", source_id)
            if isinstance(series_source, str) and series_source not in known_sources:
                add(
                    "plot.series.data_source_missing",
                    f"Series {series_id!r} references unknown data source {series_source!r}.",
                    f"{path}.series[{series_index}].data_source",
                )

        missing_policy = panel.get("missing_policy")
        if missing_policy == "gap" and plot_type != "line":
            add(
                "plot.panel.gap_unsupported",
                "missing_policy='gap' is supported only for line plots in PlotPlan 1.0.",
                f"{path}.missing_policy",
            )

        uncertainty = panel.get("uncertainty")
        if isinstance(uncertainty, dict):
            if plot_type not in {"line", "bar"}:
                add(
                    "plot.uncertainty.plot_type_unsupported",
                    "Precomputed uncertainty is supported only for line and bar plots in PlotPlan 1.0.",
                    f"{path}.uncertainty",
                )
            pair = "lower_column" in uncertainty or "upper_column" in uncertainty
            symmetric = "symmetric_column" in uncertainty
            if pair and not {"lower_column", "upper_column"}.issubset(uncertainty):
                add(
                    "plot.uncertainty.bounds_incomplete",
                    "Uncertainty bounds require both lower_column and upper_column.",
                    f"{path}.uncertainty",
                )
            if pair == symmetric:
                add(
                    "plot.uncertainty.encoding_invalid",
                    "Declare either lower/upper bounds or one symmetric uncertainty column.",
                    f"{path}.uncertainty",
                )

        category_order = panel.get("category_order")
        if isinstance(category_order, list) and len(category_order) != len(
            {str(item) for item in category_order}
        ):
            add(
                "plot.panel.category_order_duplicate",
                "category_order must not contain duplicate categories.",
                f"{path}.category_order",
            )

        legend = panel.get("legend")
        legend_mode = legend.get("mode") if isinstance(legend, dict) else None
        if isinstance(panel_id, str) and legend_mode in {"panel", "figure"}:
            known_legends.add(panel_id)
        if legend_mode == "figure" and isinstance(panel_id, str):
            figure_legend_panels.add(panel_id)
            if not isinstance(layout, dict) or layout.get("shared_legend") is not True:
                add(
                    "plot.legend.shared_disabled",
                    f"Panel {panel_id!r} requests a figure legend but layout.shared_legend is false.",
                    f"{path}.legend.mode",
                )
        if legend_mode == "none" and isinstance(series, list) and len(series) > 1:
            add(
                "plot.legend.series_unlabeled",
                f"Panel {panel_id!r} has multiple series but no supported legend or direct-label contract.",
                f"{path}.legend.mode",
            )

        axes = panel.get("axes")
        if isinstance(axes, dict):
            for axis_name in ("x", "y"):
                axis = axes.get(axis_name)
                if not isinstance(axis, dict):
                    continue
                limits = axis.get("limits")
                if (
                    isinstance(limits, list)
                    and len(limits) == 2
                    and all(isinstance(value, (int, float)) for value in limits)
                    and limits[0] >= limits[1]
                ):
                    add(
                        "plot.axis.limits_invalid",
                        f"Panel {panel_id!r} {axis_name}-axis limits must increase.",
                        f"{path}.axes.{axis_name}.limits",
                    )
                if axis.get("allow_clipping") is True and not axis.get("rationale"):
                    add(
                        "plot.axis.clipping_rationale_missing",
                        "allow_clipping=true requires a rationale.",
                        f"{path}.axes.{axis_name}",
                    )
                if plot_type == "heatmap" and axis.get("scale") != "linear":
                    add(
                        "plot.axis.categorical_log_unsupported",
                        "Heatmap category axes must use linear positioning in PlotPlan 1.0.",
                        f"{path}.axes.{axis_name}.scale",
                    )
                if plot_type == "bar" and axis_name == "x" and axis.get("scale") != "linear":
                    add(
                        "plot.axis.categorical_log_unsupported",
                        "Bar category axes must use linear positioning in PlotPlan 1.0.",
                        f"{path}.axes.{axis_name}.scale",
                    )
                if plot_type == "bar" and axis_name == "y" and axis.get("scale") == "log":
                    add(
                        "plot.axis.bar_log_unsupported",
                        "Log-scaled bar axes are unsupported because the PlotPlan 1.0 bar contract uses a zero baseline.",
                        f"{path}.axes.{axis_name}.scale",
                    )
            y_axis = axes.get("y")
            if plot_type == "bar" and isinstance(y_axis, dict):
                limits = y_axis.get("limits")
                nonzero = isinstance(limits, list) and len(limits) == 2 and limits[0] != 0
                if nonzero and panel.get("allow_nonzero_baseline") is not True:
                    add(
                        "plot.axis.nonzero_bar_baseline",
                        "Bar plots require a zero baseline unless explicitly allowed with a rationale.",
                        f"{path}.axes.y.limits",
                    )
                elif nonzero and not panel.get("nonzero_baseline_rationale"):
                    add(
                        "plot.axis.nonzero_bar_baseline_rationale_missing",
                        "A non-zero bar baseline requires nonzero_baseline_rationale.",
                        path,
                    )
                elif nonzero:
                    add(
                        "plot.axis.nonzero_bar_baseline",
                        "The PlotPlan explicitly uses a non-zero bar baseline.",
                        f"{path}.axes.y.limits",
                        severity="WARNING",
                    )

        color_scale = panel.get("color_scale")
        if plot_type == "heatmap":
            if not isinstance(color_scale, dict):
                add(
                    "plot.style.color_scale_missing",
                    "Heatmap panels require an explicit color_scale.",
                    f"{path}.color_scale",
                )
            elif color_scale.get("kind") == "diverging" and "center" not in color_scale:
                add(
                    "plot.style.diverging_center_missing",
                    "A diverging heatmap color scale requires an explicit center.",
                    f"{path}.color_scale.center",
                )
            if isinstance(color_scale, dict) and not color_scale.get("label"):
                add(
                    "plot.style.colorbar_label_missing",
                    "Heatmap color scale requires an explicit value label.",
                    f"{path}.color_scale.label",
                )

        annotations = panel.get("annotations")
        for annotation_index, annotation in enumerate(
            annotations if isinstance(annotations, list) else []
        ):
            if not isinstance(annotation, dict):
                continue
            annotation_id = annotation.get("id")
            if isinstance(annotation_id, str):
                if annotation_id in known_annotations:
                    add(
                        "plot.annotation.id_duplicate",
                        f"Annotation ID is not unique: {annotation_id}",
                        f"{path}.annotations[{annotation_index}].id",
                    )
                known_annotations.add(annotation_id)
            source = annotation.get("source")
            if isinstance(source, dict) and source.get("type") in {
                "data_column",
                "source_bound_constant",
            }:
                if not source.get("data_source") or not source.get("column"):
                    add(
                        "scientific.data.unbound_value",
                        f"Annotation {annotation_id!r} lacks a complete authoritative data binding.",
                        f"{path}.annotations[{annotation_index}].source",
                    )

        reference_lines = panel.get("reference_lines")
        for reference_index, reference in enumerate(
            reference_lines if isinstance(reference_lines, list) else []
        ):
            if not isinstance(reference, dict):
                continue
            reference_id = reference.get("id")
            if isinstance(reference_id, str):
                if reference_id in known_reference_lines:
                    add(
                        "plot.reference_line.id_duplicate",
                        f"Reference-line ID is not unique: {reference_id}",
                        f"{path}.reference_lines[{reference_index}].id",
                    )
                known_reference_lines.add(reference_id)
            if reference.get("source_type") == "source_bound_constant":
                source = reference.get("source")
                if not isinstance(source, dict) or not source.get("data_source") or not source.get("column"):
                    add(
                        "scientific.data.unbound_value",
                        f"Reference line {reference_id!r} lacks a complete source binding.",
                        f"{path}.reference_lines[{reference_index}]",
                    )
            elif (
                reference.get("source_type") == "design_reference"
                and isinstance(reference_id, str)
            ):
                design_reference_lines.add(reference_id)

    if isinstance(layout, dict) and layout.get("shared_legend") is True and not figure_legend_panels:
        add(
            "plot.legend.shared_unused",
            "layout.shared_legend is true but no panel declares legend.mode='figure'.",
            "$.layout.shared_legend",
        )

    outputs = plan.get("outputs")
    if isinstance(outputs, dict):
        for key in ("source", "manifest", "qa_report", "trace"):
            value = outputs.get(key)
            if not isinstance(value, str):
                continue
            path = Path(value)
            if path.is_absolute() or ".." in path.parts or path.parent != Path("."):
                add(
                    "plot.output.path_unsafe",
                    f"PlotPlan output {key!r} must be a file name resolved inside the selected work directory.",
                    f"$.outputs.{key}",
                )

    coverage = plan.get("spec_coverage")
    covered_design_references: set[str] = set()
    if isinstance(coverage, dict):
        section_names = ("must_show", "relationships", "required_labels", "must_not_imply")
        summary: dict[str, int] = {}
        all_items: list[tuple[str, int, dict[str, Any]]] = []
        for section in section_names:
            items = coverage.get(section)
            items = items if isinstance(items, list) else []
            mapped = sum(isinstance(item, dict) and item.get("status") == "MAPPED" for item in items)
            summary[f"{section}_total"] = len(items)
            summary[f"{section}_mapped"] = mapped
            all_items.extend(
                (section, item_index, item)
                for item_index, item in enumerate(items)
                if isinstance(item, dict)
            )
        summary["unresolved_total"] = sum(
            summary[f"{section}_total"] - summary[f"{section}_mapped"]
            for section in section_names
        )
        if coverage.get("summary") != summary:
            add(
                "plot.plan.coverage_summary_mismatch",
                "PlotPlan coverage summary does not match requirement statuses.",
                "$.spec_coverage.summary",
            )
        expected_status = "COMPLETE" if summary["unresolved_total"] == 0 else "BLOCKED"
        if coverage.get("status") != expected_status:
            add(
                "plot.plan.coverage_status_mismatch",
                f"PlotPlan coverage status must be {expected_status!r}.",
                "$.spec_coverage.status",
            )

        for section, item_index, item in all_items:
            item_path = f"$.spec_coverage.{section}[{item_index}]"
            representations = item.get("representations")
            if item.get("status") == "MAPPED" and representations == []:
                add(
                    "plot.plan.coverage_representation_missing",
                    f"Mapped coverage item {item.get('id')!r} has no representation.",
                    f"{item_path}.representations",
                )
            if item.get("status") == "UNRESOLVED" and not item.get("reason"):
                add(
                    "plot.plan.coverage_reason_missing",
                    f"Unresolved coverage item {item.get('id')!r} needs a reason.",
                    f"{item_path}.reason",
                )
            for ref_index, reference in enumerate(
                representations if isinstance(representations, list) else []
            ):
                if not isinstance(reference, dict):
                    continue
                kind = reference.get("kind")
                ids = reference.get("ids")
                valid = False
                if isinstance(ids, list):
                    if kind == "panel" and len(ids) == 1:
                        valid = ids[0] in known_panels
                    elif kind == "series" and len(ids) == 2:
                        valid = f"{ids[0]}:{ids[1]}" in known_series
                    elif kind == "axis" and len(ids) == 2:
                        valid = f"{ids[0]}:{ids[1]}" in known_axes
                    elif kind == "legend" and len(ids) == 1:
                        valid = ids[0] in known_legends
                    elif kind == "annotation" and len(ids) == 1:
                        valid = ids[0] in known_annotations
                    elif kind == "reference_line" and len(ids) == 1:
                        valid = ids[0] in known_reference_lines
                    elif kind == "data_binding" and len(ids) == 1:
                        valid = ids[0] in known_bindings
                if not valid:
                    add(
                        "plot.plan.coverage_representation_missing",
                        f"Coverage reference {kind!r} {ids!r} does not resolve in the PlotPlan.",
                        f"{item_path}.representations[{ref_index}]",
                    )
                elif (
                    item.get("status") == "MAPPED"
                    and kind == "reference_line"
                    and isinstance(ids, list)
                    and len(ids) == 1
                    and ids[0] in design_reference_lines
                ):
                    covered_design_references.add(ids[0])

    for reference_id in sorted(design_reference_lines - covered_design_references):
        add(
            "scientific.data.unbound_value",
            f"Design reference line {reference_id!r} is not mapped to a FigureSpec requirement.",
            "$.spec_coverage",
        )

    return issues


def validate_manifest_contract(manifest: Any) -> list[RuntimeIssue]:
    schema = read_json(SCHEMA_FILES["manifest"])
    issues = validate_schema_instance(manifest, schema)
    if not isinstance(manifest, dict):
        return issues
    artifacts = manifest.get("artifacts")
    status = manifest.get("status")
    if status == "COMPLETED" and isinstance(artifacts, list) and not artifacts:
        issues.append(
            RuntimeIssue(
                "ERROR",
                "manifest.completed_without_artifacts",
                "A COMPLETED export manifest must record at least one artifact.",
                "$.artifacts",
            )
        )
    if isinstance(artifacts, list):
        paths = [item.get("path") for item in artifacts if isinstance(item, dict)]
        for duplicate in sorted(
            _duplicate_values(item for item in paths if isinstance(item, str))
        ):
            issues.append(
                RuntimeIssue(
                    "ERROR",
                    "manifest.artifact.path_duplicate",
                    f"Artifact path is recorded more than once: {duplicate}",
                    "$.artifacts",
                )
            )
    return issues


def validate_qa_contract(report: Any) -> list[RuntimeIssue]:
    schema = read_json(SCHEMA_FILES["qa"])
    issues = validate_schema_instance(report, schema)
    if not isinstance(report, dict):
        return issues
    qa_issues = report.get("issues")
    summary = report.get("summary")
    if not isinstance(qa_issues, list) or not isinstance(summary, dict):
        return issues
    expected = {"blocking": 0, "major": 0, "minor": 0}
    for item in qa_issues:
        if isinstance(item, dict):
            severity = item.get("severity")
            if isinstance(severity, str) and severity.lower() in expected:
                expected[severity.lower()] += 1
    if summary != expected:
        issues.append(
            RuntimeIssue(
                "ERROR",
                "qa.summary.mismatch",
                f"QA summary {summary!r} does not match issue counts {expected!r}.",
                "$.summary",
            )
        )
    expected_outcome = (
        "BLOCKED"
        if expected["blocking"]
        else "REVISION_REQUIRED"
        if expected["major"] or expected["minor"]
        else "AUTOMATED_CHECKS_PASSED"
    )
    if report.get("outcome") != expected_outcome:
        issues.append(
            RuntimeIssue(
                "ERROR",
                "qa.outcome.mismatch",
                f"Expected outcome {expected_outcome!r} from issue severities.",
                "$.outcome",
            )
        )
    return issues


def validate_sidecar(kind: str, value: Any) -> list[RuntimeIssue]:
    if kind == "render-plan":
        return validate_render_plan_contract(value)
    if kind == "plot-plan":
        return validate_plot_plan_contract(value)
    if kind == "manifest":
        return validate_manifest_contract(value)
    if kind == "qa":
        return validate_qa_contract(value)
    raise RuntimeContractError(f"Unknown sidecar kind: {kind}")


def load_capability_registry() -> dict[str, Any]:
    registry = read_json(CAPABILITY_REGISTRY_PATH)
    if not isinstance(registry, dict):
        raise RuntimeContractError("Capability registry must be a JSON object.")
    return registry


def package_version() -> str:
    """Return the package release from the canonical capability registry."""

    value = load_capability_registry().get("package_version")
    if not isinstance(value, str) or not value.strip():
        raise RuntimeContractError(
            "Capability registry package_version must be a non-empty string."
        )
    return value


def _candidate_command(value: str) -> list[str] | None:
    parts = shlex.split(value)
    if not parts:
        return None
    executable = parts[0]
    resolved = shutil.which(executable)
    if resolved is not None:
        parts[0] = resolved
        return parts
    path = Path(executable).expanduser()
    if path.is_file() and os.access(path, os.X_OK):
        parts[0] = str(path.resolve())
        return parts
    return None


def resolve_drawio_command(explicit: str | None = None) -> list[str] | None:
    registry = load_capability_registry()
    if explicit:
        return _candidate_command(explicit)
    candidates: list[str] = []
    environment = os.environ.get("DRAWIO_COMMAND")
    if environment:
        candidates.append(environment)
    export = (
        registry.get("backends", {})
        .get("drawio", {})
        .get("operations", {})
        .get("export", {})
    )
    candidates.extend(export.get("executable_candidates", []))
    for value in candidates:
        if isinstance(value, str):
            command = _candidate_command(value)
            if command is not None:
                return command
    return None


def resolve_svg_renderer_command(explicit: str | None = None) -> list[str] | None:
    """Resolve an optional SVG→PNG/PDF renderer without making it mandatory."""

    candidates = [explicit] if explicit else [
        "rsvg-convert",
        "chromium",
        "chromium-browser",
        "google-chrome",
        "cairosvg",
    ]
    for value in candidates:
        if not isinstance(value, str):
            continue
        command = _candidate_command(value)
        if command is not None:
            return command
    return None


def command_version(
    command: Sequence[str],
    *,
    capability: str = "drawio_cli",
    label: str = "Draw.io CLI",
) -> tuple[str | None, RuntimeIssue | None]:
    try:
        completed = subprocess.run(
            [*command, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, RuntimeIssue(
            "WARNING",
            f"capability.{capability}.version_unknown",
            f"Could not query {label} version: {exc}",
        )
    output = (completed.stdout or completed.stderr).strip()
    if completed.returncode != 0 or not output:
        return None, RuntimeIssue(
            "WARNING",
            f"capability.{capability}.version_unknown",
            f"{label} was found, but its version could not be confirmed.",
        )
    return output.splitlines()[0].strip(), None


def preflight(
    *,
    backend: str,
    operation: str,
    drawio_command: str | None = None,
    svg_renderer_command: str | None = None,
) -> dict[str, Any]:
    registry = load_capability_registry()
    issues: list[RuntimeIssue] = []
    backends = registry.get("backends", {})
    if backend not in backends:
        if backend in registry.get("out_of_scope", {}):
            issues.append(
                RuntimeIssue(
                    "ERROR",
                    "capability.backend.out_of_scope",
                    registry["out_of_scope"][backend],
                )
            )
        else:
            issues.append(
                RuntimeIssue(
                    "ERROR",
                    "capability.backend.unknown",
                    f"Backend is not registered: {backend}",
                )
            )
        return {
            "registry_version": registry.get("registry_version"),
            "backend": backend,
            "operation": operation,
            "ready": False,
            "drawio_cli": None,
            "svg_renderer": None,
            "matplotlib": None,
            "issues": [item.as_dict() for item in issues],
        }

    operations = backends[backend].get("operations", {})
    required_operations = (
        [
            "plan",
            "author",
            *(["data_binding"] if backend == "matplotlib" else []),
            "lint",
            "export",
            "inspect",
        ]
        if operation == "render"
        else [operation]
    )
    unknown = [item for item in required_operations if item not in operations]
    for item in unknown:
        issues.append(
            RuntimeIssue(
                "ERROR",
                "capability.operation.unknown",
                f"Operation {item!r} is not registered for backend {backend!r}.",
            )
        )
    for item in required_operations:
        if operations.get(item, {}).get("available") is False:
            issues.append(
                RuntimeIssue(
                    "ERROR",
                    "capability.operation.unavailable",
                    f"Operation {item!r} is not implemented for backend {backend!r}.",
                )
            )

    cli_info: dict[str, Any] | None = None
    needs_external = any(
        operations.get(item, {}).get("implementation") == "external_cli"
        for item in required_operations
    )
    if backend == "drawio" and needs_external:
        command = resolve_drawio_command(drawio_command)
        if command is None:
            issues.append(
                RuntimeIssue(
                    "ERROR",
                    "capability.drawio_cli.missing",
                    "Draw.io authoring is available, but export requires an installed "
                    "Draw.io desktop CLI. Set --drawio-command or DRAWIO_COMMAND.",
                )
            )
        else:
            version, version_issue = command_version(command)
            if version_issue is not None:
                issues.append(version_issue)
            cli_info = {"command": command, "version": version}

    svg_renderer_info: dict[str, Any] | None = None
    if backend == "svg":
        renderer_command = resolve_svg_renderer_command(svg_renderer_command)
        if renderer_command is not None:
            version, version_issue = command_version(
                renderer_command,
                capability="svg_renderer",
                label="SVG renderer",
            )
            if version_issue is not None:
                issues.append(version_issue)
            svg_renderer_info = {"command": renderer_command, "version": version}
        elif svg_renderer_command:
            issues.append(
                RuntimeIssue(
                    "ERROR",
                    "capability.svg_renderer.command_missing",
                    "The explicitly selected SVG renderer command could not be resolved.",
                )
            )

    matplotlib_info: dict[str, Any] | None = None
    if backend == "matplotlib" and "export" in required_operations:
        if importlib.util.find_spec("matplotlib") is None:
            issues.append(
                RuntimeIssue(
                    "ERROR",
                    "capability.matplotlib.missing",
                    "Matplotlib export is optional and is not installed in this Python environment.",
                )
            )
        else:
            try:
                version = importlib.metadata.version("matplotlib")
            except importlib.metadata.PackageNotFoundError:
                version = None
            matplotlib_info = {
                "python": sys.version.split()[0],
                "version": version,
            }

    ready = not any(item.severity == "ERROR" for item in issues)
    return {
        "registry_version": registry.get("registry_version"),
        "backend": backend,
        "operation": operation,
        "ready": ready,
        "drawio_cli": cli_info,
        "svg_renderer": svg_renderer_info,
        "matplotlib": matplotlib_info,
        "issues": [item.as_dict() for item in issues],
    }


def format_issues(issues: Iterable[RuntimeIssue]) -> str:
    lines = []
    for issue in issues:
        location = f" ({issue.path})" if issue.path else ""
        lines.append(f"[{issue.severity}] {issue.code}{location}: {issue.message}")
    return "\n".join(lines)
