"""Optional local bill extraction. Every field is an unconfirmed, sourced candidate."""
from __future__ import annotations
import csv
from decimal import Decimal
import hashlib
import io
import os
from pathlib import Path
import re
import subprocess
from billfit_core import BillFitError

PATTERNS = {
    "current_plan": r"\b(?:Rate\s+(?:Schedule|Plan)|Plan)\s*:?\s*(E-TOU-[CD]|EV2-A|E-ELEC|E-1)\b",
    "reported_energy_charge": r"\b(?:Electric\s+)?Energy\s+Charge(?:s)?\s*:?\s*\$?\s*([0-9,]+\.[0-9]{2})\b",
    "reported_base_services_charge": r"\bBase\s+Services\s+Charge\s*:?\s*\$?\s*([0-9,]+\.[0-9]{2})\b",
    "baseline_territory": r"\bBaseline\s+Territory\s*:?\s*([PQRSTVWXYZ])\b",
    "total_kwh": r"\b(?:Total\s+)?(?:Electricity\s+)?Usage\s*:?\s*([0-9,]+(?:\.[0-9]+)?)\s*kWh\b",
}


def extract_spans(spans: list[dict], source_sha256: str, method: str) -> dict:
    candidates = []
    for span in spans:
        for field, pattern in PATTERNS.items():
            for match in re.finditer(pattern, span["text"], re.I):
                raw = match.group(1)
                value = str(Decimal(raw.replace(",", ""))) if field in {"total_kwh", "reported_energy_charge", "reported_base_services_charge"} else raw.upper()
                candidates.append({"field": field, "value": value, "status": "NEEDS_USER_CONFIRMATION",
                    "source": {"sha256": source_sha256, "page": span["page"], "line": span["line"],
                               "bbox": span.get("bbox"), "quote": match.group(0), "start": match.start(), "end": match.end()},
                    "method": method})
    by_field = {key: [x["value"] for x in candidates if x["field"] == key] for key in PATTERNS}
    return {"status": "REVIEW_REQUIRED", "candidates": candidates,
            "missing_fields": [key for key, values in by_field.items() if not values],
            "conflicting_fields": [key for key, values in by_field.items() if len(set(values)) > 1],
            "automatic_calculation": False, "automatic_confirmation": False,
            "warnings": ["Verify each candidate against the cited page/line before supplying it to validate/compare.",
                         "Total amount due is excluded. A bill's total kWh cannot replace interval usage.",
                         "No eligibility, account number, login, medical data or income is inferred."]}


def extract_bill_fields(bill_file: str) -> dict:
    path = Path(bill_file).expanduser().resolve(strict=True)
    if not path.is_file() or path.stat().st_size > 25_000_000:
        raise BillFitError("BILL_FILE_LIMIT", "Supply one local bill file under 25 MB.")
    suffix = path.suffix.lower()
    spans = []
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise BillFitError("PDF_DEPENDENCY_REQUIRED", "Install the optional bill-input requirements for local PDF text extraction.") from exc
        reader = PdfReader(path)
        if reader.is_encrypted or len(reader.pages) > 25:
            raise BillFitError("PDF_LIMIT", "Use a non-encrypted bill of at most 25 pages.")
        for number, page in enumerate(reader.pages, 1):
            for line, text in enumerate((page.extract_text() or "").splitlines(), 1):
                spans.append({"text": text, "page": number, "line": line})
        method = "LOCAL_PDF_TEXT"
    elif suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        command = os.getenv("BILLFIT_TESSERACT_PATH", "")
        if not command or not Path(command).is_file():
            raise BillFitError("LOCAL_OCR_REQUIRED", "Configure BILLFIT_TESSERACT_PATH to an existing trusted Tesseract executable. No image is uploaded.")
        result = subprocess.run([command, str(path), "stdout", "--psm", "6", "tsv"], capture_output=True,
                                text=True, encoding="utf-8", timeout=30, check=True)
        if len(result.stdout) > 2_000_000:
            raise BillFitError("OCR_OUTPUT_LIMIT", "OCR output exceeded the limit.")
        grouped = {}
        for row in csv.DictReader(io.StringIO(result.stdout), delimiter="\t"):
            if row.get("level") != "5" or not row.get("text", "").strip():
                continue
            key = tuple(row[x] for x in ("page_num", "block_num", "par_num", "line_num"))
            grouped.setdefault(key, []).append(row)
        for index, (key, words) in enumerate(grouped.items(), 1):
            left = min(int(x["left"]) for x in words); top = min(int(x["top"]) for x in words)
            right = max(int(x["left"]) + int(x["width"]) for x in words)
            bottom = max(int(x["top"]) + int(x["height"]) for x in words)
            spans.append({"text": " ".join(x["text"] for x in words), "page": int(key[0]), "line": index,
                          "bbox": [left, top, right, bottom]})
        method = "LOCAL_TESSERACT_OCR"
    else:
        raise BillFitError("BILL_FORMAT_UNSUPPORTED", "Use PDF, PNG, JPEG or TIFF. Usage files still use the existing parse operation.")
    if sum(len(x["text"]) for x in spans) > 1_000_000:
        raise BillFitError("BILL_TEXT_LIMIT", "Bill text exceeds the extraction limit.")
    result = extract_spans(spans, hashlib.sha256(path.read_bytes()).hexdigest(), method)
    if not spans:
        result["warnings"].append("No readable text. For a scanned PDF, export the relevant page to an image and use local OCR.")
    return result
