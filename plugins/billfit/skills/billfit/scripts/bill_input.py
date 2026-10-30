"""Local bill field candidates, bound to the exact bytes that were parsed.

This adapter does not infer eligibility, repair ambiguous amounts, add repeated
charges, or authorize calculator inputs. Every result requires source review.
"""
from __future__ import annotations

from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

from billfit_errors import BillFitError
from bill_ocr import extract_ocr_spans
from bill_process import run_bounded

MAX_FILE_BYTES = 25_000_000
MAX_TEXT_CHARS = 1_000_000
LOW_OCR_CONFIDENCE = 70

# Labels identify a possible field; the entire following value must validate.
# In particular, removing commas before validating can change 12,34 to 1234.
LABELS = {
    "current_plan": r"\b(?:Rate\s+(?:Schedule|Plan)|Plan)\b",
    "reported_energy_charge": r"\b(?:Electric\s+)?Energy\s+Charges?\b",
    "reported_base_services_charge": r"\bBase\s+Services\s+Charge\b",
    "baseline_territory": r"\bBaseline\s+Territory\b",
    "total_kwh": r"\b(?:Total\s+)?(?:Electricity\s+)?Usage\b",
}
LABEL_RE = re.compile("|".join(f"(?P<{key}>{value})" for key, value in LABELS.items()), re.I)
INTEGER = r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)"
VALUE_PATTERNS = {
    "current_plan": r"(?P<value>E-TOU-[CD]|EV2-A|E-ELEC|E-1)",
    "reported_energy_charge": rf"\$?\s*(?P<value>{INTEGER}\.[0-9]{{2}})",
    "reported_base_services_charge": rf"\$?\s*(?P<value>{INTEGER}\.[0-9]{{2}})",
    "baseline_territory": r"(?P<value>[PQRSTVWXYZ])",
    "total_kwh": rf"(?P<value>{INTEGER}(?:\.[0-9]+)?)\s*kWh",
}
NUMERIC_FIELDS = {"total_kwh", "reported_energy_charge", "reported_base_services_charge"}


def _source(span: dict, sha256: str, start: int, end: int) -> tuple[dict, list[str]]:
    source = {"sha256": sha256, "page": span["page"], "line": span["line"],
              "bbox": span.get("bbox"), "quote": span["text"][start:end], "start": start, "end": end}
    flags = []
    words = [word for word in span.get("words", []) if word["start"] < end and word["end"] > start]
    if words:
        source["bbox"] = [min(word["bbox"][0] for word in words), min(word["bbox"][1] for word in words),
                          max(word["bbox"][2] for word in words), max(word["bbox"][3] for word in words)]
        known = [word["confidence"] for word in words if word["confidence"] >= 0]
        minimum = min(known) if known else None
        source["ocr_confidence"] = {"minimum": minimum, "unknown_words": len(words) - len(known), "calibrated": False}
        flags.append("OCR_REQUIRES_VISUAL_REVIEW")
        if minimum is not None and minimum < LOW_OCR_CONFIDENCE:
            flags.append("LOW_OCR_CONFIDENCE")
        if len(known) != len(words):
            flags.append("OCR_CONFIDENCE_UNKNOWN")
    return source, flags


def extract_spans(spans: list[dict], source_sha256: str, method: str) -> dict:
    candidates, unresolved = [], []
    for span in spans:
        text = span["text"]
        matches = list(LABEL_RE.finditer(text))
        for index, label in enumerate(matches):
            field = label.lastgroup
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            separator = text.find(";", label.end(), end)
            if separator >= 0:
                end = separator
            end = len(text[:end].rstrip())
            segment = text[label.end():end]
            # Reject extra signs, suffixes, ranges, credits and unsupported plan
            # variants instead of truncating them to a plausible valid value.
            match = re.fullmatch(r"\s*:?\s*" + VALUE_PATTERNS[field] + r"\s*", segment, re.I) if len(segment) <= 100 else None
            if match:
                raw = match.group("value")
                value = str(Decimal(raw.replace(",", ""))) if field in NUMERIC_FIELDS else raw.upper()
                source, flags = _source(span, source_sha256, label.start(), end)
                candidates.append({"field": field, "value": value, "status": "NEEDS_USER_CONFIRMATION",
                                   "source": source, "quality_flags": flags, "method": method})
            else:
                # Diagnostic excerpts are bounded and remain local like candidates.
                source, flags = _source(span, source_sha256, label.start(), min(end, label.end() + 80))
                unresolved.append({"field": field, "reason": "AMBIGUOUS_OR_UNSUPPORTED_VALUE",
                                   "source": source, "quality_flags": flags})
    by_field = {key: [row["value"] for row in candidates if row["field"] == key] for key in LABELS}
    return {"status": "REVIEW_REQUIRED", "candidates": candidates, "unresolved_fields": unresolved,
            "missing_fields": [key for key, values in by_field.items() if not values],
            "conflicting_fields": [key for key, values in by_field.items() if len(set(values)) > 1],
            "automatic_calculation": False, "automatic_confirmation": False,
            "warnings": ["Verify each candidate against the cited page/line before supplying it to validate/compare.",
                         "Total amount due is excluded. A bill's total kWh cannot replace interval usage.",
                         "No eligibility, account number, login, medical data or income is inferred.",
                         "OCR confidence is uncalibrated. Even high-confidence text needs visual source review.",
                         "Missing, unsupported or ambiguous values require manual review; charges are never summed."]}


def _fingerprint(info: os.stat_result) -> tuple:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _read_source(path: Path) -> tuple[bytes, tuple]:
    try:
        # Nonblocking avoids opening a FIFO as a bill on supported platforms.
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
                raise BillFitError("BILL_FILE_LIMIT", "Supply one regular local bill file under 25 MB.")
            raw = handle.read(MAX_FILE_BYTES + 1)
            if len(raw) > MAX_FILE_BYTES:
                raise BillFitError("BILL_FILE_LIMIT", "Supply one regular local bill file under 25 MB.")
            if _fingerprint(before) != _fingerprint(os.fstat(handle.fileno())):
                raise BillFitError("BILL_SOURCE_CHANGED", "The supplied file changed. Select the intended version and retry.")
            return raw, _fingerprint(before)
    except OSError as exc:
        raise BillFitError("BILL_FILE_UNAVAILABLE", "The supplied local file could not be read.") from exc


def _pdf_spans(raw: bytes) -> list[dict]:
    with tempfile.TemporaryDirectory(prefix="billfit-pdf-") as directory:
        snapshot = Path(directory) / "source.pdf"
        snapshot.write_bytes(raw)
        output = run_bounded([sys.executable, "-I", str(Path(__file__).with_name("bill_pdf_worker.py")), str(snapshot)],
                             timeout=30, output_limit=8_000_000, kind="PDF")
        try:
            snapshot_raw, _ = _read_source(snapshot)
        except BillFitError as exc:
            raise BillFitError("BILL_SOURCE_CHANGED", "The extraction snapshot changed or became unavailable.") from exc
        if snapshot_raw != raw:
            raise BillFitError("BILL_SOURCE_CHANGED", "The extraction snapshot changed. Retry with the intended file.")
    errors = {
        "PDF_DEPENDENCY_REQUIRED": "Install the optional bill-input requirements for local PDF text extraction.",
        "PDF_LIMIT": "Use a non-encrypted bill of at most 25 pages.",
        "BILL_FILE_LIMIT": "Supply one regular local bill file under 25 MB.",
        "BILL_TEXT_LIMIT": "Bill text exceeds the extraction limit.",
        "PDF_TEXT_FAILED": "The PDF text could not be read. Try a readable, unencrypted export or a relevant page image.",
    }
    try:
        payload = json.loads(output)
        if isinstance(payload, dict) and set(payload) == {"error"} and payload["error"] in errors:
            raise BillFitError(payload["error"], errors[payload["error"]])
        if not isinstance(payload, dict) or set(payload) != {"spans"} or not isinstance(payload["spans"], list):
            raise ValueError("Invalid worker response")
        spans = payload["spans"]
        if len(spans) > 50_000:
            raise ValueError("Invalid worker response")
        for span in spans:
            if not isinstance(span, dict) or set(span) != {"text", "page", "line"} or not isinstance(span["text"], str):
                raise ValueError("Invalid worker response")
            if type(span["page"]) is not int or not 1 <= span["page"] <= 25 or type(span["line"]) is not int or span["line"] < 1:
                raise ValueError("Invalid worker response")
        return spans
    except (UnicodeError, ValueError, TypeError) as exc:
        raise BillFitError("PDF_TEXT_FAILED", errors["PDF_TEXT_FAILED"]) from exc


def extract_bill_fields(bill_file: str) -> dict:
    try:
        path = Path(bill_file).expanduser().resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise BillFitError("BILL_FILE_UNAVAILABLE", "The supplied local file could not be read.") from exc
    suffix = path.suffix.lower()
    if suffix not in {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        raise BillFitError("BILL_FORMAT_UNSUPPORTED", "Use PDF, PNG, JPEG or TIFF. Usage files still use the existing parse operation.")
    raw, fingerprint = _read_source(path)
    sha256 = hashlib.sha256(raw).hexdigest()
    if suffix == ".pdf":
        spans, method = _pdf_spans(raw), "LOCAL_PDF_TEXT"
    else:
        command = os.getenv("BILLFIT_TESSERACT_PATH", "")
        if not command or not Path(command).is_file():
            raise BillFitError("LOCAL_OCR_REQUIRED", "Configure BILLFIT_TESSERACT_PATH to an existing trusted Tesseract executable. No image is uploaded.")
        with tempfile.TemporaryDirectory(prefix="billfit-ocr-") as directory:
            snapshot = Path(directory) / ("source" + suffix)
            snapshot.write_bytes(raw)
            spans = extract_ocr_spans(command, snapshot)
            try:
                snapshot_raw, _ = _read_source(snapshot)
            except BillFitError as exc:
                raise BillFitError("BILL_SOURCE_CHANGED", "The extraction snapshot changed or became unavailable.") from exc
            if snapshot_raw != raw:
                raise BillFitError("BILL_SOURCE_CHANGED", "The extraction snapshot changed. Check the configured OCR executable before retrying.")
        method = "LOCAL_TESSERACT_OCR"
    if sum(len(span["text"]) for span in spans) > MAX_TEXT_CHARS:
        raise BillFitError("BILL_TEXT_LIMIT", "Bill text exceeds the extraction limit.")
    try:
        current, current_fingerprint = _read_source(path)
    except BillFitError as exc:
        raise BillFitError("BILL_SOURCE_CHANGED", "The supplied file changed or became unavailable. Select the intended version and retry.") from exc
    if current_fingerprint != fingerprint or current != raw:
        raise BillFitError("BILL_SOURCE_CHANGED", "The supplied file changed. Select the intended version and retry.")
    result = extract_spans(spans, sha256, method)
    result["source_sha256"] = sha256
    result["method"] = method
    if not spans:
        result["warnings"].append("No readable text. For a scanned PDF, export the relevant page to an image and use local OCR.")
    if not result["candidates"]:
        result["warnings"].append("No supported fields were extracted. Check image orientation and legibility, then retry or enter verified fields manually.")
    return result
