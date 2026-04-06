# Coverage — Document Logic MCP

## Overview

Document Logic MCP is a **stateless document extraction utility**. It has no static corpus —
it processes caller-supplied documents and returns structured data extracted via LLM. There is
no fixed dataset to "cover": coverage is determined entirely by the documents submitted by the
caller.

## Supported File Formats

| Format | Extension(s) | Parser |
|--------|-------------|--------|
| PDF | `.pdf` | pdfplumber + pdf2image (OCR fallback via pytesseract) |
| Word | `.docx` | python-docx |
| Excel | `.xlsx` | openpyxl |
| PowerPoint | `.pptx` | python-pptx |
| HTML | `.html`, `.htm` | beautifulsoup4 |
| Plain text | `.txt` | built-in |
| Markdown | `.md` | built-in |
| CSV | `.csv` | built-in |
| JSON | `.json` | built-in |
| Images | `.png`, `.jpg`, `.jpeg`, `.tiff`, `.bmp` | pytesseract (OCR) |

## Analysis Contexts

When `analysis_context` is provided to `/extract-stateless`, the extraction pipeline activates
domain-specific prompt supplements (Pass 2) and a cross-section synthesis pass (Pass 3).

| Context ID | Description |
|-----------|-------------|
| `stride_threat_modeling` | STRIDE threat model extraction: components, trust boundaries, threats, mitigations |
| `tprm_vendor_assessment` | Third-party risk management: vendor controls, compliance posture, risk indicators |
| `compliance_mapping` | Compliance mapping: control references, policy statements, regulatory citations |

When no `analysis_context` is provided, a general-purpose extraction pass runs (Pass 1 only).

## Terminology Resource

The bundled technology terminology resource (`technology_terminology.json`) is used by the
`/resolve-technology-name` endpoint for deterministic canonical name resolution.

- **Entry count**: 102 technology entries
- **Coverage**: Common infrastructure, cloud, security, and data technologies
- **Matching**: Exact match (case-insensitive) with fuzzy fallback (Levenshtein, threshold 0.85)
- **Source**: Manually curated; updated via the `/suggest-terminology-addition` feedback loop

## What Is Not Covered

- This server has no knowledge of any specific document domain until a document is submitted
- There is no pre-indexed corpus of legislation, standards, or reference material
- Extraction quality depends on the LLM model and the quality/completeness of the input document
