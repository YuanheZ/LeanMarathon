# Workspace PDF Packages

The workspace virtual environment currently provides:

| Import | Use |
|---|---|
| `pdfplumber` | best default for reading math papers as text; usually preserves prose spacing well |
| `fitz` | PyMuPDF; fast PDF text extraction and page inspection |
| `pdfminer.high_level` | lower-level text extraction engine used by several PDF tools |
| `pypdf` | pure-Python PDF reader; useful fallback for simple text extraction |
| `PyPDF2` | older PDF reader; use only as a fallback |
| `pypdfium2` | PDFium bindings; useful for rendering pages and fallback text extraction |

Use `python3 -c "..."` for read-only scripts. Print results to stdout; do not write converted output files.

## Hard Constraint

For exact mathematical formulas, extracted text is only **approximate**. You **must** verify the formula against the rendered page images.
