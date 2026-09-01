#!/usr/bin/env python3
"""Inspect backend-neutral editable sources and artifacts against a RenderPlan."""

from __future__ import annotations

import html
import os
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

SCRIPT_DIR = str(Path(__file__).resolve().parent)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from artifact_utils import inspect_artifact_dimensions
from drawio_lint import lint_drawio
from figure_source import FigureSourceError, normalize_source
from figure_coverage import extract_spec_requirements, requirement_multiset
from figure_runtime import (
    RuntimeContractError,
    read_json,
    sha256_file,
    utc_now,
    validate_manifest_contract,
    validate_qa_contract,
    validate_render_plan_contract,
    write_json_atomic,
)
from svg_lint import lint_svg


class FigureInspectionError(RuntimeError):
    """Raised when inspection setup is invalid or the QA report cannot be saved."""


@dataclass
class InspectionResult:
    qa_path: Path
    report: dict[str, Any]

    @property
    def passed(self) -> bool:
        return self.report.get("outcome") in {
            "PASS",
            "AUTOMATED_CHECKS_PASSED",
        }


def _portable_path(path: Path, base: Path) -> str:
    try:
        return os.path.relpath(path.resolve(), base.resolve())
    except ValueError:
        return str(path.resolve())


def _qa_file_ref(path: Path, base: Path) -> dict[str, str]:
    return {"path": _portable_path(path, base), "sha256": sha256_file(path)}


def _plain_text(value: str | None) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(value.split())


def _normalized_text(value: str | None) -> str:
    return " ".join(_plain_text(value).casefold().split())


def _qa_issue(
    *,
    severity: str,
    category: str,
    code: str,
    issue: str,
    why: str,
    fix: str,
    repairability: str,
    cell_id: str | None = None,
    artifact: str | None = None,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "severity": severity,
        "category": category,
        "code": code,
        "issue": issue,
        "why_it_matters": why,
        "recommended_fix": fix,
        "repairability": repairability,
    }
    location: dict[str, Any] = {}
    if cell_id is not None:
        location["cell_id"] = cell_id
    if artifact is not None:
        location["artifact"] = artifact
    if location:
        result["location"] = location
    if evidence:
        result["evidence"] = evidence
    return result


def _check(
    *,
    check_id: str,
    status: str,
    category: str,
    message: str,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": check_id,
        "status": status,
        "category": category,
        "message": message,
    }
    if evidence:
        result["evidence"] = evidence
    return result


def _resolve_manifest_artifacts(
    manifest: dict[str, Any], manifest_path: Path
) -> list[tuple[dict[str, Any], Path]]:
    result = []
    for record in manifest.get("artifacts", []):
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            continue
        path = Path(record["path"])
        if not path.is_absolute():
            path = manifest_path.parent / path
        result.append((record, path.resolve()))
    return result


def _final_css_width(final_size: dict[str, Any]) -> float:
    width = float(final_size["width"])
    unit = final_size["unit"]
    if unit == "mm":
        return width / 25.4 * 96.0
    if unit == "in":
        return width * 96.0
    return width


def _append_lint_findings(
    source_path: Path,
    backend: str,
    plan: dict[str, Any],
    issues: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    lint_report = (
        lint_drawio(source_path)
        if backend == "drawio"
        else lint_svg(source_path, plan=plan)
    )
    backend_label = "Draw.io" if backend == "drawio" else "Native SVG"
    checks.append(
        _check(
            check_id=f"{backend}-lint",
            status="PASS" if not lint_report.issues else "FAIL",
            category="Technical",
            message=(
                f"{backend_label} source passed structural and geometry lint."
                if not lint_report.issues
                else f"{backend_label} lint reported {len(lint_report.issues)} issue(s)."
            ),
        )
    )
    for item in lint_report.issues:
        is_overlap = item.code == "drawio.geometry.overlap"
        severity = (
            "BLOCKING"
            if item.severity == "ERROR"
            else "MAJOR"
            if is_overlap
            else "MINOR"
        )
        category = "Visual" if item.code.startswith("drawio.geometry") else "Technical"
        issues.append(
            _qa_issue(
                severity=severity,
                category=category,
                code=item.code,
                issue=item.message,
                why="The editable source must preserve correct structure, geometry, and exportability.",
                fix=f"Correct the reported {backend_label} object or regenerate it from the validated RenderPlan.",
                repairability=(
                    "SAFE_LOCAL"
                    if item.code
                    in {
                        "drawio.style.wrap_missing",
                        "drawio.connector.geometry_not_relative",
                        "drawio.geometry.out_of_bounds",
                    }
                    else "NEEDS_DESIGN"
                ),
                cell_id=item.path,
            )
        )


def _inspect_spec_coverage(
    *,
    plan: dict[str, Any],
    plan_path: Path,
    source: dict[str, Any],
    issues: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    """Bind QA to the live FigureSpec before plan-bound artifact assertions."""

    issue_count_before = len(issues)
    spec_reference = Path(plan["figure_spec"]["path"])
    if not spec_reference.is_absolute():
        spec_reference = plan_path.parent / spec_reference
    spec_path = spec_reference.resolve()
    if not spec_path.is_file():
        issues.append(
            _qa_issue(
                severity="BLOCKING",
                category="Scientific",
                code="scientific.coverage.figure_spec_missing",
                issue=f"The FigureSpec bound to the RenderPlan is missing: {spec_path}",
                why="Coverage cannot be established without the canonical scientific source.",
                fix="Restore the exact FigureSpec or regenerate the RenderPlan from its current location.",
                repairability="NEEDS_SCIENTIFIC_INPUT",
            )
        )
        checks.append(
            _check(
                check_id="figurespec-coverage",
                status="FAIL",
                category="Scientific",
                message="FigureSpec coverage could not be evaluated because the source is missing.",
            )
        )
        return

    actual_hash = sha256_file(spec_path)
    if actual_hash != plan["figure_spec"]["sha256"]:
        issues.append(
            _qa_issue(
                severity="BLOCKING",
                category="Scientific",
                code="scientific.coverage.figure_spec_hash_mismatch",
                issue="The current FigureSpec bytes do not match the RenderPlan binding.",
                why="A stale plan can silently omit or misrepresent changed scientific requirements.",
                fix="Regenerate the RenderPlan from the current FigureSpec before authoring or export.",
                repairability="NEEDS_SCIENTIFIC_INPUT",
                artifact=str(spec_path),
                evidence=[
                    f"expected={plan['figure_spec']['sha256']}",
                    f"actual={actual_hash}",
                ],
            )
        )

    try:
        requirements = extract_spec_requirements(spec_path)
    except (OSError, UnicodeError) as exc:
        raise FigureInspectionError(f"Could not read FigureSpec coverage source: {exc}") from exc

    coverage = plan["spec_coverage"]
    for section, code in (
        ("must_show", "scientific.coverage.must_show_missing"),
        ("relationships", "scientific.coverage.relationship_missing"),
    ):
        live = requirement_multiset(requirements[section])
        recorded = requirement_multiset(
            item["source_text"] for item in coverage[section]
        )
        if live != recorded:
            missing = list((live - recorded).elements())
            stale = list((recorded - live).elements())
            issues.append(
                _qa_issue(
                    severity="BLOCKING",
                    category="Scientific",
                    code=code,
                    issue=f"RenderPlan coverage does not exhaustively match FigureSpec {section}.",
                    why="The execution plan must account for every canonical scientific requirement.",
                    fix="Regenerate the RenderPlan; do not manually mark unmatched content as covered.",
                    repairability="NEEDS_SCIENTIFIC_INPUT",
                    evidence=[
                        *[f"missing: {item}" for item in missing],
                        *[f"stale: {item}" for item in stale],
                    ][:20],
                )
            )

    objects = source["objects"]
    connectors = source["connectors"]
    assertion_ids = {
        item.get("id")
        for item in plan["semantic_assertions"]
        if isinstance(item, dict)
    }
    for section, code in (
        ("must_show", "scientific.coverage.must_show_unmapped"),
        ("relationships", "scientific.coverage.relationship_unmapped"),
    ):
        for item in coverage[section]:
            if item["status"] != "MAPPED":
                issues.append(
                    _qa_issue(
                        severity="BLOCKING",
                        category="Scientific",
                        code=code,
                        issue=f"Unmapped FigureSpec requirement: {item['source_text']}",
                        why="Must Show content and canonical relationships cannot be silently dropped.",
                        fix="Add an explicit representation or revise the FigureSpec with scientific ownership.",
                        repairability="NEEDS_SCIENTIFIC_INPUT",
                        evidence=[item.get("reason", "unresolved")],
                    )
                )
                continue
            for reference in item["representations"]:
                kind = reference["kind"]
                ids = reference["ids"]
                represented = False
                if kind == "element" and len(ids) == 1:
                    represented = ids[0] in objects
                elif kind == "connector" and len(ids) == 1:
                    represented = ids[0] in connectors
                elif kind == "assertion" and len(ids) == 1:
                    represented = ids[0] in assertion_ids
                elif kind == "parent_child" and len(ids) == 2:
                    parent, child = ids
                    represented = (
                        parent in objects
                        and child in objects
                        and objects[child].get("parent_id") == parent
                    )
                if not represented:
                    issues.append(
                        _qa_issue(
                            severity="BLOCKING",
                            category="Scientific",
                            code="scientific.coverage.representation_missing",
                            issue=(
                                f"Mapped requirement {item['id']!r} references missing "
                                f"artifact representation {kind}:{ids!r}."
                            ),
                            why="Plan coverage is only valid when the editable source still contains the mapped structure.",
                            fix="Restore the plan-bound element, connector, assertion, or parent-child relationship.",
                            repairability="SAFE_LOCAL",
                            cell_id=ids[-1] if ids else None,
                            evidence=[item["source_text"]],
                        )
                    )

    coverage_passed = len(issues) == issue_count_before
    checks.append(
        _check(
            check_id="figurespec-coverage",
            status="PASS" if coverage_passed else "FAIL",
            category="Scientific",
            message=(
                "Every Must Show item and canonical relationship is mapped from FigureSpec to the editable source."
                if coverage_passed
                else "FigureSpec-to-RenderPlan-to-source coverage is incomplete or stale."
            ),
            evidence=[
                f"must_show={coverage['summary']['must_show_mapped']}/{coverage['summary']['must_show_total']}",
                f"relationships={coverage['summary']['relationships_mapped']}/{coverage['summary']['relationships_total']}",
            ],
        )
    )


def _inspect_artifacts(
    *,
    plan: dict[str, Any],
    plan_path: Path,
    source_path: Path,
    manifest: dict[str, Any],
    manifest_path: Path,
    issues: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> tuple[list[Path], str | None]:
    contract_issues = validate_manifest_contract(manifest)
    for item in contract_issues:
        issues.append(
            _qa_issue(
                severity="BLOCKING",
                category="Technical",
                code=item.code,
                issue=item.message,
                why="Inspection cannot trust a manifest that violates its execution contract.",
                fix="Regenerate the artifact manifest through the unified export command.",
                repairability="NONE",
            )
        )

    if manifest.get("status") != "COMPLETED":
        issues.append(
            _qa_issue(
                severity="BLOCKING",
                category="Technical",
                code="technical.export.incomplete",
                issue=f"Artifact manifest status is {manifest.get('status')!r}, not COMPLETED.",
                why="The actual exported figure is unavailable for final-size QA.",
                fix="Resolve backend export issues and rerun export before inspection.",
                repairability="NONE",
            )
        )

    expected_plan_hash = manifest.get("plan", {}).get("sha256")
    expected_source_hash = manifest.get("source", {}).get("sha256")
    if expected_plan_hash != sha256_file(plan_path):
        issues.append(
            _qa_issue(
                severity="BLOCKING",
                category="Technical",
                code="technical.manifest.plan_hash_mismatch",
                issue="RenderPlan bytes no longer match the artifact manifest.",
                why="Artifacts may have been produced from a different execution plan.",
                fix="Export again from the current RenderPlan.",
                repairability="NONE",
            )
        )
    if expected_source_hash != sha256_file(source_path):
        issues.append(
            _qa_issue(
                severity="BLOCKING",
                category="Technical",
                code="technical.manifest.source_hash_mismatch",
                issue="Editable source bytes no longer match the artifact manifest.",
                why="Inspection must bind exports to the exact editable source.",
                fix="Export again from the current editable source.",
                repairability="NONE",
            )
        )

    resolved = _resolve_manifest_artifacts(manifest, manifest_path)
    artifact_paths: list[Path] = []
    formats_present: set[str] = set()
    svg_text: str | None = None
    canvas_ratio = float(plan["canvas"]["width"]) / float(plan["canvas"]["height"])
    for record, path in resolved:
        format_name = record.get("format")
        if isinstance(format_name, str):
            formats_present.add(format_name)
        if not path.is_file():
            issues.append(
                _qa_issue(
                    severity="BLOCKING",
                    category="Technical",
                    code="technical.artifact.missing",
                    issue=f"Recorded artifact does not exist: {path}",
                    why="A missing required output cannot be inspected or delivered.",
                    fix="Rerun export and keep the manifest with its artifacts.",
                    repairability="NONE",
                    artifact=str(path),
                )
            )
            continue
        artifact_paths.append(path)
        if sha256_file(path) != record.get("sha256"):
            issues.append(
                _qa_issue(
                    severity="BLOCKING",
                    category="Technical",
                    code="technical.artifact.hash_mismatch",
                    issue=f"Artifact changed after export: {path.name}",
                    why="The inspected bytes are not the bytes recorded by the export run.",
                    fix="Regenerate the artifact and manifest together.",
                    repairability="NONE",
                    artifact=str(path),
                )
            )
        dimensions = inspect_artifact_dimensions(path, str(format_name))
        if dimensions is None:
            issues.append(
                _qa_issue(
                    severity="MAJOR",
                    category="Technical",
                    code="technical.artifact.dimensions_unreadable",
                    issue=f"Could not determine dimensions of {path.name}.",
                    why="Canvas ratio and final-size rendering cannot be checked reliably.",
                    fix="Re-export the artifact in a supported valid format.",
                    repairability="NONE",
                    artifact=str(path),
                )
            )
        else:
            ratio = float(dimensions["width"]) / float(dimensions["height"])
            if abs(ratio / canvas_ratio - 1.0) > 0.02:
                issues.append(
                    _qa_issue(
                        severity="MAJOR",
                        category="Technical",
                        code="technical.artifact.aspect_mismatch",
                        issue=f"{path.name} aspect ratio {ratio:.3f} differs from the planned canvas {canvas_ratio:.3f}.",
                        why="Unexpected crop or stretch can change grouping and readability.",
                        fix="Export the full planned canvas without unintended crop or scaling.",
                        repairability="NONE",
                        artifact=str(path),
                    )
                )
        if format_name == "svg":
            try:
                svg_root = ET.parse(path).getroot()
                svg_text = _normalized_text(" ".join(svg_root.itertext()))
                image_nodes = [node for node in svg_root.iter() if node.tag.rsplit("}", 1)[-1] == "image"]
                if image_nodes:
                    issues.append(
                        _qa_issue(
                            severity="BLOCKING",
                            category="Technical",
                            code="technical.svg.embedded_raster",
                            issue="SVG export contains embedded image elements.",
                            why="The required vector/editable delivery may have been rasterized.",
                            fix="Remove raster cells and export native vector objects.",
                            repairability="NEEDS_DESIGN",
                            artifact=str(path),
                        )
                    )
            except ET.ParseError as exc:
                issues.append(
                    _qa_issue(
                        severity="BLOCKING",
                        category="Technical",
                        code="technical.svg.invalid",
                        issue=f"SVG export is invalid XML: {exc}",
                        why="A broken vector export cannot be inspected or used.",
                        fix="Regenerate the SVG artifact from the current editable source.",
                        repairability="NONE",
                        artifact=str(path),
                    )
                )

    missing_formats = set(plan["outputs"]["formats"]) - formats_present
    for format_name in sorted(missing_formats):
        issues.append(
            _qa_issue(
                severity="MAJOR",
                category="Technical",
                code="technical.artifact.required_format_missing",
                issue=f"Required {format_name.upper()} output is not recorded in the manifest.",
                why="The FigureSpec delivery contract is incomplete.",
                fix=f"Export and record the required {format_name.upper()} artifact.",
                repairability="NONE",
            )
        )

    checks.append(
        _check(
            check_id="artifact-integrity",
            status=(
                "PASS"
                if not any(
                    item["code"].startswith("technical.artifact")
                    or item["code"].startswith("technical.manifest")
                    or item["code"] == "technical.export.incomplete"
                    for item in issues
                )
                else "FAIL"
            ),
            category="Technical",
            message=f"Inspected {len(artifact_paths)} exported artifact(s).",
        )
    )
    return artifact_paths, svg_text


def _inspect_source_parity(
    *,
    plan: dict[str, Any],
    source: dict[str, Any],
    issues: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    """Check plan→source completeness and obvious unplanned scientific content."""

    issue_count_before = len(issues)
    planned_objects = {item["id"]: item for item in plan["elements"]}
    planned_connectors = {item["id"]: item for item in plan["connectors"]}
    source_objects = source["objects"]
    source_connectors = source["connectors"]

    if source.get("plan_id") != plan["plan_id"]:
        issues.append(
            _qa_issue(
                severity="BLOCKING",
                category="Scientific",
                code="semantic.source.plan_id_mismatch",
                issue="Editable source identity does not match the RenderPlan.",
                why="Scientific inspection must bind to the exact planned object graph.",
                fix="Re-author the source from the supplied RenderPlan.",
                repairability="SAFE_LOCAL",
            )
        )

    for object_id, planned in planned_objects.items():
        actual = source_objects.get(object_id)
        if actual is None:
            issues.append(
                _qa_issue(
                    severity="BLOCKING",
                    category="Scientific",
                    code="semantic.source.required_object_missing",
                    issue=f"Planned object is missing from the editable source: {object_id}",
                    why="A planned scientific or helper representation cannot silently disappear.",
                    fix="Restore the object with its stable RenderPlan ID.",
                    repairability="SAFE_LOCAL",
                    cell_id=object_id,
                )
            )
            continue
        if actual.get("parent_id") != planned.get("parent_id"):
            issues.append(
                _qa_issue(
                    severity="BLOCKING",
                    category="Scientific",
                    code="semantic.source.parent_mismatch",
                    issue=f"Object {object_id!r} has the wrong parent hierarchy.",
                    why="Containment and hierarchy are scientific relations, not merely coordinates.",
                    fix="Restore the planned parent-child nesting.",
                    repairability="SAFE_LOCAL",
                    cell_id=object_id,
                    evidence=[
                        f"expected={planned.get('parent_id')!r}",
                        f"actual={actual.get('parent_id')!r}",
                    ],
                )
            )
        if actual.get("semantic_role") != planned.get("semantic_role"):
            issues.append(
                _qa_issue(
                    severity="BLOCKING",
                    category="Scientific",
                    code="semantic.source.role_mismatch",
                    issue=f"Object {object_id!r} has the wrong semantic role.",
                    why="Backend-private markup must preserve shared semantic roles.",
                    fix="Restore the RenderPlan semantic role metadata.",
                    repairability="SAFE_LOCAL",
                    cell_id=object_id,
                )
            )
        if _normalized_text(actual.get("label")) != _normalized_text(planned.get("label")):
            issues.append(
                _qa_issue(
                    severity="BLOCKING",
                    category="Scientific",
                    code="semantic.source.label_mismatch",
                    issue=f"Object {object_id!r} has a missing or altered planned label.",
                    why="Scientific and helper labels must remain traceable to the shared RenderPlan.",
                    fix="Restore the exact plan-bound live-text label.",
                    repairability="SAFE_LOCAL",
                    cell_id=object_id,
                )
            )

    for connector_id, planned in planned_connectors.items():
        actual = source_connectors.get(connector_id)
        if actual is None:
            issues.append(
                _qa_issue(
                    severity="BLOCKING",
                    category="Scientific",
                    code="semantic.source.required_relation_missing",
                    issue=f"Planned connector is missing from the editable source: {connector_id}",
                    why="A planned scientific relation cannot silently disappear.",
                    fix="Restore the connector with its stable RenderPlan ID and endpoints.",
                    repairability="SAFE_LOCAL",
                    cell_id=connector_id,
                )
            )
            continue
        expected = (
            planned["source"],
            planned["target"],
            planned["relation"],
            planned["directed"],
        )
        observed = (
            actual.get("source"),
            actual.get("target"),
            actual.get("relation"),
            actual.get("directed"),
        )
        if observed != expected:
            issues.append(
                _qa_issue(
                    severity="BLOCKING",
                    category="Scientific",
                    code="semantic.source.relation_mismatch",
                    issue=f"Connector {connector_id!r} does not match the planned relation.",
                    why="Direction, endpoints, and relation kind carry scientific meaning.",
                    fix="Restore the exact plan-bound connector semantics.",
                    repairability="SAFE_LOCAL",
                    cell_id=connector_id,
                    evidence=[f"expected={expected!r}", f"actual={observed!r}"],
                )
            )
        if _normalized_text(actual.get("label")) != _normalized_text(planned.get("label")):
            issues.append(
                _qa_issue(
                    severity="BLOCKING",
                    category="Scientific",
                    code="semantic.source.label_mismatch",
                    issue=f"Connector {connector_id!r} has a missing or altered planned label.",
                    why="Visible relation labels must be present in the editable source, not reconstructed from the plan during QA.",
                    fix="Restore the exact plan-bound connector label as live text.",
                    repairability="SAFE_LOCAL",
                    cell_id=connector_id,
                )
            )

    for object_id, actual in source_objects.items():
        if object_id in planned_objects:
            continue
        if actual.get("label"):
            issues.append(
                _qa_issue(
                    severity="BLOCKING",
                    category="Scientific",
                    code="semantic.unplanned_label.present",
                    issue=f"Unplanned labeled source object is present: {actual['label']!r}",
                    why="The editable source must not silently invent scientific-looking content.",
                    fix="Remove the object or add it deliberately to the RenderPlan from grounded FigureSpec content.",
                    repairability="NEEDS_SCIENTIFIC_INPUT",
                    cell_id=object_id,
                )
            )
        else:
            issues.append(
                _qa_issue(
                    severity="BLOCKING",
                    category="Scientific",
                    code="semantic.unplanned_required_object.present",
                    issue=f"Unplanned semantic source object is present: {object_id}",
                    why="Unplanned objects can imply structure that the scientific plan never authorized.",
                    fix="Remove the object or add a grounded representation to the RenderPlan.",
                    repairability="NEEDS_SCIENTIFIC_INPUT",
                    cell_id=object_id,
                )
            )
    for label in source.get("extra_labels", []):
        issues.append(
            _qa_issue(
                severity="BLOCKING",
                category="Scientific",
                code="semantic.unplanned_label.present",
                issue=f"Unplanned live SVG label is present: {label!r}",
                why="Scientific-looking text must be traceable to a planned object or connector.",
                fix="Remove the label or bind it to a grounded RenderPlan object.",
                repairability="NEEDS_SCIENTIFIC_INPUT",
            )
        )
    for connector_id, actual in source_connectors.items():
        if connector_id in planned_connectors:
            continue
        issues.append(
            _qa_issue(
                severity="BLOCKING",
                category="Scientific",
                code="semantic.unplanned_relation.present",
                issue=(
                    f"Unplanned source relation is present: {actual.get('source')} "
                    f"→ {actual.get('target')}"
                ),
                why="A backend must not invent a scientific relation absent from the RenderPlan.",
                fix="Remove the connector or ground it through FigureSpec and RenderPlan coverage.",
                repairability="NEEDS_SCIENTIFIC_INPUT",
                cell_id=connector_id,
            )
        )

    checks.append(
        _check(
            check_id="plan-source-parity",
            status="PASS" if len(issues) == issue_count_before else "FAIL",
            category="Scientific",
            message=(
                "Editable source matches the planned objects, hierarchy, and relations without unplanned scientific content."
                if len(issues) == issue_count_before
                else "Editable source diverges from the RenderPlan or contains unplanned scientific content."
            ),
        )
    )


def _inspect_assertions(
    *,
    plan: dict[str, Any],
    source: dict[str, Any],
    svg_text: str | None,
    issues: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    objects = source["objects"]
    connectors = source["connectors"]
    for assertion in plan["semantic_assertions"]:
        assertion_id = assertion["id"]
        kind = assertion["kind"]
        severity = assertion["severity"]
        params = assertion["params"]
        why = assertion.get("why") or "The assertion protects FigureSpec meaning."
        passed = True
        message = "Assertion passed."
        category = "Scientific"
        generated_issue: dict[str, Any] | None = None

        if kind == "required_label":
            cell_id = params.get("element_id")
            expected = str(params.get("label", ""))
            source_object = objects.get(cell_id)
            source_ok = (
                source_object is not None
                and _normalized_text(source_object.get("label")) == _normalized_text(expected)
            )
            artifact_ok = svg_text is None or _normalized_text(expected) in svg_text
            passed = source_ok and artifact_ok
            message = f"Required label {expected!r} is present." if passed else f"Required label {expected!r} is missing or altered."
            if not passed:
                generated_issue = _qa_issue(
                    severity=severity,
                    category="Scientific",
                    code="semantic.required_label.missing",
                    issue=message,
                    why=why,
                    fix="Restore the exact plan-bound label in the editable source object and re-export.",
                    repairability="SAFE_LOCAL",
                    cell_id=str(cell_id),
                    evidence=[f"expected={expected!r}", f"source_ok={source_ok}", f"svg_ok={artifact_ok}"],
                )
        elif kind in {"required_relation", "forbidden_relation"}:
            relation_source = str(params.get("source", ""))
            relation_target = str(params.get("target", ""))
            directed = bool(params.get("directed"))
            present = any(
                item.get("source") == relation_source
                and item.get("target") == relation_target
                and item.get("directed") is directed
                if directed
                else {item.get("source"), item.get("target")} == {
                    relation_source,
                    relation_target,
                }
                and item.get("directed") is False
                for item in connectors.values()
            )
            required = kind == "required_relation"
            passed = present if required else not present
            relation = params.get("relation", "relation")
            message = (
                f"Required relation {relation_source} → {relation_target} is present."
                if required and passed
                else f"Required relation {relation_source} → {relation_target} is missing."
                if required
                else f"Forbidden relation {relation_source} → {relation_target} is absent."
                if passed
                else f"Forbidden relation {relation_source} → {relation_target} is present."
            )
            if not passed:
                generated_issue = _qa_issue(
                    severity=severity,
                    category="Scientific",
                    code=(
                        "semantic.required_relation.missing"
                        if required
                        else "semantic.forbidden_relation.present"
                    ),
                    issue=message,
                    why=why,
                    fix=(
                        "Restore the plan-bound connector and preserve its direction semantics."
                        if required
                        else "Remove the unsupported connector without altering other relations."
                    ),
                    repairability="SAFE_LOCAL",
                    evidence=[f"relation={relation}", f"directed={directed}"],
                )
        elif kind == "role_color":
            category = "Communication"
            cell_id = str(params.get("element_id", ""))
            source_object = objects.get(cell_id, {})
            expected_fill = str(params.get("expected_fill", ""))
            expected_stroke = str(params.get("expected_stroke", ""))
            passed = (
                str(source_object.get("fill") or "").casefold() == expected_fill.casefold()
                and str(source_object.get("stroke") or "").casefold() == expected_stroke.casefold()
            )
            message = f"Semantic color for {cell_id!r} is preserved." if passed else f"Semantic color for {cell_id!r} changed."
            if not passed:
                generated_issue = _qa_issue(
                    severity=severity,
                    category=category,
                    code="semantic.role_color.mismatch",
                    issue=message,
                    why=why,
                    fix="Restore the RenderPlan fill and stroke tokens for this semantic role.",
                    repairability="SAFE_LOCAL",
                    cell_id=cell_id,
                )
        elif kind == "no_embedded_raster":
            category = "Technical"
            raster = bool(source["embedded_raster"])
            passed = not raster
            message = "Source contains no embedded raster cells." if passed else "Source contains embedded raster content."
            if not passed:
                generated_issue = _qa_issue(
                    severity=severity,
                    category=category,
                    code="technical.editability.embedded_raster",
                    issue=message,
                    why=why,
                    fix="Reconstruct the affected object as native vector content.",
                    repairability="NEEDS_DESIGN",
                )
        elif kind in {"within_canvas", "minimum_text_size"}:
            category = "Visual" if kind == "minimum_text_size" else "Technical"
            delegated_code = (
                "visual.text.too_small"
                if kind == "minimum_text_size"
                else "drawio.geometry.out_of_bounds"
            )
            passed = not any(item["code"] == delegated_code for item in issues)
            message = (
                "Delegated final-size/geometry assertion passed."
                if passed
                else "Delegated final-size/geometry assertion failed."
            )
        checks.append(
            _check(
                check_id=assertion_id,
                status="PASS" if passed else "FAIL",
                category=category,
                message=message,
            )
        )
        if generated_issue is not None:
            issues.append(generated_issue)


def _inspect_final_size(
    *,
    plan: dict[str, Any],
    source: dict[str, Any],
    issues: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    canvas = plan["canvas"]
    final_size = plan["final_size"]
    canvas_ratio = float(canvas["width"]) / float(canvas["height"])
    final_ratio = float(final_size["width"]) / float(final_size["height"])
    if abs(final_ratio / canvas_ratio - 1.0) > 0.02:
        issues.append(
            _qa_issue(
                severity="MAJOR",
                category="Visual",
                code="visual.final_size.aspect_mismatch",
                issue=f"Final-size ratio {final_ratio:.3f} differs from canvas ratio {canvas_ratio:.3f}.",
                why="Stretching or unintended crop can change the figure's visual hierarchy.",
                fix="Use a final size with the planned aspect ratio or revise the RenderPlan canvas.",
                repairability="NEEDS_DESIGN",
            )
        )

    scale = _final_css_width(final_size) / float(canvas["width"])
    minimum_pt = float(final_size["minimum_text_size_pt"])
    too_small: list[str] = []
    for cell_id, item in source["objects"].items():
        if not _plain_text(item.get("label")):
            continue
        try:
            source_px = float(item.get("font_size_px") or plan["theme"]["font_size_px"])
        except (TypeError, ValueError):
            source_px = float(plan["theme"]["font_size_px"])
        final_pt = source_px * scale * 72.0 / 96.0
        if final_pt + 1e-6 < minimum_pt:
            too_small.append(f"{cell_id}={final_pt:.2f}pt")
    if too_small:
        issues.append(
            _qa_issue(
                severity="MAJOR",
                category="Visual",
                code="visual.text.too_small",
                issue=f"{len(too_small)} label(s) fall below {minimum_pt:g} pt at final size.",
                why="Essential labels must remain readable at the intended publication size.",
                fix="Simplify content, enlarge the affected labels, or allocate more space before export.",
                repairability="NEEDS_DESIGN",
                evidence=too_small[:20],
            )
        )
    checks.append(
        _check(
            check_id="final-size-text",
            status="FAIL" if too_small else "PASS",
            category="Visual",
            message=(
                f"All source labels remain at least {minimum_pt:g} pt at final size."
                if not too_small
                else f"{len(too_small)} label(s) are below the minimum final-size text threshold."
            ),
            evidence=too_small[:20] if too_small else None,
        )
    )


def inspect_figure(
    *,
    plan_path: Path,
    source_path: Path,
    manifest_path: Path,
    qa_path: Path | None = None,
    overwrite: bool = False,
) -> InspectionResult:
    plan_path = plan_path.expanduser().resolve()
    source_path = source_path.expanduser().resolve()
    manifest_path = manifest_path.expanduser().resolve()
    try:
        plan = read_json(plan_path)
        manifest = read_json(manifest_path)
    except RuntimeContractError as exc:
        raise FigureInspectionError(str(exc)) from exc
    plan_issues = validate_render_plan_contract(plan)
    if plan_issues:
        details = "; ".join(f"{item.code}: {item.message}" for item in plan_issues)
        raise FigureInspectionError(f"RenderPlan is invalid: {details}")
    if not source_path.is_file():
        raise FigureInspectionError(f"Editable source does not exist: {source_path}")
    backend = plan.get("backend")
    if backend not in {"drawio", "svg"}:
        raise FigureInspectionError(f"Unsupported inspection backend: {backend!r}")
    if qa_path is None:
        qa_path = plan_path.parent / plan["outputs"]["qa_report"]
    qa_path = qa_path.expanduser()
    if not qa_path.is_absolute():
        qa_path = manifest_path.parent / qa_path
    qa_path = qa_path.resolve()
    if qa_path.exists() and not overwrite:
        raise FigureInspectionError(f"Refusing to overwrite existing QA report: {qa_path}")

    issues: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    try:
        source = normalize_source(source_path, backend=backend, plan=plan)
    except FigureSourceError as exc:
        raise FigureInspectionError(str(exc)) from exc
    _append_lint_findings(source_path, backend, plan, issues, checks)
    _inspect_spec_coverage(
        plan=plan,
        plan_path=plan_path,
        source=source,
        issues=issues,
        checks=checks,
    )
    _inspect_source_parity(
        plan=plan,
        source=source,
        issues=issues,
        checks=checks,
    )
    artifact_paths, svg_text = _inspect_artifacts(
        plan=plan,
        plan_path=plan_path,
        source_path=source_path,
        manifest=manifest,
        manifest_path=manifest_path,
        issues=issues,
        checks=checks,
    )
    _inspect_final_size(plan=plan, source=source, issues=issues, checks=checks)
    _inspect_assertions(
        plan=plan,
        source=source,
        svg_text=svg_text,
        issues=issues,
        checks=checks,
    )

    summary = {"blocking": 0, "major": 0, "minor": 0}
    for item in issues:
        summary[item["severity"].casefold()] += 1
    outcome = (
        "BLOCKED"
        if summary["blocking"]
        else "REVISION_REQUIRED"
        if summary["major"] or summary["minor"]
        else "AUTOMATED_CHECKS_PASSED"
    )
    qa_report = {
        "schema_version": "1.1",
        "run_id": f"{plan['plan_id']}-qa",
        "assessment_scope": "AUTOMATED_EXECUTION",
        "human_review_status": "NOT_PERFORMED",
        "outcome": outcome,
        "plan": _qa_file_ref(plan_path, qa_path.parent),
        "source": _qa_file_ref(source_path, qa_path.parent),
        "artifacts": [_qa_file_ref(path, qa_path.parent) for path in artifact_paths],
        "final_size": {
            "width": plan["final_size"]["width"],
            "height": plan["final_size"]["height"],
            "unit": plan["final_size"]["unit"],
        },
        "summary": summary,
        "checks": checks,
        "issues": issues,
        "inspected_at": utc_now(),
        "metadata": {
            "manifest": _portable_path(manifest_path, qa_path.parent),
            "inspection_basis": (
                "normalized editable source objects plus backend-neutral artifact metadata and SVG text"
            ),
            "ocr_used": False,
            "scope_note": (
                "This outcome covers automated execution checks only; it does not claim complete "
                "scientific, communication, or human visual approval."
            ),
        },
    }
    contract_issues = validate_qa_contract(qa_report)
    if contract_issues:
        details = "; ".join(f"{item.code}: {item.message}" for item in contract_issues)
        raise FigureInspectionError(f"Generated QA report is invalid: {details}")
    try:
        write_json_atomic(qa_path, qa_report, overwrite=overwrite)
    except RuntimeContractError as exc:
        raise FigureInspectionError(str(exc)) from exc
    return InspectionResult(qa_path=qa_path, report=qa_report)


def format_inspection_result(result: InspectionResult) -> str:
    report = result.report
    lines = [
        f"[{'AUTOMATED CHECKS PASSED' if result.passed else 'FAIL'}] Figure inspection",
        f"Outcome: {report['outcome']}",
        f"Assessment scope: {report['assessment_scope']}",
        f"Human review: {report['human_review_status']}",
        f"QA report: {result.qa_path}",
        (
            "Issues: "
            f"{report['summary']['blocking']} blocking, "
            f"{report['summary']['major']} major, "
            f"{report['summary']['minor']} minor"
        ),
    ]
    for issue in report["issues"]:
        lines.append(
            f"[{issue['severity']}] {issue['category']} / {issue['code']}: {issue['issue']}"
        )
    return "\n".join(lines)
