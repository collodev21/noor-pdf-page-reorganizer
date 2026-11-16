"""Noor PDF Page Reorganizer — reorder, rotate and extract PDF pages offline."""
from __future__ import annotations

import argparse
import math
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping

from pypdf import PdfReader, PdfWriter

MAX_INPUT_BYTES = 250 * 1024 * 1024
MAX_PAGES = 1000
RIGHT_ANGLE_ROTATIONS = {0, 90, 180, 270}


@dataclass(frozen=True)
class PageInfo:
    number: int  # one-based display number
    width: float
    height: float
    rotation: int


ProgressCallback = Callable[[int, int], None]


def _validate_source(path: str | Path) -> Path:
    source = Path(path)
    if source.suffix.lower() != ".pdf":
        raise ValueError("Input filename must end in .pdf")
    if not source.is_file():
        raise ValueError(f"PDF file not found: {source}")
    try:
        size = source.stat().st_size
    except OSError as exc:
        raise ValueError(f"Cannot access input PDF: {exc}") from exc
    if size <= 0:
        raise ValueError("Input PDF is empty")
    if size > MAX_INPUT_BYTES:
        raise ValueError(f"Input PDF exceeds the {MAX_INPUT_BYTES // (1024 * 1024)} MB safety limit")
    return source


def _reader(stream) -> PdfReader:
    try:
        reader = PdfReader(stream, strict=False)
        if reader.is_encrypted:
            raise ValueError("Password-protected PDFs are not supported in this version")
        count = len(reader.pages)
        if count == 0:
            raise ValueError("PDF has no pages")
        if count > MAX_PAGES:
            raise ValueError(f"PDF has {count} pages; maximum supported is {MAX_PAGES}")
        return reader
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Cannot read PDF: {exc}") from exc


def inspect_pdf(path: str | Path) -> list[PageInfo]:
    """Read page count, displayed page boxes and stored right-angle rotations."""
    source = _validate_source(path)
    try:
        with source.open("rb") as stream:
            reader = _reader(stream)
            result = []
            for index, page in enumerate(reader.pages):
                box = page.mediabox
                width, height = float(box.width), float(box.height)
                if not math.isfinite(width) or not math.isfinite(height) or width <= 0 or height <= 0:
                    raise ValueError(f"Page {index + 1} has invalid dimensions")
                rotation = int(page.get("/Rotate", 0) or 0) % 360
                if rotation not in RIGHT_ANGLE_ROTATIONS:
                    raise ValueError(f"Page {index + 1} has an unsupported non-right-angle rotation")
                result.append(PageInfo(index + 1, width, height, rotation))
            return result
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Cannot inspect PDF: {exc}") from exc


def parse_page_order(spec: str, page_count: int) -> list[int]:
    """Parse one-based page list/ranges into zero-based order, e.g. 3,1,4-6."""
    if page_count < 1:
        raise ValueError("PDF must contain at least one page")
    if not spec or not spec.strip():
        raise ValueError("Page order cannot be empty")
    pages: list[int] = []
    for token in spec.split(","):
        token = token.strip()
        if not token:
            raise ValueError("Empty item in page order")
        match = re.fullmatch(r"(\d+)(?:\s*-\s*(\d+))?", token)
        if not match:
            raise ValueError(f"Invalid page item: {token!r}")
        start = int(match.group(1)); end = int(match.group(2) or start)
        if start > end:
            raise ValueError(f"Page ranges must ascend: {token}")
        if start < 1 or end > page_count:
            raise ValueError(f"Page {start if start < 1 else end} is outside 1–{page_count}")
        pages.extend(range(start - 1, end))
    if len(pages) != len(set(pages)):
        raise ValueError("Page order contains duplicates")
    return pages


def parse_rotation_specs(specs: Iterable[str], page_count: int) -> dict[int, int]:
    """Parse repeatable one-based PAGE:DEGREES specs into zero-based rotations."""
    rotations: dict[int, int] = {}
    for raw in specs:
        match = re.fullmatch(r"\s*(\d+)\s*:\s*(\d+)\s*", raw)
        if not match:
            raise ValueError(f"Invalid rotation {raw!r}; use PAGE:90, PAGE:180 or PAGE:270")
        page, degrees = int(match.group(1)), int(match.group(2))
        if not 1 <= page <= page_count:
            raise ValueError(f"Rotation page {page} is outside 1–{page_count}")
        if degrees not in {90, 180, 270}:
            raise ValueError("Rotation must be 90, 180 or 270 degrees clockwise")
        if page - 1 in rotations:
            raise ValueError(f"Rotation specified more than once for page {page}")
        rotations[page - 1] = degrees
    return rotations


def export_pages(source: str | Path, output: str | Path, page_order: Iterable[int] | None = None,
                 rotations: Mapping[int, int] | None = None, *, overwrite: bool = False,
                 progress: ProgressCallback | None = None) -> Path:
    """Write selected/reordered source pages and optional clockwise turns to a new PDF.

    Page indices in ``page_order`` and ``rotations`` are zero-based. An omitted
    order means all pages in the original order. Each included original page may
    occur once. Source content is written as PDF objects, not rasterized.
    """
    input_path = _validate_source(source)
    target = Path(output)
    if target.suffix.lower() != ".pdf":
        raise ValueError("Output filename must end in .pdf")
    try:
        if input_path.resolve() == target.resolve():
            raise ValueError("Output must be a different file from the source PDF")
        if target.exists() and os.path.samefile(input_path, target):
            raise ValueError("Output must not be the source PDF or a hard link to it")
    except OSError as exc:
        raise ValueError(f"Cannot compare source and output paths: {exc}") from exc
    if target.exists() and not overwrite:
        raise FileExistsError(f"Output already exists; choose another name or confirm overwrite: {target}")

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with input_path.open("rb") as stream:
            reader = _reader(stream)
            page_count = len(reader.pages)
            order = list(range(page_count)) if page_order is None else list(page_order)
            if not order:
                raise ValueError("At least one page must be included")
            if any(not isinstance(p, int) or isinstance(p, bool) or not 0 <= p < page_count for p in order):
                raise ValueError(f"Page order indices must be between 0 and {page_count - 1}")
            if len(order) != len(set(order)):
                raise ValueError("Page order contains duplicate pages")
            rotate_map = dict(rotations or {})
            for index, degrees in rotate_map.items():
                if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < page_count:
                    raise ValueError(f"Rotation page index must be between 0 and {page_count - 1}")
                if degrees not in {0, 90, 180, 270}:
                    raise ValueError("Rotation values must be 0, 90, 180 or 270 degrees")

            with tempfile.NamedTemporaryFile(prefix=f".{target.stem}.tmp-", suffix=".pdf",
                                             dir=target.parent, delete=False) as temp_stream:
                temporary = Path(temp_stream.name)
            writer = PdfWriter()
            total = len(order)
            for position, index in enumerate(order, 1):
                page = reader.pages[index]
                degrees = rotate_map.get(index, 0)
                if degrees:
                    page.rotate(degrees)
                writer.add_page(page)
                if progress:
                    progress(position, total)
            writer.write(str(temporary))

        # Re-open the completed temporary file before replacing any destination.
        with temporary.open("rb") as check_stream:
            check = _reader(check_stream)
            if len(check.pages) != len(order):
                raise ValueError("Export validation failed: output page count did not match")
        if target.exists() and not overwrite:
            raise FileExistsError(f"Output appeared during export; refusing to overwrite: {target}")
        os.replace(temporary, target)
        temporary = None
        return target
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Could not write PDF: {exc}") from exc
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description="Reorder, rotate or extract PDF pages without rasterizing them")
    parser.add_argument("input", help="Input PDF (password-protected PDFs are not supported)")
    parser.add_argument("-o", "--output", required=True, help="New output PDF path")
    parser.add_argument("--order", help="Final page order/subset, one-based; e.g. 3,1,4-6 (default: all pages)")
    parser.add_argument("--rotate", action="append", default=[], metavar="PAGE:DEGREES",
                        help="Rotate an original page clockwise by 90, 180 or 270 degrees; repeatable")
    parser.add_argument("--overwrite", action="store_true", help="Allow replacing an existing output PDF")
    args = parser.parse_args()
    try:
        infos = inspect_pdf(args.input)
        order = list(range(len(infos))) if args.order is None else parse_page_order(args.order, len(infos))
        rotations = parse_rotation_specs(args.rotate, len(infos))
        total = len(order)
        result = export_pages(args.input, args.output, order, rotations,
                              overwrite=args.overwrite,
                              progress=lambda i, n: print(f"Writing page {i}/{n}", flush=True))
        print(f"Created {result}: {total} page(s)")
    except (ValueError, OSError, FileExistsError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
