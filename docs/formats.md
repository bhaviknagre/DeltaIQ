# Ingestion & formats

| Format | Status | How |
|---|---|---|
| Native PDF | **Fully working** | PyMuPDF `get_text("dict")` line-level extraction with real bounding boxes. Deterministic, no OCR. |
| Scanned PDF | **Fully working** | Rasterize at 300dpi → Tesseract OCR (`--psm 11`, sparse-text mode) → word-grouped, line-level elements with OCR confidence carried through. |
| DWG | **Real stub behind the same interface** | `ezdxf` parses real DXF (TEXT/MTEXT/LINE/LWPOLYLINE/CIRCLE → typed elements with bounding boxes and layer metadata). `.dwg` itself needs conversion to `.dxf` first (ODA File Converter or Autodesk SDK — no license-free pure-Python DWG reader exists); the adapter raises a clear `NotImplementedError` naming that pre-step. |

Two of three formats are fully working end-to-end, meeting the assignment's
minimum bar; DWG is a genuine stub, not a hypothetical one — point
`DwgAdapter` at a real `.dxf` file and it produces the same
`CanonicalDocument` shape the PDF adapters do.

## Native PDF (`src/ingest/pdf_native.py`)

Reads the PDF's text layer directly via PyMuPDF, at line granularity (not
page-level blocks, which merge unrelated labels together on a dense P&ID).
Each line becomes one `Element` with an exact bounding box.

## Scanned PDF (`src/ingest/pdf_scanned.py`)

Rasterizes each page at 300dpi and runs Tesseract OCR. One tuning decision
mattered a lot: Tesseract's default page-segmentation mode (`--psm 3`, "assume
a uniform block of text") merges unrelated nearby labels into single garbled
lines on a P&ID's scattered layout — measured at **92 spurious deltas** on the
demo pair. Switching to `--psm 11` ("sparse text, no particular order") treats
each scattered label as its own region, cutting that to **10**. Configurable
via `OCR_PSM` in `.env`.

## DWG / DXF (`src/ingest/dwg.py`)

Parses TEXT/MTEXT entities as elements and LINE/LWPOLYLINE/CIRCLE as
`ElementType.GEOMETRY`, each with a real bounding box and the DXF layer name
in `attrs`. Real `.dwg` binaries need conversion to `.dxf` first — there's no
license-free pure-Python DWG reader; a production build would shell out to the
ODA File Converter as a pre-step and reuse `DwgAdapter.parse()` unchanged.

## Format detection

`FormatAdapter.sniff()` is content-based, not extension-based: a `.pdf` with
an average of ≥20 extractable characters per page is routed to
`NativePdfAdapter`; one with real page content but little/no text layer is
routed to `ScannedPdfAdapter`. This matters because the distinction between
"native" and "scanned" is exactly what routing depends on — a file extension
alone can't tell them apart.

## PID resolution (`src/ingest/pid_store.py`)

A PID is resolved to bytes + metadata via a flat JSON manifest
(`data/pid_store/pids.json`, `pid -> {path, revision_label}`) by default, then
dispatched to whichever registered adapter's `sniff()` matches.
`METADATA_STORE=mongo` and `BLOB_STORE=minio`/`mongo_gridfs` swap this for a
real database/object-store lookup behind the same `resolve_pid()` / `load()`
interface — see [Data & infrastructure](infrastructure.md).
