#!/usr/bin/env python3
"""Unified CLI for FigureSpec and executable figure-production sidecars.

Existing init_figures.py and validate_figure_spec.py entry points remain
supported. The ``init`` and ``validate`` commands below proxy to those scripts
without changing their arguments or exit codes.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from figure_runtime import (
    RuntimeContractError,
    format_issues,
    load_capability_registry,
    package_version,
    preflight,
    read_json,
    validate_sidecar,
)


SCRIPT_DIR = Path(__file__).resolve().parent


def proxy_existing(script_name: str, arguments: list[str]) -> int:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / script_name), *arguments],
        check=False,
    )
    return completed.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="figure.py",
        description=(
            "Unified Scientific Figure Skills CLI. FigureSpec remains schema 1.0; "
            "execution data is stored in validated sidecars."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"scientific-figure-skills {package_version()} (FigureSpec 1.0)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Expose the established compatibility proxies in top-level help. main()
    # still delegates their arguments and exit codes to the original scripts
    # before argparse processes them.
    subparsers.add_parser(
        "init",
        add_help=False,
        help="Initialize FigureSpec files via init_figures.py.",
    )
    subparsers.add_parser(
        "validate",
        add_help=False,
        help="Validate FigureSpec files via validate_figure_spec.py.",
    )

    capabilities = subparsers.add_parser(
        "capabilities",
        help="Show registered and explicitly out-of-scope capabilities.",
    )
    capabilities.add_argument("--json", action="store_true")

    preflight_parser = subparsers.add_parser(
        "preflight",
        help="Check whether a registered backend operation can run here.",
    )
    preflight_parser.add_argument("--backend", default="drawio")
    preflight_parser.add_argument(
        "--operation",
        default="render",
        choices=["plan", "author", "data_binding", "lint", "export", "inspect", "repair", "render"],
    )
    preflight_parser.add_argument(
        "--drawio-command",
        default=None,
        help="Executable path or command prefix; also configurable with DRAWIO_COMMAND.",
    )
    preflight_parser.add_argument(
        "--svg-renderer-command",
        default=None,
        help="Optional explicit SVG→PNG/PDF renderer command.",
    )
    preflight_parser.add_argument("--json", action="store_true")

    validate = subparsers.add_parser(
        "validate-sidecar",
        help="Validate a RenderPlan, PlotPlan, artifact manifest, or QA report.",
    )
    validate.add_argument("kind", choices=["render-plan", "plot-plan", "manifest", "qa"])
    validate.add_argument("path")
    validate.add_argument("--json", action="store_true")

    plan = subparsers.add_parser(
        "plan",
        help="Derive a diagram RenderPlan or conservative PlotPlan scaffold from FigureSpec.",
    )
    plan.add_argument("figure_spec")
    plan.add_argument(
        "--backend",
        required=True,
        choices=["drawio", "svg", "matplotlib"],
        help="Explicit backend selection; no backend is selected by default.",
    )
    plan.add_argument("--output", required=True)
    plan.add_argument(
        "--data",
        dest="data_paths",
        action="append",
        help="Authoritative local CSV/TSV/JSON-records input for a Matplotlib scaffold; repeat as needed.",
    )
    plan.add_argument("--strict", action="store_true")
    plan.add_argument("--force", action="store_true")

    author = subparsers.add_parser(
        "author",
        help="Author editable diagram source or a reproducible PlotPlan runner.",
    )
    author.add_argument("render_plan")
    author.add_argument("--output", default=None)
    author.add_argument("--force", action="store_true")

    lint = subparsers.add_parser(
        "lint",
        help="Lint backend source structure, editability, and geometry.",
    )
    lint.add_argument("source")
    lint.add_argument("--plan", default=None)
    lint.add_argument("--strict", action="store_true")
    lint.add_argument("--json", action="store_true")

    export = subparsers.add_parser(
        "export",
        help="Record/export backend artifacts and write an artifact manifest.",
    )
    export.add_argument("source")
    export.add_argument("--plan", required=True)
    export.add_argument("--output-dir", default=None)
    export.add_argument(
        "--format",
        dest="formats",
        action="append",
        choices=["svg", "pdf", "png"],
        help="Repeat to select formats; defaults to the selected plan outputs.formats.",
    )
    export.add_argument("--drawio-command", default=None)
    export.add_argument("--svg-renderer-command", default=None)
    export.add_argument("--manifest", default=None)
    export.add_argument("--strict-lint", action="store_true")
    export.add_argument("--timeout", type=int, default=60)
    export.add_argument("--force", action="store_true")
    export.add_argument("--json", action="store_true")

    inspect = subparsers.add_parser(
        "inspect",
        help="Inspect final-size artifacts and machine-checkable semantic assertions.",
    )
    inspect.add_argument("source")
    inspect.add_argument("--plan", required=True)
    inspect.add_argument("--manifest", required=True)
    inspect.add_argument("--qa", default=None)
    inspect.add_argument("--force", action="store_true")
    inspect.add_argument("--json", action="store_true")

    repair = subparsers.add_parser(
        "repair",
        help="Apply only bounded local repairs and preserve the input source.",
    )
    repair.add_argument("source")
    repair.add_argument("--plan", default=None)
    repair.add_argument("--output", default=None)
    repair.add_argument("--dry-run", action="store_true")
    repair.add_argument("--force", action="store_true")
    repair.add_argument("--json", action="store_true")

    render = subparsers.add_parser(
        "render",
        help="Run plan → author → lint → export → inspect in one local process.",
    )
    render.add_argument(
        "figure_spec",
        help="FigureSpec Markdown for diagram backends; completed PlotPlan JSON for Matplotlib.",
    )
    render.add_argument(
        "--backend",
        required=True,
        choices=["drawio", "svg", "matplotlib"],
        help="Explicit selection; no backend is globally defaulted.",
    )
    render.add_argument("--work-dir", required=True)
    render.add_argument("--drawio-command", default=None)
    render.add_argument("--svg-renderer-command", default=None)
    render.add_argument(
        "--format",
        dest="formats",
        action="append",
        choices=["svg", "pdf", "png"],
    )
    render.add_argument("--allow-spec-warnings", action="store_true")
    render.add_argument("--allow-lint-warnings", action="store_true")
    render.add_argument("--timeout", type=int, default=60)
    render.add_argument("--force", action="store_true")
    render.add_argument("--json", action="store_true")

    return parser


def print_capabilities(*, as_json: bool) -> int:
    registry = load_capability_registry()
    if as_json:
        print(json.dumps(registry, indent=2, ensure_ascii=False))
        return 0

    print("Scientific Figure Skills")
    default = registry.get("default_backend")
    print(f"Default backend: {default if default is not None else '(none)'}")
    for name, backend in registry.get("backends", {}).items():
        marker = "yes" if backend.get("default") else "no"
        print(f"\n{name} (default: {marker})")
        for operation, detail in backend.get("operations", {}).items():
            availability = detail.get("available")
            print(
                f"  {operation}: {detail.get('implementation')} "
                f"[available={availability}]"
            )
    print("\nExplicitly out of scope for the bundled execution adapter:")
    for name in registry.get("out_of_scope", {}):
        print(f"  - {name}")
    return 0


def print_preflight(args: argparse.Namespace) -> int:
    result = preflight(
        backend=args.backend,
        operation=args.operation,
        drawio_command=args.drawio_command,
        svg_renderer_command=args.svg_renderer_command,
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        label = "READY" if result["ready"] else "BLOCKED"
        print(f"[{label}] {args.backend}:{args.operation}")
        cli = result.get("drawio_cli")
        if cli:
            print(f"Draw.io command: {' '.join(cli['command'])}")
            print(f"Draw.io version: {cli.get('version') or '(unconfirmed)'}")
        renderer = result.get("svg_renderer")
        if renderer:
            print(f"SVG renderer: {' '.join(renderer['command'])}")
            print(f"SVG renderer version: {renderer.get('version') or '(unconfirmed)'}")
        matplotlib_info = result.get("matplotlib")
        if matplotlib_info:
            print(f"Python: {matplotlib_info.get('python')}")
            print(f"Matplotlib: {matplotlib_info.get('version') or '(unconfirmed)'}")
        for issue in result.get("issues", []):
            print(f"[{issue['severity']}] {issue['code']}: {issue['message']}")
    return 0 if result["ready"] else 2


def print_sidecar_validation(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser().resolve()
    try:
        value = read_json(path)
        issues = validate_sidecar(args.kind, value)
    except RuntimeContractError as exc:
        if args.json:
            print(
                json.dumps(
                    {
                        "kind": args.kind,
                        "path": str(path),
                        "passed": False,
                        "issues": [
                            {
                                "severity": "ERROR",
                                "code": "schema.file.invalid",
                                "message": str(exc),
                            }
                        ],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
        else:
            print(f"[ERROR] schema.file.invalid: {exc}", file=sys.stderr)
        return 2

    passed = not any(issue.severity == "ERROR" for issue in issues)
    if args.json:
        print(
            json.dumps(
                {
                    "kind": args.kind,
                    "path": str(path),
                    "passed": passed,
                    "issues": [issue.as_dict() for issue in issues],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(f"[{'PASS' if passed else 'FAIL'}] {path}")
        if issues:
            print(format_issues(issues))
        else:
            print("No issues found.")
    return 0 if passed else 1


def create_plan(args: argparse.Namespace) -> int:
    if args.backend == "matplotlib":
        from plot_plan import PlotPlanError, create_plot_plan_file

        try:
            plan = create_plot_plan_file(
                Path(args.figure_spec),
                Path(args.output),
                data_paths=[Path(item) for item in args.data_paths or []],
                strict=args.strict,
                overwrite=args.force,
            )
        except PlotPlanError as exc:
            print(f"PlotPlan error: {exc}", file=sys.stderr)
            return 2
    else:
        from diagram_plan import DiagramPlanError, create_render_plan_file

        try:
            plan = create_render_plan_file(
                Path(args.figure_spec),
                Path(args.output),
                backend=args.backend,
                strict=args.strict,
                overwrite=args.force,
            )
        except DiagramPlanError as exc:
            print(f"RenderPlan error: {exc}", file=sys.stderr)
            return 2
    output = Path(args.output).expanduser().resolve()
    plan_kind = "PlotPlan scaffold" if args.backend == "matplotlib" else "RenderPlan"
    print(f"Created {plan_kind}: {output}")
    print(f"Backend: {plan['backend']} (explicit selection)")
    if args.backend == "matplotlib":
        print(f"Data sources: {len(plan['data_sources'])}")
        print(f"Panels: {len(plan['panels'])}")
    else:
        print(f"Elements: {len(plan['elements'])}")
        print(f"Connectors: {len(plan['connectors'])}")
    coverage = plan["spec_coverage"]
    print(
        "FigureSpec coverage: "
        f"{coverage['status']} "
        f"({coverage['summary']['unresolved_total']} unresolved)"
    )
    if coverage["status"] != "COMPLETE" and args.backend != "matplotlib":
        for section, code in (
            ("must_show", "scientific.coverage.must_show_unmapped"),
            ("relationships", "scientific.coverage.relationship_unmapped"),
        ):
            for item in coverage[section]:
                if item["status"] == "UNRESOLVED":
                    print(
                        f"[BLOCKING] {code}: {item['source_ref']}: "
                        f"{item['source_text']} ({item.get('reason', 'unresolved')})"
                    )
        return 1
    if args.backend == "matplotlib":
        print(
            "[BLOCKING] PlotPlan scaffold requires explicit panel, series, axis, "
            "and data-binding decisions before rendering."
        )
        return 1
    return 0


def author_source(args: argparse.Namespace) -> int:
    plan_path = Path(args.render_plan)
    try:
        plan = read_json(plan_path.expanduser().resolve())
    except RuntimeContractError as exc:
        print(f"Source authoring error: {exc}", file=sys.stderr)
        return 2
    backend = plan.get("backend")
    if backend == "drawio":
        from drawio_backend import DrawioBackendError as BackendError
        from drawio_backend import author_from_plan_file
    elif backend == "svg":
        from svg_backend import SvgBackendError as BackendError
        from svg_backend import author_from_plan_file
    elif backend == "matplotlib":
        from matplotlib_backend import MatplotlibBackendError as BackendError
        from matplotlib_backend import author_plot_source

        def author_from_plan_file(
            selected_plan: Path,
            selected_output: Path | None,
            *,
            overwrite: bool,
        ) -> Path:
            return author_plot_source(
                selected_plan,
                selected_output,
                overwrite=overwrite,
            )
    else:
        print(f"Source authoring error: unsupported backend {backend!r}", file=sys.stderr)
        return 2
    output = Path(args.output) if args.output else None
    try:
        created = author_from_plan_file(
            plan_path,
            output,
            overwrite=args.force,
        )
    except (BackendError, KeyError, TypeError) as exc:
        print(f"Source authoring error: {exc}", file=sys.stderr)
        return 2
    print(f"Created {backend} source: {created}")
    print(
        "Format: native uncompressed mxGraph XML"
        if backend == "drawio"
        else "Format: native semantic SVG with live text"
        if backend == "svg"
        else "Format: reproducible hash-pinned Python PlotPlan runner"
    )
    return 0


def lint_source(args: argparse.Namespace) -> int:
    source_path = Path(args.source)
    plan = Path(args.plan) if args.plan else None
    if source_path.suffix.casefold() == ".drawio":
        from drawio_lint import format_lint_report, lint_drawio, lint_passed

        report = lint_drawio(source_path)
    elif source_path.suffix.casefold() == ".svg":
        from svg_lint import format_lint_report, lint_passed, lint_svg

        report = lint_svg(source_path, plan=plan)
    elif source_path.name.endswith(".plot.py"):
        from matplotlib_backend import (
            format_plot_lint_report,
            lint_plot_source,
            plot_source_lint_passed,
        )

        report = lint_plot_source(source_path, plan_path=plan)
        if args.json:
            print(json.dumps(report.as_dict(strict=args.strict), indent=2, ensure_ascii=False))
        else:
            print(format_plot_lint_report(report, strict=args.strict))
        return 0 if plot_source_lint_passed(report, strict=args.strict) else 1
    else:
        print(f"Lint error: unsupported source extension {source_path.suffix!r}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report.as_dict(strict=args.strict), indent=2, ensure_ascii=False))
    else:
        print(format_lint_report(report, strict=args.strict))
    return 0 if lint_passed(report, strict=args.strict) else 1


def export_source(args: argparse.Namespace) -> int:
    plan_path = Path(args.plan)
    try:
        plan = read_json(plan_path.expanduser().resolve())
    except RuntimeContractError as exc:
        print(f"Export error: {exc}", file=sys.stderr)
        return 2
    backend = plan.get("backend")
    export_error: type[Exception]
    try:
        if backend == "drawio":
            from drawio_export import DrawioExportError, export_drawio, format_export_result

            export_error = DrawioExportError

            result = export_drawio(
                plan_path=plan_path,
                source_path=Path(args.source),
                output_dir=Path(args.output_dir) if args.output_dir else None,
                formats=args.formats,
                drawio_command=args.drawio_command,
                manifest_path=Path(args.manifest) if args.manifest else None,
                overwrite=args.force,
                strict_lint=args.strict_lint,
                timeout_seconds=args.timeout,
            )
        elif backend == "svg":
            from svg_export import SvgExportError, export_svg, format_export_result

            export_error = SvgExportError

            result = export_svg(
                plan_path=plan_path,
                source_path=Path(args.source),
                output_dir=Path(args.output_dir) if args.output_dir else None,
                formats=args.formats,
                renderer_command=args.svg_renderer_command,
                manifest_path=Path(args.manifest) if args.manifest else None,
                overwrite=args.force,
                strict_lint=args.strict_lint,
                timeout_seconds=args.timeout,
            )
        elif backend == "matplotlib":
            from matplotlib_backend import (
                MatplotlibBackendError,
                export_matplotlib,
                format_export_result,
            )

            export_error = MatplotlibBackendError
            result = export_matplotlib(
                plan_path=plan_path,
                source_path=Path(args.source),
                output_dir=Path(args.output_dir) if args.output_dir else None,
                formats=args.formats,
                manifest_path=Path(args.manifest) if args.manifest else None,
                overwrite=args.force,
                strict_lint=args.strict_lint,
                timeout_seconds=args.timeout,
            )
        else:
            print(f"Export error: unsupported backend {backend!r}", file=sys.stderr)
            return 2
    except export_error as exc:
        print(f"Export error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(
            json.dumps(
                {
                    "manifest_path": str(result.manifest_path),
                    "manifest": result.manifest,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(format_export_result(result))
    return 0 if result.success else 1


def inspect_figure_artifacts(args: argparse.Namespace) -> int:
    try:
        plan = read_json(Path(args.plan).expanduser().resolve())
    except RuntimeContractError as exc:
        print(f"Figure inspection error: {exc}", file=sys.stderr)
        return 2
    if isinstance(plan, dict) and plan.get("backend") == "matplotlib":
        from plot_inspect import (
            PlotInspectionError as InspectionError,
            format_inspection_result,
            inspect_plot as inspect_selected,
        )
    else:
        from figure_inspect import (
            FigureInspectionError as InspectionError,
            format_inspection_result,
            inspect_figure as inspect_selected,
        )

    try:
        result = inspect_selected(
            plan_path=Path(args.plan),
            source_path=Path(args.source),
            manifest_path=Path(args.manifest),
            qa_path=Path(args.qa) if args.qa else None,
            overwrite=args.force,
        )
    except InspectionError as exc:
        print(f"Figure inspection error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(
            json.dumps(
                {"qa_path": str(result.qa_path), "report": result.report},
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(format_inspection_result(result))
    return 0 if result.passed else 1


def repair_drawio_source(args: argparse.Namespace) -> int:
    source = Path(args.source)
    if source.suffix.casefold() == ".svg" or source.name.endswith(".plot.py"):
        backend_label = "native SVG" if source.suffix.casefold() == ".svg" else "Matplotlib"
        print(
            f"Repair error: capability.operation.unavailable: {backend_label} repair is not implemented; edit the source plan and rerun.",
            file=sys.stderr,
        )
        return 2
    from drawio_repair import DrawioRepairError, format_repair_result, repair_drawio

    try:
        result = repair_drawio(
            source_path=Path(args.source),
            output_path=Path(args.output) if args.output else None,
            plan_path=Path(args.plan) if args.plan else None,
            dry_run=args.dry_run,
            overwrite=args.force,
        )
    except DrawioRepairError as exc:
        print(f"Draw.io repair error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result.as_dict(), indent=2, ensure_ascii=False))
    else:
        print(format_repair_result(result))
    return 0 if result.safe_complete else 1


def render_figure(args: argparse.Namespace) -> int:
    if args.backend == "matplotlib":
        from matplotlib_backend import MatplotlibBackendError
        from plot_binding import PlotBindingError
        from plot_inspect import PlotInspectionError
        from plot_pipeline import (
            PlotPipelineError,
            format_pipeline_result,
            run_plot_pipeline,
        )

        try:
            result = run_plot_pipeline(
                plot_plan_path=Path(args.figure_spec),
                work_dir=Path(args.work_dir),
                formats=args.formats,
                strict_lint=not args.allow_lint_warnings,
                overwrite=args.force,
                timeout_seconds=args.timeout,
            )
        except (
            PlotPipelineError,
            PlotBindingError,
            MatplotlibBackendError,
            PlotInspectionError,
            RuntimeContractError,
        ) as exc:
            print(f"Plot pipeline error: {exc}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(result.as_dict(), indent=2, ensure_ascii=False))
        else:
            print(format_pipeline_result(result))
        return 0 if result.success else 1

    from diagram_plan import DiagramPlanError
    from drawio_backend import DrawioBackendError
    from drawio_export import DrawioExportError
    from figure_inspect import FigureInspectionError
    from figure_pipeline import (
        FigurePipelineError,
        format_pipeline_result,
        run_figure_pipeline,
    )
    from svg_backend import SvgBackendError
    from svg_export import SvgExportError

    try:
        result = run_figure_pipeline(
            figure_spec_path=Path(args.figure_spec),
            work_dir=Path(args.work_dir),
            backend=args.backend,
            drawio_command=args.drawio_command,
            svg_renderer_command=args.svg_renderer_command,
            formats=args.formats,
            strict_spec=not args.allow_spec_warnings,
            strict_lint=not args.allow_lint_warnings,
            overwrite=args.force,
            timeout_seconds=args.timeout,
        )
    except (
        FigurePipelineError,
        DiagramPlanError,
        DrawioBackendError,
        DrawioExportError,
        SvgBackendError,
        SvgExportError,
        FigureInspectionError,
        RuntimeContractError,
    ) as exc:
        print(f"Figure pipeline error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result.as_dict(), indent=2, ensure_ascii=False))
    else:
        print(format_pipeline_result(result))
    return 0 if result.success else 1


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)

    # Compatibility proxies deliberately parse no arguments here. This keeps
    # every existing option and exit code owned by the original command.
    if raw and raw[0] == "validate":
        return proxy_existing("validate_figure_spec.py", raw[1:])
    if raw and raw[0] == "init":
        return proxy_existing("init_figures.py", raw[1:])

    try:
        parser = build_parser()
    except RuntimeContractError as exc:
        print(f"Runtime contract error: {exc}", file=sys.stderr)
        return 2
    args = parser.parse_args(raw)
    try:
        if args.command == "capabilities":
            return print_capabilities(as_json=args.json)
        if args.command == "preflight":
            return print_preflight(args)
        if args.command == "validate-sidecar":
            return print_sidecar_validation(args)
        if args.command == "plan":
            return create_plan(args)
        if args.command == "author":
            return author_source(args)
        if args.command == "lint":
            return lint_source(args)
        if args.command == "export":
            return export_source(args)
        if args.command == "inspect":
            return inspect_figure_artifacts(args)
        if args.command == "repair":
            return repair_drawio_source(args)
        if args.command == "render":
            return render_figure(args)
    except RuntimeContractError as exc:
        print(f"Runtime contract error: {exc}", file=sys.stderr)
        return 2
    parser.error(f"Unhandled command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
