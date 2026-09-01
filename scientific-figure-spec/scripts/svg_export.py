#!/usr/bin/env python3
"""Native SVG artifact recording with optional PNG/PDF renderer discovery."""

from __future__ import annotations

import os
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from artifact_utils import MEDIA_TYPES, file_reference, inspect_artifact_dimensions
from figure_coverage import coverage_is_complete
from figure_runtime import (
    RuntimeContractError,
    RuntimeIssue,
    command_version,
    package_version,
    read_json,
    resolve_svg_renderer_command,
    sha256_file,
    utc_now,
    validate_manifest_contract,
    validate_render_plan_contract,
    write_json_atomic,
)
from svg_lint import lint_passed, lint_svg


@dataclass(frozen=True)
class SvgRenderer:
    kind: str
    command: list[str]
    version: str | None


@dataclass
class SvgExportResult:
    manifest_path: Path
    manifest: dict[str, Any]

    @property
    def success(self) -> bool:
        return self.manifest.get("status") == "COMPLETED"


class SvgExportError(RuntimeError):
    """Raised when SVG export setup or manifest writing is unsafe."""


def _renderer_kind(command: list[str], *, explicit: bool) -> str:
    name = Path(command[0]).name.casefold()
    joined = " ".join(Path(item).name.casefold() for item in command[:2])
    if "rsvg-convert" in joined:
        return "rsvg-convert"
    if any(token in joined for token in ("chromium", "chrome")):
        return "chromium"
    if "cairosvg" in joined:
        return "cairosvg"
    return "explicit" if explicit else name


def resolve_svg_renderer(explicit: str | None = None) -> SvgRenderer | None:
    command = resolve_svg_renderer_command(explicit)
    if command is None:
        return None
    version, _ = command_version(
        command,
        capability="svg_renderer",
        label="SVG renderer",
    )
    return SvgRenderer(
        kind=_renderer_kind(command, explicit=explicit is not None),
        command=command,
        version=version,
    )


def _renderer_invocation(
    renderer: SvgRenderer,
    source_path: Path,
    output_path: Path,
    format_name: str,
    *,
    canvas: dict[str, Any],
) -> list[str]:
    if renderer.kind == "rsvg-convert":
        return [*renderer.command, "-f", format_name, "-o", str(output_path), str(source_path)]
    if renderer.kind == "cairosvg":
        return [*renderer.command, str(source_path), "-f", format_name, "-o", str(output_path)]
    if renderer.kind == "chromium":
        base = [*renderer.command, "--headless", "--disable-gpu", "--no-sandbox"]
        uri = source_path.resolve().as_uri()
        if format_name == "png":
            return [
                *base,
                f"--window-size={int(canvas['width'])},{int(canvas['height'])}",
                f"--screenshot={output_path}",
                uri,
            ]
        return [*base, "--no-pdf-header-footer", f"--print-to-pdf={output_path}", uri]
    return [
        *renderer.command,
        "--input",
        str(source_path),
        "--output",
        str(output_path),
        "--format",
        format_name,
    ]


def _manifest_issue(issue: RuntimeIssue) -> dict[str, str]:
    return {"severity": issue.severity, "code": issue.code, "message": issue.message}


def _base_manifest(
    *,
    plan: dict[str, Any],
    plan_path: Path,
    source_path: Path,
    manifest_path: Path,
    renderer: SvgRenderer | None,
) -> dict[str, Any]:
    base = manifest_path.parent
    return {
        "schema_version": "1.0",
        "run_id": f"{plan['plan_id']}-export",
        "status": "BLOCKED",
        "plan": file_reference(plan_path, base, "application/json"),
        "source": file_reference(source_path, base, "image/svg+xml"),
        "exporter": {
            "backend": "svg",
            "command": renderer.command if renderer else [],
            "version": (
                renderer.version
                if renderer
                else f"scientific-figure-skills/{package_version()}"
            ),
            "exit_code": 0 if renderer is None else None,
        },
        "artifacts": [],
        "issues": [],
        "created_at": utc_now(),
        "metadata": {
            "native_svg_is_editable_source": True,
            "renderer_kind": renderer.kind if renderer else None,
            "invocations": [],
        },
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
        raise SvgExportError(f"Refusing to write invalid artifact manifest: {details}")
    try:
        write_json_atomic(path, manifest, overwrite=overwrite)
    except RuntimeContractError as exc:
        raise SvgExportError(str(exc)) from exc


def _artifact_record(path: Path, base: Path, format_name: str) -> dict[str, Any]:
    record = file_reference(path, base, MEDIA_TYPES[format_name])
    record["format"] = format_name
    dimensions = inspect_artifact_dimensions(path, format_name)
    if dimensions is not None:
        record["dimensions"] = dimensions
    return record


def export_svg(
    *,
    plan_path: Path,
    source_path: Path,
    output_dir: Path | None = None,
    formats: list[str] | None = None,
    renderer_command: str | None = None,
    manifest_path: Path | None = None,
    overwrite: bool = False,
    strict_lint: bool = False,
    timeout_seconds: int = 60,
) -> SvgExportResult:
    plan_path = plan_path.expanduser().resolve()
    source_path = source_path.expanduser().resolve()
    try:
        plan = read_json(plan_path)
    except RuntimeContractError as exc:
        raise SvgExportError(str(exc)) from exc
    plan_issues = validate_render_plan_contract(plan)
    if plan_issues:
        details = "; ".join(f"{item.code}: {item.message}" for item in plan_issues)
        raise SvgExportError(f"RenderPlan is invalid: {details}")
    if plan.get("backend") != "svg":
        raise SvgExportError("Native SVG exporter received a non-SVG RenderPlan.")
    if not source_path.is_file():
        raise SvgExportError(f"Native SVG source does not exist: {source_path}")

    output_dir = output_dir.expanduser().resolve() if output_dir else plan_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    if manifest_path is None:
        manifest_path = plan_path.parent / plan["outputs"]["manifest"]
    manifest_path = manifest_path.expanduser()
    if not manifest_path.is_absolute():
        manifest_path = output_dir / manifest_path
    manifest_path = manifest_path.resolve()
    if manifest_path.exists() and not overwrite:
        raise SvgExportError(f"Refusing to overwrite existing manifest: {manifest_path}")

    requested = formats if formats is not None else list(plan["outputs"]["formats"])
    requested = list(dict.fromkeys(item.casefold() for item in requested))
    unsupported = [item for item in requested if item not in MEDIA_TYPES]
    if unsupported:
        raise SvgExportError(f"Unsupported export format(s): {', '.join(unsupported)}")
    if not requested:
        raise SvgExportError("At least one export format is required.")

    external_formats = [item for item in requested if item != "svg"]
    renderer = resolve_svg_renderer(renderer_command) if external_formats else None
    manifest = _base_manifest(
        plan=plan,
        plan_path=plan_path,
        source_path=source_path,
        manifest_path=manifest_path,
        renderer=renderer,
    )
    runtime_issues: list[RuntimeIssue] = []
    if not coverage_is_complete(plan):
        runtime_issues.append(
            RuntimeIssue(
                "ERROR",
                "export.plan.coverage_blocked",
                "FigureSpec coverage is incomplete; export is refused.",
            )
        )
    lint_report = lint_svg(source_path, plan=plan)
    runtime_issues.extend(lint_report.errors)
    if strict_lint:
        runtime_issues.extend(lint_report.warnings)
    if lint_report.errors or (strict_lint and lint_report.warnings):
        runtime_issues.append(
            RuntimeIssue(
                "ERROR",
                "export.source.lint_failed",
                "Native SVG source did not pass the required lint policy.",
            )
        )
    try:
        source_root = ET.parse(source_path).getroot()
        if source_root.get("data-plan-id") != plan["plan_id"]:
            runtime_issues.append(
                RuntimeIssue(
                    "ERROR",
                    "export.source.plan_mismatch",
                    "Native SVG source plan identity does not match the supplied RenderPlan.",
                )
            )
    except (OSError, ET.ParseError):
        pass

    spec_ref = plan["figure_spec"]
    spec_path = (plan_path.parent / spec_ref["path"]).resolve()
    if not spec_path.is_file():
        runtime_issues.append(
            RuntimeIssue("ERROR", "export.figure_spec.missing", f"Referenced FigureSpec is unavailable: {spec_path}")
        )
    elif sha256_file(spec_path) != spec_ref["sha256"]:
        runtime_issues.append(
            RuntimeIssue("ERROR", "export.figure_spec.hash_mismatch", "Referenced FigureSpec changed after the RenderPlan was created.")
        )

    if external_formats and renderer is None:
        runtime_issues.append(
            RuntimeIssue(
                "ERROR",
                "capability.svg_renderer.missing",
                "PNG/PDF export requires rsvg-convert, Chromium/Chrome, CairoSVG, or an explicit renderer command; native SVG remains available.",
            )
        )

    targets = {item: output_dir / f"{source_path.stem}.{item}" for item in external_formats}
    for target in targets.values():
        if target.exists() and not overwrite:
            runtime_issues.append(
                RuntimeIssue("ERROR", "export.output.exists", f"Refusing to overwrite existing artifact: {target}")
            )

    blocking_without_capability = [
        item for item in runtime_issues if item.code != "capability.svg_renderer.missing"
    ]
    if any(item.severity == "ERROR" for item in blocking_without_capability):
        manifest["issues"] = [_manifest_issue(item) for item in runtime_issues]
        _write_valid_manifest(manifest_path, manifest, overwrite=overwrite)
        return SvgExportResult(manifest_path=manifest_path, manifest=manifest)

    if "svg" in requested:
        manifest["artifacts"].append(
            _artifact_record(source_path, manifest_path.parent, "svg")
        )

    if external_formats and renderer is None:
        manifest["status"] = "PARTIAL" if manifest["artifacts"] else "BLOCKED"
        manifest["issues"] = [_manifest_issue(item) for item in runtime_issues]
        _write_valid_manifest(manifest_path, manifest, overwrite=overwrite)
        return SvgExportResult(manifest_path=manifest_path, manifest=manifest)

    invocation_failed = False
    exit_code = 0
    if external_formats:
        assert renderer is not None
        with tempfile.TemporaryDirectory(prefix="svg-export-", dir=output_dir) as tmp:
            temporary_root = Path(tmp)
            temporary_outputs: dict[str, Path] = {}
            for format_name in external_formats:
                temporary_output = temporary_root / f"artifact.{format_name}"
                invocation = _renderer_invocation(
                    renderer,
                    source_path,
                    temporary_output,
                    format_name,
                    canvas=plan["canvas"],
                )
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
                        RuntimeIssue("ERROR", "export.renderer.timeout", f"SVG renderer timed out after {timeout_seconds} seconds for {format_name}.")
                    )
                    invocation_failed = True
                    exit_code = 124
                    break
                except OSError as exc:
                    runtime_issues.append(
                        RuntimeIssue("ERROR", "export.renderer.failed", f"Could not execute SVG renderer for {format_name}: {exc}")
                    )
                    invocation_failed = True
                    exit_code = 127
                    break
                exit_code = completed.returncode
                if completed.returncode != 0:
                    detail = (completed.stderr or completed.stdout).strip().replace("\n", " ")
                    runtime_issues.append(
                        RuntimeIssue("ERROR", "export.renderer.failed", f"SVG renderer returned {completed.returncode} for {format_name}: {detail[:500]}")
                    )
                    invocation_failed = True
                    break
                dimensions = inspect_artifact_dimensions(temporary_output, format_name)
                if not temporary_output.is_file() or temporary_output.stat().st_size == 0:
                    runtime_issues.append(
                        RuntimeIssue("ERROR", "export.artifact.missing", f"SVG renderer did not create a non-empty {format_name} artifact.")
                    )
                    invocation_failed = True
                    break
                if dimensions is None:
                    runtime_issues.append(
                        RuntimeIssue(
                            "ERROR",
                            f"export.artifact.{format_name}_invalid",
                            f"Rendered {format_name.upper()} artifact failed header/dimension validation.",
                        )
                    )
                    invocation_failed = True
                    break
                temporary_outputs[format_name] = temporary_output
            manifest["exporter"]["exit_code"] = exit_code
            if not invocation_failed and len(temporary_outputs) == len(external_formats):
                for format_name, temporary_output in temporary_outputs.items():
                    os.replace(temporary_output, targets[format_name])
                    manifest["artifacts"].append(
                        _artifact_record(targets[format_name], manifest_path.parent, format_name)
                    )

    if invocation_failed:
        manifest["status"] = "PARTIAL" if manifest["artifacts"] else "FAILED"
    else:
        manifest["status"] = "COMPLETED"
    manifest["issues"] = [_manifest_issue(item) for item in runtime_issues]
    _write_valid_manifest(manifest_path, manifest, overwrite=overwrite)
    return SvgExportResult(manifest_path=manifest_path, manifest=manifest)


def format_export_result(result: SvgExportResult) -> str:
    manifest = result.manifest
    lines = [
        f"[{'PASS' if result.success else 'FAIL'}] Native SVG export",
        f"Status: {manifest['status']}",
        f"Manifest: {result.manifest_path}",
    ]
    for artifact in manifest.get("artifacts", []):
        lines.append(
            f"Artifact: {artifact['format']} {artifact['path']} ({artifact['size_bytes']} bytes)"
        )
    for issue in manifest.get("issues", []):
        lines.append(f"[{issue['severity']}] {issue['code']}: {issue['message']}")
    return "\n".join(lines)
