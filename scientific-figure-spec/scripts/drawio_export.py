#!/usr/bin/env python3
"""Draw.io Desktop CLI export adapter with artifact manifests."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

SCRIPT_DIR = str(Path(__file__).resolve().parent)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from artifact_utils import MEDIA_TYPES, file_reference, inspect_artifact_dimensions
from drawio_lint import lint_drawio
from figure_coverage import coverage_is_complete
from figure_runtime import (
    RuntimeContractError,
    RuntimeIssue,
    command_version,
    read_json,
    resolve_drawio_command,
    sha256_file,
    utc_now,
    validate_manifest_contract,
    validate_render_plan_contract,
    write_json_atomic,
)


@dataclass
class ExportResult:
    manifest_path: Path
    manifest: dict[str, Any]

    @property
    def success(self) -> bool:
        return self.manifest.get("status") == "COMPLETED"


class DrawioExportError(RuntimeError):
    """Raised when export setup or manifest writing is unsafe."""


def _manifest_issue(issue: RuntimeIssue) -> dict[str, str]:
    return {
        "severity": issue.severity,
        "code": issue.code,
        "message": issue.message,
    }


def _base_manifest(
    *,
    plan: dict[str, Any],
    plan_path: Path,
    source_path: Path,
    manifest_path: Path,
    command: list[str] | None,
    version: str | None,
) -> dict[str, Any]:
    base = manifest_path.parent
    return {
        "schema_version": "1.0",
        "run_id": f"{plan['plan_id']}-export",
        "status": "BLOCKED",
        "plan": file_reference(plan_path, base, "application/json"),
        "source": file_reference(
            source_path,
            base,
            "application/vnd.jgraph.mxfile",
        ),
        "exporter": {
            "backend": "drawio",
            "command": command or [],
            "version": version,
            "exit_code": None,
        },
        "artifacts": [],
        "issues": [],
        "created_at": utc_now(),
        "metadata": {"invocations": []},
    }


def _write_valid_manifest(
    path: Path,
    manifest: dict[str, Any],
    *,
    overwrite: bool,
) -> None:
    contract_issues = validate_manifest_contract(manifest)
    if contract_issues:
        details = "; ".join(f"{item.code}: {item.message}" for item in contract_issues)
        raise DrawioExportError(f"Refusing to write invalid artifact manifest: {details}")
    try:
        write_json_atomic(path, manifest, overwrite=overwrite)
    except RuntimeContractError as exc:
        raise DrawioExportError(str(exc)) from exc


def export_drawio(
    *,
    plan_path: Path,
    source_path: Path,
    output_dir: Path | None = None,
    formats: list[str] | None = None,
    drawio_command: str | None = None,
    manifest_path: Path | None = None,
    overwrite: bool = False,
    strict_lint: bool = False,
    timeout_seconds: int = 60,
) -> ExportResult:
    plan_path = plan_path.expanduser().resolve()
    source_path = source_path.expanduser().resolve()
    try:
        plan = read_json(plan_path)
    except RuntimeContractError as exc:
        raise DrawioExportError(str(exc)) from exc
    plan_issues = validate_render_plan_contract(plan)
    if plan_issues:
        details = "; ".join(f"{item.code}: {item.message}" for item in plan_issues)
        raise DrawioExportError(f"RenderPlan is invalid: {details}")
    if plan.get("backend") != "drawio":
        raise DrawioExportError("Draw.io exporter received a non-Draw.io RenderPlan.")
    if not source_path.is_file():
        raise DrawioExportError(f"Draw.io source does not exist: {source_path}")

    output_dir = (
        output_dir.expanduser().resolve() if output_dir is not None else plan_path.parent
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    if manifest_path is None:
        manifest_path = plan_path.parent / plan["outputs"]["manifest"]
    manifest_path = manifest_path.expanduser()
    if not manifest_path.is_absolute():
        manifest_path = output_dir / manifest_path
    manifest_path = manifest_path.resolve()
    if manifest_path.exists() and not overwrite:
        raise DrawioExportError(f"Refusing to overwrite existing manifest: {manifest_path}")

    requested_formats = formats if formats is not None else list(plan["outputs"]["formats"])
    requested_formats = list(dict.fromkeys(item.casefold() for item in requested_formats))
    unsupported = [item for item in requested_formats if item not in MEDIA_TYPES]
    if unsupported:
        raise DrawioExportError(f"Unsupported export format(s): {', '.join(unsupported)}")
    if not requested_formats:
        raise DrawioExportError("At least one export format is required.")

    command = resolve_drawio_command(drawio_command)
    version: str | None = None
    version_issue: RuntimeIssue | None = None
    if command is not None:
        version, version_issue = command_version(command)
    manifest = _base_manifest(
        plan=plan,
        plan_path=plan_path,
        source_path=source_path,
        manifest_path=manifest_path,
        command=command,
        version=version,
    )
    runtime_issues: list[RuntimeIssue] = []
    if not coverage_is_complete(plan):
        runtime_issues.append(
            RuntimeIssue(
                "ERROR",
                "export.plan.coverage_blocked",
                "FigureSpec coverage is incomplete; export is refused before invoking Draw.io Desktop.",
            )
        )
    if version_issue is not None:
        runtime_issues.append(version_issue)

    lint_report = lint_drawio(source_path)
    runtime_issues.extend(lint_report.errors)
    if strict_lint:
        runtime_issues.extend(lint_report.warnings)
    else:
        runtime_issues.extend(lint_report.warnings)
    if lint_report.errors or (strict_lint and lint_report.warnings):
        runtime_issues.append(
            RuntimeIssue(
                "ERROR",
                "export.source.lint_failed",
                "Draw.io source did not pass the required lint policy; export was not invoked.",
            )
        )

    try:
        source_root = ET.parse(source_path).getroot()
        if source_root.get("data-plan-id") != plan["plan_id"]:
            runtime_issues.append(
                RuntimeIssue(
                    "ERROR",
                    "export.source.plan_mismatch",
                    "Draw.io source plan identity does not match the supplied RenderPlan.",
                )
            )
    except (OSError, ET.ParseError):
        pass

    spec_ref = plan["figure_spec"]
    spec_path = (plan_path.parent / spec_ref["path"]).resolve()
    if not spec_path.is_file():
        runtime_issues.append(
            RuntimeIssue(
                "ERROR",
                "export.figure_spec.missing",
                f"Referenced FigureSpec is unavailable: {spec_path}",
            )
        )
    elif sha256_file(spec_path) != spec_ref["sha256"]:
        runtime_issues.append(
            RuntimeIssue(
                "ERROR",
                "export.figure_spec.hash_mismatch",
                "Referenced FigureSpec changed after the RenderPlan was created.",
            )
        )

    targets = {format_name: output_dir / f"{source_path.stem}.{format_name}" for format_name in requested_formats}
    collisions = [path for path in targets.values() if path.exists() and not overwrite]
    for collision in collisions:
        runtime_issues.append(
            RuntimeIssue(
                "ERROR",
                "export.output.exists",
                f"Refusing to overwrite existing artifact: {collision}",
            )
        )
    if command is None:
        runtime_issues.append(
            RuntimeIssue(
                "ERROR",
                "export.cli.missing",
                "Draw.io Desktop CLI is required for export. Set --drawio-command or DRAWIO_COMMAND.",
            )
        )

    if any(item.severity == "ERROR" for item in runtime_issues):
        manifest["issues"] = [_manifest_issue(item) for item in runtime_issues]
        _write_valid_manifest(manifest_path, manifest, overwrite=overwrite)
        return ExportResult(manifest_path=manifest_path, manifest=manifest)

    assert command is not None
    temporary_outputs: dict[str, Path] = {}
    invocation_failed = False
    exit_code = 0
    with tempfile.TemporaryDirectory(prefix="drawio-export-", dir=output_dir) as tmp:
        temporary_root = Path(tmp)
        for format_name in requested_formats:
            temporary_output = temporary_root / f"artifact.{format_name}"
            invocation = [
                *command,
                "--export",
                "--format",
                format_name,
                "--output",
                str(temporary_output),
                str(source_path),
            ]
            manifest["metadata"]["invocations"].append(invocation)
            try:
                completed = subprocess.run(
                    invocation,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                )
            except subprocess.TimeoutExpired:
                runtime_issues.append(
                    RuntimeIssue(
                        "ERROR",
                        "export.cli.timeout",
                        f"Draw.io export timed out after {timeout_seconds} seconds for {format_name}.",
                    )
                )
                invocation_failed = True
                exit_code = 124
                break
            except OSError as exc:
                runtime_issues.append(
                    RuntimeIssue(
                        "ERROR",
                        "export.cli.failed",
                        f"Could not execute Draw.io CLI for {format_name}: {exc}",
                    )
                )
                invocation_failed = True
                exit_code = 127
                break
            exit_code = completed.returncode
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout).strip().replace("\n", " ")
                runtime_issues.append(
                    RuntimeIssue(
                        "ERROR",
                        "export.cli.failed",
                        f"Draw.io CLI returned {completed.returncode} for {format_name}: {detail[:500]}",
                    )
                )
                invocation_failed = True
                break
            if not temporary_output.is_file():
                runtime_issues.append(
                    RuntimeIssue(
                        "ERROR",
                        "export.artifact.missing",
                        f"Draw.io CLI reported success but did not create {format_name} output.",
                    )
                )
                invocation_failed = True
                break
            if temporary_output.stat().st_size == 0:
                runtime_issues.append(
                    RuntimeIssue(
                        "ERROR",
                        "export.artifact.empty",
                        f"Draw.io CLI created an empty {format_name} output.",
                    )
                )
                invocation_failed = True
                break
            temporary_outputs[format_name] = temporary_output

        manifest["exporter"]["exit_code"] = exit_code
        if not invocation_failed and len(temporary_outputs) == len(requested_formats):
            for format_name, temporary_output in temporary_outputs.items():
                os.replace(temporary_output, targets[format_name])
            manifest["status"] = "COMPLETED"

    if manifest["status"] == "COMPLETED":
        for format_name in requested_formats:
            artifact_path = targets[format_name]
            artifact = file_reference(
                artifact_path,
                manifest_path.parent,
                MEDIA_TYPES[format_name],
            )
            artifact["format"] = format_name
            dimensions = inspect_artifact_dimensions(artifact_path, format_name)
            if dimensions is not None:
                artifact["dimensions"] = dimensions
            else:
                runtime_issues.append(
                    RuntimeIssue(
                        "WARNING",
                        "export.artifact.dimension_unreadable",
                        f"Could not read dimensions from {artifact_path.name}.",
                    )
                )
            manifest["artifacts"].append(artifact)
    else:
        manifest["status"] = "FAILED"

    manifest["issues"] = [_manifest_issue(item) for item in runtime_issues]
    _write_valid_manifest(manifest_path, manifest, overwrite=overwrite)
    return ExportResult(manifest_path=manifest_path, manifest=manifest)


def format_export_result(result: ExportResult) -> str:
    manifest = result.manifest
    lines = [
        f"[{'PASS' if result.success else 'FAIL'}] Draw.io export",
        f"Status: {manifest['status']}",
        f"Manifest: {result.manifest_path}",
    ]
    for artifact in manifest.get("artifacts", []):
        lines.append(
            f"Artifact: {artifact['format']} {artifact['path']} "
            f"({artifact['size_bytes']} bytes)"
        )
    for issue in manifest.get("issues", []):
        lines.append(f"[{issue['severity']}] {issue['code']}: {issue['message']}")
    return "\n".join(lines)
