# Noor PDF Page Reorganizer

Offline Windows utility to reorder, rotate, remove or extract pages from one PDF. It writes a new PDF from page objects rather than rendering pages into images, so selectable text and mixed page dimensions remain PDF content. The original is never edited in place.

## Features

- Open one PDF and inspect page number, MediaBox dimensions and current rotation.
- Preview the selected page and move selected pages up or down in the output sequence.
- Remove pages from the output plan and rotate selected pages clockwise by 90°, 180° or 270°.
- Save the complete arranged plan to a new PDF, or extract only the selected pages in their displayed order.
- Use the command line for a repeatable page order such as `3,1,4-6` and per-source-page rotation.
- Reject invalid page plans, duplicate page numbers, unsupported rotations, corrupt/encrypted PDFs, and outputs that resolve to the source. Existing output files are protected unless explicit overwrite is requested.
- Process locally. No network service or upload is used.

This is a small single-document utility, not a full PDF editor. PDF Arranger already offers a broader graphical merge/split/crop/rotate/rearrange workflow. PDFsam Basic supports offline rotation and extraction among its merge, split, mix and insert tools. Noor's compact page list, selected-page preview, one-based sequence syntax and source-preserving export make it useful as a simple standalone operation; these features are not claimed to be unique. [PDF Arranger](https://github.com/pdfarranger/pdfarranger) · [PDFsam Basic](https://pdfsam.org/pdfsam-basic/).

## Windows installation

Install Python 3.10 or newer with Tcl/Tk support (the GUI uses Tkinter). In PowerShell from this project folder:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python .\src\noor_pdf_page_reorganizer_gui.py
```

The CLI can be used without opening the GUI:

```powershell
python .\src\noor_pdf_page_reorganizer.py .\input.pdf -o .\organized.pdf --order "3,1,4-6" --rotate 3:90
```

`--order` is an ordered list of one-based input pages and ascending ranges. Pages left out of this sequence are omitted, so it can also extract a subset. Rotation arguments refer to original input page numbers, use clockwise degrees, and may be repeated. For example, `--rotate 2:180 --rotate 5:270`. Existing outputs require `--overwrite`; do not set it unless replacement is intended. CLI help: `python .\src\noor_pdf_page_reorganizer.py --help`.

## Important PDF behavior and limits

The tool changes PDF page objects and does not rasterize page content. It preserves the page-level content streams and each selected page's MediaBox dimensions; a clockwise right-angle rotation is stored as the page's `/Rotate` entry. The tests check selectable text, mixed page sizes, rotation values and PDFium readability.

The source is never overwritten, but any rewritten copy may lose or change document-level metadata, bookmarks/outlines, forms, links, attachments, layers, tagged accessibility structure, or other non-page features. Such features are not guaranteed to survive. A rewrite invalidates existing digital signatures. Always review the output before using a signed or archival document. Password-protected PDFs are not supported. The input safety limits are 250 MB and 1,000 pages. There is no PDF merging, OCR, compression or editing of page text. The pypdf `rotate()` operation uses right-angle page rotation rather than raster transformation; see [pypdf's official page-rotation guidance](https://pypdf.readthedocs.io/en/stable/user/cropping-and-transforming.html).

## Tests and build status

Install development dependencies and run:

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

Tests cover ordering/range parsing, mixed page dimensions, vector text retention, page rotation including existing rotation, extraction, PDFium rendering, Unicode paths, malformed rotation metadata, corrupt/password-protected inputs, output collision safety and preservation of the original bytes. GitHub Actions is configured for the core tests on Windows and Ubuntu with Python 3.10 and 3.12. Tests do not launch the Tkinter GUI or exercise a physical scanner/printer. No Windows executable, installer or release is claimed.

## License and security

MIT; see [LICENSE](LICENSE). See [SECURITY.md](SECURITY.md) for private vulnerability reporting. Do not attach real customer documents or personal data to public issues.
