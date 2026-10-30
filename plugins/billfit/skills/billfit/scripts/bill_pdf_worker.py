"""Private one-shot PDF worker. Parent owns the snapshot and captures stderr.

Only fixed error codes or bounded text spans are emitted on stdout. Keeping
pypdf in this child also keeps its global log configuration out of the MCP host.
This is not an OS memory sandbox; PDF decompression may still consume RAM.
"""
from __future__ import annotations
import json
from pathlib import Path
import sys

MAX_FILE_BYTES = 25_000_000
MAX_TEXT_CHARS = 1_000_000
MAX_LINES = 50_000


def read_pdf(path: Path) -> dict:
    try:
        from pypdf import PdfReader
    except ImportError:
        return {"error": "PDF_DEPENDENCY_REQUIRED"}
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return {"error": "BILL_FILE_LIMIT"}
        reader = PdfReader(path)
        if reader.is_encrypted or len(reader.pages) > 25:
            return {"error": "PDF_LIMIT"}
        spans, total = [], 0
        for number, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            total += len(text)
            if total > MAX_TEXT_CHARS:
                return {"error": "BILL_TEXT_LIMIT"}
            for line, value in enumerate(text.splitlines(), 1):
                if len(spans) >= MAX_LINES:
                    return {"error": "BILL_TEXT_LIMIT"}
                spans.append({"text": value, "page": number, "line": line})
        return {"spans": spans}
    except Exception:
        return {"error": "PDF_TEXT_FAILED"}


if __name__ == "__main__":
    # Explicit UTF-8 does not depend on the user's Windows console encoding.
    result = read_pdf(Path(sys.argv[1])) if len(sys.argv) == 2 else {"error": "PDF_TEXT_FAILED"}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
