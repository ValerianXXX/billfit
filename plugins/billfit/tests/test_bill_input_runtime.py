"""Owned local process, PDF and source-location checks; synthetic inputs only."""
from __future__ import annotations

import hashlib
import asyncio
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/billfit/scripts"
sys.path.insert(0, str(SCRIPTS))
from bill_input import extract_bill_fields, extract_spans
from bill_ocr import _run_bounded, parse_tsv
from billfit_errors import BillFitError
from test_bill_input_evidence import HEADER, PAGE, TSV, WORDS, FakeProcess


class LocalOcrRuntimeTests(unittest.TestCase):
    def process_failure(self, script, code, **options):
        real_popen = subprocess.Popen
        children = []
        def spawn(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append(child)
            return child
        with patch("bill_process.subprocess.Popen", side_effect=spawn):
            with self.assertRaises(BillFitError) as caught:
                _run_bounded([sys.executable, "-c", script], **options)
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(caught.exception.as_dict()))
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())
        return caught.exception

    def test_actual_child_stdout_and_stderr_do_not_deadlock(self):
        result = _run_bounded([sys.executable, "-c",
            "import os; os.write(2,b'e'*250000); os.write(1,b'o'*250000)"], output_limit=600000, timeout=5)
        self.assertEqual(result, b"o" * 250000)

    def test_actual_child_stdout_overflow_is_killed_and_reaped(self):
        self.process_failure("import os,time; os.write(1,b'x'*5000000); time.sleep(30)",
                             "OCR_OUTPUT_LIMIT", output_limit=32000, timeout=5)

    def test_actual_child_stderr_is_bounded_too(self):
        self.process_failure("import os,time; os.write(2,b'SYNTHETIC_PRIVATE'*300000); time.sleep(30)",
                             "OCR_OUTPUT_LIMIT", output_limit=32000, timeout=5)

    def test_actual_stalled_child_has_one_deadline_and_is_reaped(self):
        started = time.monotonic()
        self.process_failure("import time; time.sleep(30)", "LOCAL_OCR_TIMEOUT", timeout=0.3)
        self.assertLess(time.monotonic() - started, 5)

    def test_actual_child_nonzero_exit_is_redacted(self):
        self.process_failure("import sys; sys.stderr.write('SYNTHETIC_PRIVATE'); sys.exit(7)", "LOCAL_OCR_FAILED", timeout=5)

    def test_missing_executable_is_a_redacted_domain_error(self):
        with self.assertRaises(BillFitError) as caught:
            _run_bounded(["nonexistent-synthetic-billfit-command"])
        self.assertEqual(caught.exception.code, "LOCAL_OCR_FAILED")

    def test_tsv_preserves_literal_quote_words(self):
        text = TSV.replace("\tEnergy\n", '\t"Energy\n')
        self.assertEqual(parse_tsv(text.encode())[0]["text"], '"Energy Charges $12.34')

    def test_unknown_confidence_is_not_a_zero_or_a_probability(self):
        spans = parse_tsv(TSV.replace("\t32\t", "\t-1\t").encode())
        result = extract_spans(spans, "synthetic", "LOCAL_TESSERACT_OCR")
        row = result["candidates"][0]
        self.assertEqual(row["source"]["ocr_confidence"]["unknown_words"], 1)
        self.assertEqual(row["source"]["ocr_confidence"]["minimum"], 95)
        self.assertIn("OCR_CONFIDENCE_UNKNOWN", row["quality_flags"])
        self.assertFalse(row["source"]["ocr_confidence"]["calibrated"])

    def test_invalid_utf8_and_missing_page_evidence_fail_closed(self):
        for raw in (b"\xff", (HEADER + "\n" + "\n".join(WORDS) + "\n").encode()):
            with self.subTest(raw=raw[:10]):
                with self.assertRaises(BillFitError) as caught:
                    parse_tsv(raw)
                self.assertEqual(caught.exception.code, "OCR_OUTPUT_INVALID")

    def test_word_source_box_excludes_unrelated_text_on_same_line(self):
        rows = WORDS + ["5\t1\t1\t1\t1\t4\t400\t100\t100\t20\t0\t;"]
        spans = parse_tsv(("\n".join([HEADER, PAGE, *rows]) + "\n").encode())
        row = extract_spans(spans, "synthetic", "LOCAL_TESSERACT_OCR")["candidates"][0]
        self.assertEqual(row["source"]["bbox"], [50, 100, 320, 120])
        self.assertEqual(row["source"]["ocr_confidence"]["minimum"], 32)
        self.assertEqual(row["source"]["quote"], "Energy Charges $12.34")

    def test_owned_snapshot_is_removed_after_output_error(self):
        snapshots = []
        with tempfile.TemporaryDirectory(prefix="billfit-source-test-") as directory:
            source = Path(directory) / "input.png"
            source.write_bytes(b"SYNTHETIC_IMAGE")
            def process(command, **kwargs):
                snapshots.append(Path(command[1]))
                return FakeProcess(command, output="invalid TSV\n", **kwargs)
            with patch.dict("os.environ", {"BILLFIT_TESSERACT_PATH": sys.executable}), patch("subprocess.Popen", side_effect=process):
                with self.assertRaises(BillFitError):
                    extract_bill_fields(str(source))
            self.assertTrue(source.exists())
        self.assertEqual(len(snapshots), 1)
        self.assertFalse(snapshots[0].exists())


@unittest.skipUnless(importlib.util.find_spec("pypdf"), "optional PDF dependencies unavailable")
class RealPdfInputTests(unittest.TestCase):
    def test_repeated_pdf_retains_two_pages_without_addition(self):
        fixture = Path(__file__).parent / "fixtures/bill-input-v2/repeated-synthetic-pages.pdf"
        result = extract_bill_fields(str(fixture))
        self.assertEqual(len(result["candidates"]), 10)
        self.assertEqual(result["source_sha256"], hashlib.sha256(fixture.read_bytes()).hexdigest())
        charges = [row for row in result["candidates"] if row["field"] == "reported_energy_charge"]
        self.assertEqual([(row["source"]["page"], row["value"]) for row in charges], [(1, "12.34"), (2, "12.34")])
        self.assertEqual(result["conflicting_fields"], [])
        self.assertFalse(result["automatic_calculation"])

    def test_actual_cli_parser_error_does_not_echo_input_or_traceback(self):
        with tempfile.TemporaryDirectory(prefix="billfit-bad-pdf-") as directory:
            fixture = Path(directory) / "input.pdf"
            fixture.write_bytes(b"LEAK! SYNTHETIC_PRIVATE_DOCUMENT")
            completed = subprocess.run([sys.executable, str(SCRIPTS / "billfit_cli.py"), "extract-bill",
                                        "--input-json", json.dumps({"bill_file": str(fixture)})],
                                       capture_output=True, text=True, timeout=5)
        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn("LEAK!", completed.stdout + completed.stderr)
        self.assertNotIn("SYNTHETIC_PRIVATE", completed.stdout + completed.stderr)
        self.assertNotIn("Traceback", completed.stdout + completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["error"]["code"], "PDF_TEXT_FAILED")

    def test_encrypted_and_over_page_limit_pdfs_have_fixed_errors(self):
        from pypdf import PdfWriter
        for pages, encrypted in [(1, True), (26, False)]:
            with self.subTest(pages=pages, encrypted=encrypted), tempfile.TemporaryDirectory(prefix="billfit-pdf-limit-") as directory:
                writer = PdfWriter()
                for _ in range(pages):
                    writer.add_blank_page(width=612, height=792)
                if encrypted:
                    writer.encrypt("synthetic-test-password")
                path = Path(directory) / "test.pdf"
                writer.write(path)
                with self.assertRaises(BillFitError) as caught:
                    extract_bill_fields(str(path))
                self.assertEqual(caught.exception.code, "PDF_LIMIT")

    def test_pdf_source_change_during_child_parsing_cannot_rebind_evidence(self):
        fixture = Path(__file__).parent / "fixtures/bill-input-v2/repeated-synthetic-pages.pdf"
        real_popen = subprocess.Popen
        with tempfile.TemporaryDirectory(prefix="billfit-pdf-change-") as directory:
            source = Path(directory) / "input.pdf"
            source.write_bytes(fixture.read_bytes())
            snapshots = []
            def spawn(command, **kwargs):
                snapshots.append(Path(command[-1]))
                self.assertNotEqual(snapshots[-1], source)
                source.write_bytes(b"changed original")
                return real_popen(command, **kwargs)
            with patch("bill_process.subprocess.Popen", side_effect=spawn):
                with self.assertRaises(BillFitError) as caught:
                    extract_bill_fields(str(source))
            self.assertEqual(caught.exception.code, "BILL_SOURCE_CHANGED")
            self.assertFalse(snapshots[0].exists())

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "optional MCP SDK unavailable")
    def test_real_stdio_pdf_error_and_recovery_preserve_review_requirement(self):
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters
        fixture = Path(__file__).parent / "fixtures/bill-input-v2/repeated-synthetic-pages.pdf"
        async def scenario(mode, invalid):
            params = StdioServerParameters(command=sys.executable, args=[str(SCRIPTS / "mcp_server.py"), "--sdk"])
            async with Client(params, mode=mode) as client:
                bad = await client.call_tool("billfit_extract_bill_fields", {"bill_file": str(invalid)})
                self.assertTrue(bad.is_error)
                self.assertEqual(bad.structured_content["error"]["code"], "PDF_TEXT_FAILED")
                good = await client.call_tool("billfit_extract_bill_fields", {"bill_file": str(fixture)})
                self.assertFalse(good.is_error)
                result = good.structured_content
                self.assertEqual(result["status"], "REVIEW_REQUIRED")
                self.assertEqual(len(result["candidates"]), 10)
                self.assertTrue(all(row["status"] == "NEEDS_USER_CONFIRMATION" for row in result["candidates"]))
                self.assertFalse(result["automatic_calculation"])
                self.assertFalse(result["automatic_confirmation"])
        with tempfile.TemporaryDirectory(prefix="billfit-mcp-pdf-") as directory:
            invalid = Path(directory) / "invalid.pdf"
            invalid.write_bytes(b"SYNTHETIC MALFORMED PDF")
            for mode in ["2026-07-28", "legacy"]:
                asyncio.run(scenario(mode, invalid))


if __name__ == "__main__":
    unittest.main()
