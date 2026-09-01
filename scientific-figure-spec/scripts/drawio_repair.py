#!/usr/bin/env python3
"""Bounded, plan-aware repair for uncompressed Draw.io sources.

Repairs are written to a distinct output file. The command never edits the
input in place and never invents labels, cells, relationships, or geometry that
are absent from an optional validated RenderPlan.
"""

from __future__ import annotations

import copy
import os
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from drawio_backend import drawio_tree
from drawio_lint import DrawioLintReport, lint_drawio
from figure_runtime import (
    RuntimeContractError,
    read_json,
    sha256_file,
    validate_render_plan_contract,
)


class DrawioRepairError(RuntimeError):
    """Raised when a repair cannot be attempted without unsafe assumptions."""


@dataclass
class RepairResult:
    source: Path
    output: Path | None
    dry_run: bool
    source_sha256: str
    changed: bool
    safe_complete: bool
    actions: list[dict[str, str]]
    skipped: list[dict[str, str]]
    before: DrawioLintReport
    after: DrawioLintReport

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": str(self.source),
            "output": str(self.output) if self.output is not None else None,
            "dry_run": self.dry_run,
            "source_sha256": self.source_sha256,
            "changed": self.changed,
            "safe_complete": self.safe_complete,
            "actions": self.actions,
            "skipped": self.skipped,
            "before": self.before.as_dict(strict=True),
            "after": self.after.as_dict(strict=True),
        }


def _action(code: str, cell_id: str, message: str) -> dict[str, str]:
    return {"code": code, "cell_id": cell_id, "message": message}


def _set_style_token(style: str | None, key: str, value: str) -> tuple[str, bool]:
    tokens = [token for token in (style or "").split(";") if token]
    changed = False
    found = False
    result: list[str] = []
    for token in tokens:
        if "=" not in token:
            result.append(token)
            continue
        token_key, token_value = token.split("=", 1)
        if token_key == key:
            found = True
            if token_value != value:
                changed = True
            result.append(f"{key}={value}")
        else:
            result.append(token)
    if not found:
        result.append(f"{key}={value}")
        changed = True
    return ";".join(result) + ";", changed


def _plain_label(value: str | None) -> str:
    # Generated plan labels are plain text. For safety, a non-empty HTML-rich or
    # otherwise changed label is treated as a conflict rather than overwritten.
    return " ".join((value or "").split())


def _edge_matches(edge: ET.Element, source: str, target: str, directed: bool) -> bool:
    edge_directed = edge.get("data-directed")
    if edge_directed is None:
        style = edge.get("style") or ""
        edge_directed = "false" if "endArrow=none" in style else "true"
    if directed:
        return (
            edge.get("source") == source
            and edge.get("target") == target
            and edge_directed == "true"
        )
    return (
        {edge.get("source"), edge.get("target")} == {source, target}
        and edge_directed == "false"
    )


def _graph_root(document: ET.ElementTree) -> ET.Element:
    root = document.getroot()
    graph_root = root.find("./diagram/mxGraphModel/root")
    if root.tag != "mxfile" or graph_root is None:
        raise DrawioRepairError(
            "Safe repair requires uncompressed mxfile/diagram/mxGraphModel/root structure."
        )
    return graph_root


def _serialize(document: ET.ElementTree) -> bytes:
    ET.indent(document, space="  ")
    return ET.tostring(document.getroot(), encoding="utf-8", xml_declaration=True) + b"\n"


def _write_atomic(path: Path, payload: bytes, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise DrawioRepairError(f"Refusing to overwrite existing repair output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb",
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
        raise DrawioRepairError(f"Could not write repair output: {exc}") from exc


def _lint_payload(payload: bytes, directory: Path) -> DrawioLintReport:
    with tempfile.NamedTemporaryFile(
        "wb",
        dir=directory,
        prefix=".drawio-repair-lint.",
        suffix=".drawio",
        delete=False,
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    try:
        return lint_drawio(temporary)
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass


def repair_drawio(
    *,
    source_path: Path,
    output_path: Path | None,
    plan_path: Path | None = None,
    dry_run: bool = False,
    overwrite: bool = False,
) -> RepairResult:
    source_path = source_path.expanduser().resolve()
    if not source_path.is_file():
        raise DrawioRepairError(f"Draw.io source does not exist: {source_path}")
    source_hash = sha256_file(source_path)
    if output_path is not None:
        output_path = output_path.expanduser()
        if not output_path.is_absolute():
            output_path = Path.cwd() / output_path
        output_path = output_path.resolve()
        if output_path == source_path:
            raise DrawioRepairError(
                "In-place repair is forbidden; choose a distinct output path."
            )
    if not dry_run and output_path is None:
        raise DrawioRepairError("Repair requires --output unless --dry-run is used.")

    before = lint_drawio(source_path)
    fatal_codes = {
        "drawio.file.missing",
        "drawio.file.read",
        "drawio.xml.invalid",
        "drawio.xml.unsafe_doctype",
        "drawio.structure.mxfile_missing",
        "drawio.structure.diagram_missing",
        "drawio.format.compressed",
        "drawio.structure.graph_model_missing",
        "drawio.structure.root_missing",
    }
    if any(item.code in fatal_codes for item in before.issues):
        raise DrawioRepairError(
            "Source is not safely repairable as uncompressed Draw.io XML."
        )
    try:
        document = ET.parse(source_path)
    except (ET.ParseError, OSError) as exc:
        raise DrawioRepairError(f"Could not parse Draw.io source: {exc}") from exc
    graph_root = _graph_root(document)
    mxfile = document.getroot()
    actions: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []

    if mxfile.get("compressed") != "false":
        mxfile.set("compressed", "false")
        actions.append(
            _action(
                "repair.format.uncompressed_marker_added",
                "mxfile",
                "Marked the already-uncompressed XML source as compressed=false.",
            )
        )

    cells = graph_root.findall("mxCell")
    current_by_id = {
        cell.get("id"): cell for cell in cells if cell.get("id") is not None
    }

    # Two purely syntactic repairs do not need a RenderPlan.
    for cell in cells:
        cell_id = cell.get("id") or "(missing)"
        if cell.get("vertex") == "1" and _plain_label(cell.get("value")):
            style, wrap_changed = _set_style_token(
                cell.get("style"), "whiteSpace", "wrap"
            )
            style, html_changed = _set_style_token(style, "html", "1")
            if wrap_changed or html_changed:
                cell.set("style", style)
                actions.append(
                    _action(
                        "repair.style.wrap_added",
                        cell_id,
                        "Added whiteSpace=wrap and html=1 without changing content.",
                    )
                )
        if cell.get("edge") == "1":
            geometry = cell.find("mxGeometry")
            if geometry is not None and geometry.get("relative") != "1":
                geometry.set("relative", "1")
                actions.append(
                    _action(
                        "repair.connector.geometry_relative",
                        cell_id,
                        "Set connector geometry relative=1.",
                    )
                )

    plan: dict[str, Any] | None = None
    canonical_by_id: dict[str, ET.Element] = {}
    if plan_path is not None:
        plan_path = plan_path.expanduser().resolve()
        try:
            plan = read_json(plan_path)
        except RuntimeContractError as exc:
            raise DrawioRepairError(str(exc)) from exc
        plan_issues = validate_render_plan_contract(plan)
        if plan_issues:
            details = "; ".join(f"{item.code}: {item.message}" for item in plan_issues)
            raise DrawioRepairError(f"RenderPlan is invalid: {details}")
        if mxfile.get("data-plan-id") != plan["plan_id"]:
            raise DrawioRepairError(
                "Source plan identity does not match the supplied RenderPlan."
            )
        canonical_root = _graph_root(drawio_tree(plan))
        canonical_by_id = {
            cell.get("id"): cell
            for cell in canonical_root.findall("mxCell")
            if cell.get("id") is not None
        }

        # Restore plan-owned missing cells. This cannot invent content because
        # every restored object is copied verbatim from the validated plan.
        for cell_id, canonical in canonical_by_id.items():
            if cell_id in {"0", "1"} or cell_id in current_by_id:
                continue
            restored = copy.deepcopy(canonical)
            graph_root.append(restored)
            current_by_id[cell_id] = restored
            code = (
                "repair.connector.restored_from_plan"
                if restored.get("edge") == "1"
                else "repair.cell.restored_from_plan"
            )
            actions.append(
                _action(code, cell_id, "Restored a missing plan-owned native cell.")
            )

        affected_geometry: set[str] = set()
        for issue in before.issues:
            if issue.code.startswith("drawio.geometry") and issue.path:
                affected_geometry.update(item for item in issue.path.split(",") if item)

        for element in plan["elements"]:
            cell_id = element["id"]
            current = current_by_id.get(cell_id)
            canonical = canonical_by_id.get(cell_id)
            if current is None or canonical is None:
                continue
            expected_label = _plain_label(canonical.get("value"))
            current_label = _plain_label(current.get("value"))
            if current_label and current_label != expected_label:
                skipped.append(
                    _action(
                        "repair.skipped.label_conflict",
                        cell_id,
                        "Non-empty label differs from the RenderPlan and was not overwritten.",
                    )
                )
                continue
            if not current_label and expected_label:
                current.set("value", canonical.get("value") or "")
                actions.append(
                    _action(
                        "repair.label.restored_from_plan",
                        cell_id,
                        "Restored an empty plan-bound label.",
                    )
                )
            if cell_id in affected_geometry:
                canonical_geometry = canonical.find("mxGeometry")
                current_geometry = current.find("mxGeometry")
                if canonical_geometry is not None:
                    replacement = copy.deepcopy(canonical_geometry)
                    if current_geometry is not None:
                        current.remove(current_geometry)
                    current.append(replacement)
                    actions.append(
                        _action(
                            "repair.geometry.restored_from_plan",
                            cell_id,
                            "Restored invalid or conflicting geometry from the RenderPlan.",
                        )
                    )

        plan_edge_ids = {connector["id"] for connector in plan["connectors"]}
        endpoint_issue_ids = {
            issue.path
            for issue in before.issues
            if issue.code.startswith("drawio.connector") and issue.path
        }
        for edge_id in plan_edge_ids:
            current = current_by_id.get(edge_id)
            canonical = canonical_by_id.get(edge_id)
            if current is None or canonical is None:
                continue
            expected = (
                canonical.get("source"),
                canonical.get("target"),
                canonical.get("data-directed"),
                canonical.get("data-relation"),
            )
            actual = (
                current.get("source"),
                current.get("target"),
                current.get("data-directed"),
                current.get("data-relation"),
            )
            if actual != expected or edge_id in endpoint_issue_ids:
                for attribute in (
                    "source",
                    "target",
                    "data-directed",
                    "data-relation",
                    "style",
                ):
                    value = canonical.get(attribute)
                    if value is not None:
                        current.set(attribute, value)
                canonical_geometry = canonical.find("mxGeometry")
                current_geometry = current.find("mxGeometry")
                if canonical_geometry is not None:
                    if current_geometry is not None:
                        current.remove(current_geometry)
                    current.append(copy.deepcopy(canonical_geometry))
                actions.append(
                    _action(
                        "repair.connector.restored_from_plan",
                        edge_id,
                        "Restored plan-bound endpoints, semantics, style, and geometry.",
                    )
                )

        for assertion in plan["semantic_assertions"]:
            if assertion["kind"] == "role_color":
                params = assertion["params"]
                cell_id = str(params.get("element_id", ""))
                current = current_by_id.get(cell_id)
                if current is None:
                    continue
                style = current.get("style")
                style, fill_changed = _set_style_token(
                    style, "fillColor", str(params.get("expected_fill", ""))
                )
                style, stroke_changed = _set_style_token(
                    style, "strokeColor", str(params.get("expected_stroke", ""))
                )
                if fill_changed or stroke_changed:
                    current.set("style", style)
                    actions.append(
                        _action(
                            "repair.semantic_color.restored",
                            cell_id,
                            "Restored plan-bound semantic fill and stroke colors.",
                        )
                    )

        for assertion in plan["semantic_assertions"]:
            if assertion["kind"] != "forbidden_relation":
                continue
            params = assertion["params"]
            source = str(params.get("source", ""))
            target = str(params.get("target", ""))
            directed = bool(params.get("directed"))
            for cell in list(graph_root.findall("mxCell")):
                if cell.get("edge") != "1":
                    continue
                if _edge_matches(cell, source, target, directed):
                    cell_id = cell.get("id") or "(missing)"
                    graph_root.remove(cell)
                    actions.append(
                        _action(
                            "repair.forbidden_relation.removed",
                            cell_id,
                            "Removed a connector explicitly forbidden by the RenderPlan.",
                        )
                    )

    for issue in before.issues:
        if issue.code == "drawio.editability.embedded_raster":
            skipped.append(
                _action(
                    "repair.skipped.unsafe_raster",
                    issue.path or "(unknown)",
                    "Raster removal may delete scientific content and requires redesign.",
                )
            )
        elif issue.code in {
            "drawio.structure.id_duplicate",
            "drawio.structure.id_missing",
            "drawio.structure.parent_unknown",
            "drawio.structure.cell_type_missing",
        }:
            skipped.append(
                _action(
                    "repair.skipped.unresolved_issue",
                    issue.path or "(unknown)",
                    f"No bounded repair is defined for {issue.code}.",
                )
            )

    payload = _serialize(document)
    after = _lint_payload(payload, source_path.parent)
    after.path = output_path if output_path is not None and not dry_run else source_path
    unresolved_skip = any(item["code"] != "repair.no_change" for item in skipped)
    safe_complete = not after.errors and not after.warnings and not unresolved_skip
    changed = bool(actions)
    if not changed:
        skipped.append(
            _action(
                "repair.no_change",
                "document",
                "No safe local repair was applicable.",
            )
        )
    if not dry_run:
        assert output_path is not None
        _write_atomic(output_path, payload, overwrite=overwrite)
    if sha256_file(source_path) != source_hash:
        raise DrawioRepairError("Input source changed during repair; output is not trusted.")
    return RepairResult(
        source=source_path,
        output=None if dry_run else output_path,
        dry_run=dry_run,
        source_sha256=source_hash,
        changed=changed,
        safe_complete=safe_complete,
        actions=actions,
        skipped=skipped,
        before=before,
        after=after,
    )


def format_repair_result(result: RepairResult) -> str:
    lines = [
        f"[{'PASS' if result.safe_complete else 'INCOMPLETE'}] Draw.io safe repair",
        f"Input preserved: {result.source}",
        f"Output: {result.output if result.output is not None else '(dry run)'}",
        f"Applied actions: {len(result.actions)}",
        f"Skipped actions: {len(result.skipped)}",
    ]
    for item in result.actions:
        lines.append(f"[APPLIED] {item['code']} ({item['cell_id']}): {item['message']}")
    for item in result.skipped:
        lines.append(f"[SKIPPED] {item['code']} ({item['cell_id']}): {item['message']}")
    lines.append(
        f"Post-repair lint: {len(result.after.errors)} errors, {len(result.after.warnings)} warnings"
    )
    return "\n".join(lines)
