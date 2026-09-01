#!/usr/bin/env python3
"""Validate FigureSpec v1.0 Markdown files.

The validator checks structure, readiness, identity, status, source-binding
warnings, and recorded output paths. It does not determine scientific truth,
visual quality, or genuine human approval.

Examples
--------

    python validate_figure_spec.py figures/F001-method-overview.md
    python validate_figure_spec.py figures/
    python validate_figure_spec.py --recursive paper/
    python validate_figure_spec.py --strict figures/
    python validate_figure_spec.py --json figures/
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SPEC_VERSION = "1.0"
ALLOWED_STATUSES = {"DRAFT", "READY", "RENDERED", "FINAL"}

REQUIRED_TOP_LEVEL_HEADINGS = [
    "Scientific Figure Specification",
    "1. Figure Identity",
    "2. Scientific Purpose",
    "3. Required Content",
    "4. Scientific Structure & Relationships",
    "5. Figure Design",
    "6. Visual & Content Constraints",
    "7. References & Rendering Requirements",
]

REQUIRED_SUBHEADINGS_BY_SECTION = {
    "2. Scientific Purpose": [
        "2.1 Core Message",
        "2.2 Intended Reader Takeaway",
        "2.3 Role in the Paper",
    ],
    "3. Required Content": [
        "3.1 Must Show",
        "3.2 Exact Scientific Content",
        "3.3 Source Binding",
        "3.4 Optional / Removable Content",
        "3.5 Assumptions / Open Questions",
    ],
    "4. Scientific Structure & Relationships": [
        "4.1 Relationships",
    ],
    "5. Figure Design": [
        "5.1 Reading Order",
        "5.2 Composition",
        "5.3 Primary Visual Anchor",
        "5.4 Information Hierarchy",
        "5.5 Simplification & Redundancy",
    ],
    "6. Visual & Content Constraints": [
        "6.1 Visual Semantics",
        "6.2 Required Figure Labels",
        "6.3 Must Not Imply / Avoid",
    ],
    "7. References & Rendering Requirements": [
        "7.1 References",
        "7.2 Cross-Figure Consistency",
        "7.3 Rendering Requirements",
    ],
}

REQUIRED_SUBHEADINGS = [
    title
    for titles in REQUIRED_SUBHEADINGS_BY_SECTION.values()
    for title in titles
]

REQUIRED_HIERARCHY_HEADINGS = ["Primary", "Secondary", "Supporting"]

FRONT_MATTER_RE = re.compile(
    r"\A---\r?\n(?P<body>.*?)\r?\n---(?:\r?\n|\Z)",
    re.DOTALL,
)
FIGURE_ID_RE = re.compile(r"^F\d{3,}$")
FILENAME_FIGURE_ID_RE = re.compile(r"^(?P<figure_id>F\d{3,})(?:-|\.md$)")
HEADING_RE = re.compile(r"^(?P<marks>#{1,6})\s+(?P<title>.+?)\s*$")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
EMPTY_LIST_ITEM_RE = re.compile(r"^\s*[-*+]\s*$")
LIST_PREFIX_RE = re.compile(r"^\s*[-*+]\s+")
URL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
FIELD_RE_TEMPLATE = r"(?mi)^\*\*{field}:\*\*\s*(?P<value>.*?)\s*$"
NUMERIC_CONTENT_RE = re.compile(r"(?<![A-Za-z])\d[\d,._%+\-]*")

PLACEHOLDER_VALUES = {
    "none",
    "none specified",
    "not applicable",
    "n/a",
    "tbd",
    "undecided",
    "unknown",
}


class ValidationSetupError(RuntimeError):
    """Raised when validation cannot be started safely."""


@dataclass(frozen=True)
class Heading:
    level: int
    title: str
    line_index: int


@dataclass(frozen=True)
class Issue:
    severity: str
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }


@dataclass
class Report:
    path: Path
    issues: list[Issue]

    @property
    def errors(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity == "ERROR"]

    @property
    def warnings(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity == "WARNING"]

    def add_error(self, code: str, message: str) -> None:
        self.issues.append(Issue("ERROR", code, message))

    def add_warning(self, code: str, message: str) -> None:
        self.issues.append(Issue("WARNING", code, message))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate FigureSpec v1.0 Markdown files."
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="FigureSpec files or directories containing F*.md files.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Search supplied directories recursively.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as validation failures.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="Optional project root for resolving relative artifact paths.",
    )
    return parser.parse_args()


def parse_yaml_scalar(value: str) -> Any:
    value = value.strip()
    if value in {"null", "Null", "NULL", "~", ""}:
        return None
    if value.startswith('"') and value.endswith('"'):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid double-quoted YAML scalar: {value}") from exc
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return value


def parse_canonical_frontmatter(body: str) -> dict[str, Any]:
    """Parse the small mapping-only YAML subset used by the template."""
    result: dict[str, Any] = {}
    current_parent: str | None = None

    for line_number, raw_line in enumerate(body.splitlines(), start=2):
        if "\t" in raw_line:
            raise ValueError(
                f"Tabs are not supported in frontmatter (line {line_number})."
            )
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if indent == 0:
            match = re.match(
                r"^(?P<key>[A-Za-z0-9_-]+)\s*:\s*(?P<value>.*)$",
                raw_line,
            )
            if match is None:
                raise ValueError(
                    f"Unsupported frontmatter syntax at line {line_number}: {raw_line}"
                )
            key = match.group("key")
            if key in result:
                raise ValueError(f"Duplicate frontmatter key: {key}")
            value_text = match.group("value")
            if value_text.strip() == "":
                result[key] = {}
                current_parent = key
            else:
                result[key] = parse_yaml_scalar(value_text)
                current_parent = None
            continue

        if indent == 2 and current_parent is not None:
            match = re.match(
                r"^\s{2}(?P<key>[A-Za-z0-9_-]+)\s*:\s*(?P<value>.*)$",
                raw_line,
            )
            if match is None:
                raise ValueError(
                    f"Unsupported nested syntax at line {line_number}: {raw_line}"
                )
            parent = result[current_parent]
            if not isinstance(parent, dict):
                raise ValueError(f"Frontmatter parent is not a mapping: {current_parent}")
            key = match.group("key")
            if key in parent:
                raise ValueError(f"Duplicate frontmatter key: {current_parent}.{key}")
            parent[key] = parse_yaml_scalar(match.group("value"))
            continue

        raise ValueError(
            f"Unsupported frontmatter indentation at line {line_number}: {raw_line}"
        )

    return result


def extract_frontmatter(text: str) -> tuple[dict[str, Any] | None, str | None]:
    match = FRONT_MATTER_RE.match(text)
    if match is None:
        return None, "File must begin with YAML frontmatter delimited by '---'."
    try:
        return parse_canonical_frontmatter(match.group("body")), None
    except ValueError as exc:
        return None, str(exc)


def collect_headings(text: str) -> list[Heading]:
    headings: list[Heading] = []
    in_fence = False
    fence_marker: str | None = None

    for index, line in enumerate(text.splitlines()):
        stripped = line.lstrip()
        marker = None
        if stripped.startswith("```"):
            marker = "```"
        elif stripped.startswith("~~~"):
            marker = "~~~"

        if marker is not None:
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif fence_marker == marker:
                in_fence = False
                fence_marker = None
            continue

        if in_fence:
            continue

        match = HEADING_RE.match(line)
        if match:
            headings.append(
                Heading(
                    level=len(match.group("marks")),
                    title=match.group("title").strip(),
                    line_index=index,
                )
            )
    return headings


def heading_lookup(headings: Iterable[Heading]) -> dict[str, list[Heading]]:
    result: dict[str, list[Heading]] = {}
    for heading in headings:
        result.setdefault(heading.title, []).append(heading)
    return result


def section_body(
    text: str,
    headings: list[Heading],
    title: str,
) -> str | None:
    matching = [heading for heading in headings if heading.title == title]
    if len(matching) != 1:
        return None

    target = matching[0]
    lines = text.splitlines()
    end_index = len(lines)
    for heading in headings:
        if heading.line_index > target.line_index and heading.level <= target.level:
            end_index = heading.line_index
            break
    return "\n".join(lines[target.line_index + 1 : end_index])


def normalize_content_line(line: str) -> str:
    line = LIST_PREFIX_RE.sub("", line.strip())
    line = re.sub(r"^\*\*(.*?)\*\*\s*$", r"\1", line).strip()
    return line


def meaningful_content(body: str | None, *, allow_placeholders: bool = False) -> str:
    if body is None:
        return ""

    cleaned = HTML_COMMENT_RE.sub("", body)
    meaningful_lines: list[str] = []

    for line in cleaned.splitlines():
        stripped = line.strip()
        if not stripped or EMPTY_LIST_ITEM_RE.match(stripped):
            continue
        if stripped.startswith("#"):
            continue

        normalized = normalize_content_line(stripped)
        if not normalized:
            continue
        if normalized.endswith(":") and normalized.startswith("**"):
            continue
        if not allow_placeholders and normalized.lower() in PLACEHOLDER_VALUES:
            continue
        meaningful_lines.append(stripped)

    return "\n".join(meaningful_lines).strip()


def extract_bold_field(body: str | None, field: str) -> str | None:
    if body is None:
        return None
    pattern = re.compile(FIELD_RE_TEMPLATE.format(field=re.escape(field)))
    match = pattern.search(body)
    if match is None:
        return None
    value = match.group("value").strip()
    return value or None


def validate_metadata(
    report: Report,
    metadata: dict[str, Any],
) -> tuple[str | None, str | None]:
    for key in (
        "spec_version",
        "figure_id",
        "working_title",
        "status",
        "outputs",
    ):
        if key not in metadata:
            report.add_error("metadata.missing", f"Missing frontmatter field: {key}")

    version = metadata.get("spec_version")
    if version != SPEC_VERSION:
        report.add_error(
            "metadata.spec_version",
            f"Expected spec_version {SPEC_VERSION!r}, found {version!r}.",
        )

    figure_id = metadata.get("figure_id")
    if not isinstance(figure_id, str) or not FIGURE_ID_RE.fullmatch(figure_id):
        report.add_error(
            "metadata.figure_id",
            "figure_id must match F followed by at least three digits, e.g. F001.",
        )
        normalized_figure_id = None
    else:
        normalized_figure_id = figure_id

    title = metadata.get("working_title")
    if not isinstance(title, str) or not title.strip():
        report.add_error(
            "metadata.working_title",
            "working_title must be a non-empty string.",
        )

    status = metadata.get("status")
    if not isinstance(status, str):
        report.add_error("metadata.status", "status must be a string.")
        normalized_status = None
    else:
        normalized_status = status.upper()
        if normalized_status not in ALLOWED_STATUSES:
            report.add_error(
                "metadata.status",
                f"Invalid status {status!r}. Allowed: {', '.join(sorted(ALLOWED_STATUSES))}",
            )
        elif status != normalized_status:
            report.add_warning(
                "metadata.status_casing",
                f"Status {status!r} is non-canonical; use {normalized_status!r}.",
            )

    outputs = metadata.get("outputs")
    if not isinstance(outputs, dict):
        report.add_error("metadata.outputs", "outputs must be a nested mapping.")
    else:
        for key in ("source", "vector", "preview"):
            if key not in outputs:
                report.add_error(
                    "metadata.output_field",
                    f"Missing outputs.{key}.",
                )

    return normalized_figure_id, normalized_status


def validate_filename_identity(report: Report, figure_id: str | None) -> None:
    if figure_id is None:
        return
    match = FILENAME_FIGURE_ID_RE.match(report.path.name)
    if match is None:
        report.add_warning(
            "filename.id_missing",
            "Filename does not begin with an ID such as F001-.",
        )
        return
    filename_id = match.group("figure_id")
    if filename_id != figure_id:
        report.add_error(
            "filename.id_mismatch",
            f"Filename starts with {filename_id}, but frontmatter uses {figure_id}.",
        )


def nearest_parent_heading(
    headings: list[Heading],
    target: Heading,
    parent_level: int,
) -> Heading | None:
    """Return the nearest enclosing heading at the requested level."""
    for heading in reversed(headings):
        if heading.line_index >= target.line_index:
            continue
        if heading.level == parent_level:
            return heading
        if heading.level < parent_level:
            return None
    return None


def validate_headings(report: Report, headings: list[Heading]) -> None:
    lookup = heading_lookup(headings)
    canonical_top_level = set(REQUIRED_TOP_LEVEL_HEADINGS)

    for title in REQUIRED_TOP_LEVEL_HEADINGS:
        matches = lookup.get(title, [])
        if not matches:
            report.add_error("structure.heading_missing", f"Missing heading: {title}")
        elif len(matches) > 1:
            report.add_error("structure.heading_duplicate", f"Duplicate heading: {title}")
        elif matches[0].level != 1:
            report.add_error(
                "structure.heading_level",
                f"Heading {title!r} must use level 1 (#).",
            )

    for heading in headings:
        if heading.level == 1 and heading.title not in canonical_top_level:
            report.add_error(
                "structure.unexpected_top_level_heading",
                f"Unexpected top-level heading: {heading.title}",
            )

    ordered_top_level: list[Heading] = []
    for title in REQUIRED_TOP_LEVEL_HEADINGS:
        matches = [
            heading
            for heading in lookup.get(title, [])
            if heading.level == 1
        ]
        if len(matches) == 1:
            ordered_top_level.append(matches[0])
    if len(ordered_top_level) == len(REQUIRED_TOP_LEVEL_HEADINGS):
        if [heading.line_index for heading in ordered_top_level] != sorted(
            heading.line_index for heading in ordered_top_level
        ):
            report.add_error(
                "structure.section_order",
                "Required top-level sections are not in canonical order.",
            )

    for parent_title, required_titles in REQUIRED_SUBHEADINGS_BY_SECTION.items():
        valid_children: list[Heading] = []
        for title in required_titles:
            matches = lookup.get(title, [])
            if not matches:
                report.add_error(
                    "structure.subheading_missing",
                    f"Missing subheading: {title}",
                )
                continue
            if len(matches) > 1:
                report.add_error(
                    "structure.subheading_duplicate",
                    f"Duplicate subheading: {title}",
                )
                continue

            heading = matches[0]
            if heading.level != 2:
                report.add_error(
                    "structure.subheading_level",
                    f"Subheading {title!r} must use level 2 (##).",
                )
                continue

            parent = nearest_parent_heading(headings, heading, parent_level=1)
            if parent is None or parent.title != parent_title:
                actual_parent = parent.title if parent is not None else "none"
                report.add_error(
                    "structure.subheading_parent",
                    f"Subheading {title!r} must belong to {parent_title!r}; "
                    f"found under {actual_parent!r}.",
                )
                continue

            valid_children.append(heading)

        if len(valid_children) == len(required_titles):
            positions = [heading.line_index for heading in valid_children]
            if positions != sorted(positions):
                report.add_error(
                    "structure.subheading_order",
                    f"Required subheadings under {parent_title!r} are not in "
                    "canonical order.",
                )

    valid_hierarchy_headings: list[Heading] = []
    for title in REQUIRED_HIERARCHY_HEADINGS:
        matches = lookup.get(title, [])
        if not matches:
            report.add_error(
                "structure.hierarchy_heading_missing",
                f"Missing information-hierarchy heading: {title}",
            )
        elif len(matches) != 1:
            report.add_error(
                "structure.hierarchy_heading_duplicate",
                f"Expected one hierarchy heading {title!r}.",
            )
        elif matches[0].level != 3:
            report.add_error(
                "structure.hierarchy_heading_level",
                f"Hierarchy heading {title!r} must use level 3 (###).",
            )
        else:
            heading = matches[0]
            parent = nearest_parent_heading(headings, heading, parent_level=2)
            if parent is None or parent.title != "5.4 Information Hierarchy":
                actual_parent = parent.title if parent is not None else "none"
                report.add_error(
                    "structure.hierarchy_heading_parent",
                    f"Hierarchy heading {title!r} must belong to "
                    f"'5.4 Information Hierarchy'; found under {actual_parent!r}.",
                )
            else:
                valid_hierarchy_headings.append(heading)

    if len(valid_hierarchy_headings) == len(REQUIRED_HIERARCHY_HEADINGS):
        positions = [heading.line_index for heading in valid_hierarchy_headings]
        if positions != sorted(positions):
            report.add_error(
                "structure.hierarchy_heading_order",
                "Primary, Secondary, and Supporting must appear in canonical order.",
            )


def validate_readiness(
    report: Report,
    text: str,
    headings: list[Heading],
    metadata: dict[str, Any],
    status: str | None,
) -> None:
    if status is None or status == "DRAFT":
        return

    required_sections = {
        "2.1 Core Message": "readiness.core_message",
        "3.1 Must Show": "readiness.must_show",
        "4.1 Relationships": "readiness.relationships",
        "5.1 Reading Order": "readiness.reading_order",
        "5.2 Composition": "readiness.composition",
        "5.3 Primary Visual Anchor": "readiness.primary_anchor",
        "Primary": "readiness.primary_hierarchy",
    }

    for title, code in required_sections.items():
        content = meaningful_content(section_body(text, headings, title))
        if not content:
            report.add_error(
                code,
                f"{title} must contain real content when status is {status}.",
            )

    identity_body = section_body(text, headings, "1. Figure Identity")
    primary_archetype = extract_bold_field(identity_body, "Primary Archetype")
    if not primary_archetype or primary_archetype.lower() in PLACEHOLDER_VALUES:
        report.add_warning(
            "readiness.primary_archetype",
            f"Primary Archetype is empty while status is {status}.",
        )

    for title, code in (
        ("2.2 Intended Reader Takeaway", "readiness.reader_takeaway"),
        ("2.3 Role in the Paper", "readiness.paper_role"),
        ("5.5 Simplification & Redundancy", "readiness.simplification"),
        ("6.3 Must Not Imply / Avoid", "readiness.must_not_imply"),
    ):
        if not meaningful_content(section_body(text, headings, title)):
            report.add_warning(
                code,
                f"{title} is empty while status is {status}.",
            )

    render_body = section_body(text, headings, "7.3 Rendering Requirements")
    body_intended_use = extract_bold_field(render_body, "Intended Use")
    if not body_intended_use:
        report.add_warning(
            "readiness.intended_use",
            f"Intended use is not recorded while status is {status}.",
        )


def validate_source_binding(
    report: Report,
    text: str,
    headings: list[Heading],
) -> None:
    exact = meaningful_content(
        section_body(text, headings, "3.2 Exact Scientific Content"),
        allow_placeholders=False,
    )
    if not exact or NUMERIC_CONTENT_RE.search(exact) is None:
        return

    binding = meaningful_content(
        section_body(text, headings, "3.3 Source Binding"),
        allow_placeholders=False,
    )
    if not binding:
        report.add_warning(
            "content.numeric_without_source_binding",
            "Exact Scientific Content contains a numeric value but Source Binding is empty.",
        )


def populated_outputs(metadata: dict[str, Any]) -> dict[str, str]:
    outputs = metadata.get("outputs")
    if not isinstance(outputs, dict):
        return {}
    result: dict[str, str] = {}
    for key in ("source", "vector", "preview"):
        value = outputs.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value.strip()
    return result


def artifact_candidates(
    artifact: str,
    spec_path: Path,
    project_root: Path | None,
) -> list[Path]:
    path = Path(artifact).expanduser()
    if path.is_absolute():
        return [path]

    candidates: list[Path] = []
    if project_root is not None:
        candidates.append(project_root / path)
    candidates.extend(
        [
            spec_path.parent / path,
            spec_path.parent.parent / path,
            Path.cwd() / path,
        ]
    )

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = str(candidate.resolve(strict=False))
        if normalized not in seen:
            seen.add(normalized)
            unique.append(candidate)
    return unique


def validate_outputs(
    report: Report,
    metadata: dict[str, Any],
    status: str | None,
    project_root: Path | None,
) -> None:
    outputs = populated_outputs(metadata)

    if status in {"RENDERED", "FINAL"} and not outputs:
        report.add_error(
            "outputs.required",
            f"At least one output artifact is required when status is {status}.",
        )
        return

    for key, value in outputs.items():
        if URL_RE.match(value):
            report.add_warning(
                "outputs.external_unchecked",
                f"outputs.{key} is an external URI and was not checked locally: {value}",
            )
            continue

        candidates = artifact_candidates(value, report.path, project_root)
        if any(candidate.is_file() for candidate in candidates):
            continue

        searched = ", ".join(str(candidate) for candidate in candidates)
        message = (
            f"outputs.{key} points to {value!r}, but no artifact file was found. "
            f"Checked: {searched}"
        )
        if status in {"RENDERED", "FINAL"}:
            report.add_error("outputs.missing_artifact", message)
        else:
            report.add_warning("outputs.missing_artifact", message)


def validate_file(path: Path, project_root: Path | None) -> Report:
    report = Report(path=path, issues=[])
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        report.add_error("file.encoding", "File is not valid UTF-8.")
        return report
    except OSError as exc:
        report.add_error("file.read", f"Could not read file: {exc}")
        return report

    metadata, error = extract_frontmatter(text)
    if error is not None or metadata is None:
        report.add_error("metadata.frontmatter", error or "Invalid frontmatter.")
        return report

    figure_id, status = validate_metadata(report, metadata)
    validate_filename_identity(report, figure_id)

    headings = collect_headings(text)
    validate_headings(report, headings)
    validate_readiness(report, text, headings, metadata, status)
    validate_source_binding(report, text, headings)
    validate_outputs(report, metadata, status, project_root)
    return report


def discover_specs(supplied_paths: list[str], recursive: bool) -> list[Path]:
    discovered: list[Path] = []
    for raw in supplied_paths:
        path = Path(raw).expanduser()
        if not path.exists():
            raise ValidationSetupError(f"Path does not exist: {path}")
        if path.is_file():
            discovered.append(path.resolve())
            continue
        iterator = path.rglob("F*.md") if recursive else path.glob("F*.md")
        discovered.extend(p.resolve() for p in iterator if p.is_file())

    unique: list[Path] = []
    seen: set[Path] = set()
    for path in sorted(discovered):
        if path not in seen:
            seen.add(path)
            unique.append(path)
    if not unique:
        raise ValidationSetupError("No FigureSpec files were found.")
    return unique


def validate_duplicate_ids(reports: list[Report]) -> None:
    seen: dict[str, Path] = {}
    for report in reports:
        try:
            text = report.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        metadata, error = extract_frontmatter(text)
        if error is not None or metadata is None:
            continue
        figure_id = metadata.get("figure_id")
        if not isinstance(figure_id, str) or not FIGURE_ID_RE.fullmatch(figure_id):
            continue
        previous = seen.get(figure_id)
        if previous is None:
            seen[figure_id] = report.path
            continue

        report.add_error(
            "project.duplicate_figure_id",
            f"figure_id {figure_id} is also used by {previous}.",
        )
        for previous_report in reports:
            if previous_report.path == previous:
                previous_report.add_error(
                    "project.duplicate_figure_id",
                    f"figure_id {figure_id} is also used by {report.path}.",
                )
                break


def print_text_report(reports: list[Report], strict: bool) -> None:
    total_errors = 0
    total_warnings = 0
    for report in reports:
        total_errors += len(report.errors)
        total_warnings += len(report.warnings)

        if report.errors or (strict and report.warnings):
            status_label = "FAIL"
        elif report.warnings:
            status_label = "PASS WITH WARNINGS"
        else:
            status_label = "PASS"

        print(f"\n[{status_label}] {report.path}")
        if not report.issues:
            print("  No issues found.")
            continue
        for issue in report.issues:
            print(f"  {issue.severity:<7} {issue.code}: {issue.message}")

    print("\nSummary")
    print(f"  Files:    {len(reports)}")
    print(f"  Errors:   {total_errors}")
    print(f"  Warnings: {total_warnings}")
    if total_errors or (strict and total_warnings):
        print("  Result:   FAIL")
    else:
        print("  Result:   PASS")


def print_json_report(reports: list[Report], strict: bool) -> None:
    total_errors = sum(len(report.errors) for report in reports)
    total_warnings = sum(len(report.warnings) for report in reports)
    passed = total_errors == 0 and (not strict or total_warnings == 0)
    payload = {
        "spec_version": SPEC_VERSION,
        "strict": strict,
        "passed": passed,
        "summary": {
            "files": len(reports),
            "errors": total_errors,
            "warnings": total_warnings,
        },
        "files": [
            {
                "path": str(report.path),
                "passed": not report.errors and (not strict or not report.warnings),
                "errors": len(report.errors),
                "warnings": len(report.warnings),
                "issues": [issue.as_dict() for issue in report.issues],
            }
            for report in reports
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> int:
    args = parse_args()
    try:
        specs = discover_specs(args.paths, args.recursive)
        project_root = (
            Path(args.project_root).expanduser().resolve()
            if args.project_root
            else None
        )
        if project_root is not None and not project_root.is_dir():
            raise ValidationSetupError(
                f"Project root is not a directory: {project_root}"
            )

        reports = [validate_file(path, project_root) for path in specs]
        validate_duplicate_ids(reports)

        total_errors = sum(len(report.errors) for report in reports)
        total_warnings = sum(len(report.warnings) for report in reports)

        if args.json:
            print_json_report(reports, args.strict)
        else:
            print_text_report(reports, args.strict)

        if total_errors or (args.strict and total_warnings):
            return 1
        return 0

    except ValidationSetupError as exc:
        if args.json:
            print(
                json.dumps(
                    {"passed": False, "setup_error": str(exc)},
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
