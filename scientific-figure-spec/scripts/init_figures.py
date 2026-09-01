#!/usr/bin/env python3
"""Initialize one or more FigureSpec v1.0 Markdown files.

Examples
--------
Create figures in ./figures:

    python init_figures.py \
        "Method Overview" \
        "Evaluation Framework"

Use another output directory:

    python init_figures.py \
        --output-dir paper/figures \
        "Main Results"

Preview without writing:

    python init_figures.py \
        --dry-run \
        "Method Overview"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


SPEC_VERSION = "1.0"
FIGURE_FILENAME_RE = re.compile(r"^F(?P<number>\d{3,})-.*\.md$")
FIGURE_ID_FIELD_RE = re.compile(
    r'(?m)^figure_id\s*:\s*["\']?F(?P<number>\d{3,})["\']?\s*$'
)
FRONT_MATTER_RE = re.compile(
    r"\A---\r?\n(?P<body>.*?)\r?\n---(?:\r?\n|\Z)",
    re.DOTALL,
)
MAX_SLUG_LENGTH = 80


class InitError(RuntimeError):
    """Raised when initialization cannot proceed safely."""


@dataclass(frozen=True)
class PlannedFigure:
    figure_id: str
    title: str
    filename: str
    path: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Initialize FigureSpec v1.0 files from the bundled template.",
        epilog='Example: %(prog)s "Method Overview" "Evaluation Framework"',
    )
    parser.add_argument(
        "titles",
        nargs="+",
        help="One or more working titles.",
    )
    parser.add_argument(
        "--output-dir",
        default="figures",
        help="Destination directory. Default: ./figures",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned files without writing them.",
    )
    return parser.parse_args()


def canonical_template_path() -> Path:
    skill_root = Path(__file__).resolve().parent.parent
    return skill_root / "assets" / "figure-spec.template.md"


def load_template(path: Path) -> str:
    if not path.is_file():
        raise InitError(f"FigureSpec template not found: {path}")

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InitError(f"Could not read template: {path}") from exc

    match = FRONT_MATTER_RE.match(text)
    if match is None:
        raise InitError(
            "The template must begin with YAML frontmatter delimited by '---'."
        )

    frontmatter = match.group("body")
    for field in ("spec_version", "figure_id", "working_title", "status"):
        if re.search(rf"(?m)^{re.escape(field)}\s*:", frontmatter) is None:
            raise InitError(f"Template frontmatter is missing: {field}")

    version_match = re.search(
        r'(?m)^spec_version\s*:\s*["\']?(?P<value>[^"\'\s]+)["\']?\s*$',
        frontmatter,
    )
    if version_match is None or version_match.group("value") != SPEC_VERSION:
        raise InitError(
            f"Template spec_version must be {SPEC_VERSION!r}."
        )

    if re.search(
        r'(?m)^figure_id\s*:\s*["\']?FXXX["\']?\s*$',
        frontmatter,
    ) is None:
        raise InitError('Template field "figure_id" must use placeholder "FXXX".')

    return text


def normalize_title(title: str) -> str:
    normalized = unicodedata.normalize("NFKC", title).strip()
    if not normalized:
        raise InitError("Figure titles must not be empty.")
    if "\n" in normalized or "\r" in normalized:
        raise InitError(f"Figure title must be one line: {title!r}")
    return normalized


def slugify(title: str) -> str:
    """Create a Unicode-safe filesystem slug."""
    text = unicodedata.normalize("NFKC", title).strip().lower()
    parts: list[str] = []
    previous_was_separator = False

    for char in text:
        if char.isalnum():
            parts.append(char)
            previous_was_separator = False
        elif parts and not previous_was_separator:
            parts.append("-")
            previous_was_separator = True

    slug = "".join(parts).strip("-") or "figure"
    slug = slug[:MAX_SLUG_LENGTH].rstrip("-")
    return slug or "figure"


def yaml_string(value: str) -> str:
    """Return a JSON-quoted string, which is also a valid YAML scalar."""
    return json.dumps(value, ensure_ascii=False)


def replace_frontmatter_field(
    document: str,
    field: str,
    yaml_value: str,
) -> str:
    match = FRONT_MATTER_RE.match(document)
    if match is None:
        raise InitError("Template does not contain valid YAML frontmatter.")

    body = match.group("body")
    pattern = re.compile(rf"(?m)^{re.escape(field)}\s*:\s*.*$")
    new_body, count = pattern.subn(f"{field}: {yaml_value}", body, count=1)
    if count != 1:
        raise InitError(f"Could not uniquely update frontmatter field: {field}")

    return document[: match.start("body")] + new_body + document[match.end("body") :]


def render_spec(template: str, figure_id: str, title: str) -> str:
    document = template
    document = replace_frontmatter_field(
        document, "figure_id", yaml_string(figure_id)
    )
    document = replace_frontmatter_field(
        document, "working_title", yaml_string(title)
    )
    document = replace_frontmatter_field(
        document, "status", yaml_string("DRAFT")
    )
    return document


def existing_figure_numbers(output_dir: Path) -> set[int]:
    """Discover IDs from both filenames and frontmatter."""
    numbers: set[int] = set()
    if not output_dir.exists():
        return numbers
    if not output_dir.is_dir():
        raise InitError(f"Output path is not a directory: {output_dir}")

    for path in output_dir.glob("*.md"):
        filename_match = FIGURE_FILENAME_RE.match(path.name)
        if filename_match:
            numbers.add(int(filename_match.group("number")))

        try:
            prefix = path.read_text(encoding="utf-8", errors="ignore")[:4096]
        except OSError:
            continue

        metadata_match = FIGURE_ID_FIELD_RE.search(prefix)
        if metadata_match:
            numbers.add(int(metadata_match.group("number")))

    return numbers


def next_figure_number(existing_numbers: Iterable[int]) -> int:
    numbers = list(existing_numbers)
    return max(numbers) + 1 if numbers else 1


def make_plan(
    titles: list[str],
    output_dir: Path,
    first_number: int,
) -> list[PlannedFigure]:
    plan: list[PlannedFigure] = []
    for offset, raw_title in enumerate(titles):
        title = normalize_title(raw_title)
        number = first_number + offset
        figure_id = f"F{number:03d}"
        filename = f"{figure_id}-{slugify(title)}.md"
        plan.append(
            PlannedFigure(
                figure_id=figure_id,
                title=title,
                filename=filename,
                path=output_dir / filename,
            )
        )
    return plan


def preflight(plan: list[PlannedFigure]) -> None:
    paths = [item.path for item in plan]
    if len(paths) != len(set(paths)):
        raise InitError("Initialization plan contains duplicate target paths.")

    collisions = [item.path for item in plan if item.path.exists()]
    if collisions:
        formatted = "\n".join(f"  - {path}" for path in collisions)
        raise InitError(
            "Refusing to overwrite existing FigureSpec files:\n" + formatted
        )


def write_batch(plan: list[PlannedFigure], template: str) -> None:
    """Write atomically at batch level and roll back this invocation on error."""
    created: list[Path] = []
    try:
        for item in plan:
            content = render_spec(template, item.figure_id, item.title)
            with item.path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
            created.append(item.path)
    except Exception:
        for path in created:
            try:
                path.unlink()
            except OSError:
                pass
        raise


def print_plan(plan: list[PlannedFigure], *, dry_run: bool) -> None:
    label = "Would create" if dry_run else "Created"
    for item in plan:
        print(f'{label}: {item.path} [{item.figure_id}: "{item.title}"]')


def main() -> int:
    args = parse_args()
    try:
        template_path = canonical_template_path()
        template = load_template(template_path)

        output_dir = Path(args.output_dir).expanduser()
        if not output_dir.is_absolute():
            output_dir = Path.cwd() / output_dir
        output_dir = output_dir.resolve()

        existing_numbers = existing_figure_numbers(output_dir)
        plan = make_plan(
            titles=args.titles,
            output_dir=output_dir,
            first_number=next_figure_number(existing_numbers),
        )
        preflight(plan)

        print(f"Template: {template_path}")
        print(f"Output directory: {output_dir}")
        if existing_numbers:
            print(
                "Existing figure IDs: "
                + ", ".join(f"F{n:03d}" for n in sorted(existing_numbers))
            )
        else:
            print("Existing figure IDs: (none)")

        if args.dry_run:
            print_plan(plan, dry_run=True)
            return 0

        output_dir.mkdir(parents=True, exist_ok=True)
        preflight(plan)
        write_batch(plan, template)
        print_plan(plan, dry_run=False)
        suffix = "s" if len(plan) != 1 else ""
        print(f"\nInitialized {len(plan)} FigureSpec file{suffix}.")
        return 0

    except InitError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"Filesystem error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
