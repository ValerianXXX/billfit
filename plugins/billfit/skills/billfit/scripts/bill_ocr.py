"""Bounded local Tesseract process and validated, word-level TSV evidence."""
from __future__ import annotations

import csv
import io
import math
from pathlib import Path
import re

from billfit_errors import BillFitError
from bill_process import run_bounded as _run_bounded

MAX_OUTPUT_BYTES = 2_000_000  # stdout and stderr together; stderr is discarded
MAX_ROWS = 50_000
HEADER = ["level", "page_num", "block_num", "par_num", "line_num", "word_num",
          "left", "top", "width", "height", "conf", "text"]


def _invalid() -> BillFitError:
    return BillFitError("OCR_OUTPUT_INVALID", "Local OCR returned invalid evidence. Check the configured OCR version or enter verified fields manually.")


def parse_tsv(raw: bytes) -> list[dict]:
    if len(raw) > MAX_OUTPUT_BYTES:
        raise BillFitError("OCR_OUTPUT_LIMIT", "OCR output exceeded the limit.")
    try:
        # Tesseract TSV text is literal, not CSV-quoted. Preserve quote marks.
        reader = csv.reader(io.StringIO(raw.decode("utf-8")), delimiter="\t", quoting=csv.QUOTE_NONE, strict=True)
        if next(reader, None) != HEADER:
            raise _invalid()
        rows, pages = {}, {}
        for count, columns in enumerate(reader, 1):
            if count > MAX_ROWS or len(columns) != len(HEADER):
                raise _invalid()
            if any(not re.fullmatch(r"[0-9]+", value) for value in columns[:10]):
                raise _invalid()
            numbers = tuple(int(value) for value in columns[:10])
            level, page, block, paragraph, line, word, left, top, width, height = numbers
            confidence = float(columns[10])
            text = columns[11]
            if not math.isfinite(confidence) or not (confidence == -1 or 0 <= confidence <= 100):
                raise _invalid()
            if not 1 <= level <= 5 or not 1 <= page <= 25 or width <= 0 or height <= 0:
                raise _invalid()
            ids = (block, paragraph, line, word)
            if any(value <= 0 for value in ids[:level-1]) or any(value != 0 for value in ids[level-1:]):
                raise _invalid()
            if any(ord(char) < 32 for char in text):
                raise _invalid()
            identity = numbers[:6]
            value = (numbers, confidence, text)
            if identity in rows and rows[identity] != value:
                raise _invalid()
            rows[identity] = value
            if level == 1:
                if left or top:
                    raise _invalid()
                pages[page] = (width, height)
        if not pages:
            raise _invalid()
        grouped = {}
        for identity, (numbers, confidence, text) in sorted(rows.items()):
            level, page, block, paragraph, line, word, left, top, width, height = numbers
            if page not in pages or left + width > pages[page][0] or top + height > pages[page][1]:
                raise _invalid()
            if level == 5 and text.strip():
                grouped.setdefault((page, block, paragraph, line), []).append(
                    {"text": text, "confidence": confidence, "bbox": [left, top, left + width, top + height]})
        spans, page_lines = [], {}
        for (page, block, paragraph, line), words in grouped.items():
            cursor = 0
            for word in words:
                word["start"] = cursor
                word["end"] = cursor + len(word["text"])
                cursor = word["end"] + 1
            page_lines[page] = page_lines.get(page, 0) + 1
            spans.append({"text": " ".join(word["text"] for word in words), "page": page,
                          "line": page_lines[page], "layout_id": [block, paragraph, line], "words": words,
                          "bbox": [min(word["bbox"][0] for word in words), min(word["bbox"][1] for word in words),
                                   max(word["bbox"][2] for word in words), max(word["bbox"][3] for word in words)]})
        return spans
    except (UnicodeError, csv.Error, ValueError, OverflowError) as exc:
        raise _invalid() from exc


def extract_ocr_spans(command: str, snapshot: Path) -> list[dict]:
    return parse_tsv(_run_bounded([command, str(snapshot), "stdout", "--psm", "6", "tsv"]))
