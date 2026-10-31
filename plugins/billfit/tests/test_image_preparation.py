"""Frozen image/evidence contracts. Original synthetic pixels; no customer bills."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib
from PIL import Image, ImageDraw, ImageOps

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/billfit/scripts"
sys.path.insert(0, str(SCRIPTS))
from bill_input import extract_bill_fields
from billfit_errors import BillFitError


def image_fixture():
    image = Image.new("RGB", (120, 80), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 15, 29, 34), fill="red")
    draw.rectangle((75, 40, 89, 59), fill="blue")
    return image


def spans_fixture():
    text = "Energy Charges $12.34"
    return [{"text": text, "page": 1, "line": 1, "bbox": [10, 20, 30, 40],
             "words": [{"text": text, "start": 0, "end": len(text), "bbox": [10, 20, 30, 40], "confidence": 97}]}]


class ImagePreparationTests(unittest.TestCase):
    def test_quarter_rotations_match_independent_pixel_transposes(self):
        from bill_image import prepare_image
        choices = [(90, Image.Transpose.ROTATE_270), (180, Image.Transpose.ROTATE_180), (-90, Image.Transpose.ROTATE_90)]
        with tempfile.TemporaryDirectory(prefix="billfit-transform-test-") as temporary:
            root = Path(temporary)
            source = root / "original.png"
            original = image_fixture()
            original.save(source)
            before = source.read_bytes()
            for angle, transpose in choices:
                with self.subTest(angle=angle):
                    output = root / f"prepared-{angle}.png"
                    meta = prepare_image(source, output, rotation_degrees=angle)
                    with Image.open(output) as result:
                        expected = original.transpose(transpose)
                        self.assertEqual(result.size, expected.size)
                        self.assertEqual(result.convert("RGB").tobytes(), expected.tobytes())
                    self.assertEqual(meta["source_size"], [120, 80])
                    self.assertEqual(meta["rotation_degrees"], angle)
                    self.assertEqual(meta["prepared_sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
                    self.assertEqual(source.read_bytes(), before)

    def test_all_exif_orientations_retain_encoded_pixel_coordinates(self):
        from bill_image import prepare_image
        with tempfile.TemporaryDirectory(prefix="billfit-exif-test-") as temporary:
            root = Path(temporary)
            for orientation in range(1, 9):
                with self.subTest(orientation=orientation):
                    source, output = root / f"source-{orientation}.png", root / f"result-{orientation}.png"
                    exif = Image.Exif(); exif[274] = orientation
                    image_fixture().save(source, exif=exif)
                    meta = prepare_image(source, output)
                    with Image.open(source) as original, Image.open(output) as result:
                        expected = ImageOps.exif_transpose(original)
                        self.assertEqual(result.size, expected.size)
                        self.assertEqual(result.tobytes(), expected.tobytes())
                        self.assertNotIn(274, result.getexif())
                    self.assertEqual(meta["exif_orientation"], orientation)
                    self.assertEqual(meta["source_size"], [120, 80])

    def test_deskew_uses_pixels_and_does_not_guess_on_blank_input(self):
        from bill_image import prepare_image
        with tempfile.TemporaryDirectory(prefix="billfit-deskew-test-") as temporary:
            root = Path(temporary)
            horizontal = Image.new("RGB", (500, 500), "white")
            draw = ImageDraw.Draw(horizontal)
            for y in range(90, 400, 40):
                draw.line((90, y, 410, y), fill="black", width=3)
            tilted = horizontal.rotate(-6, resample=Image.Resampling.BICUBIC, fillcolor="white")
            source = root / "synthetic-lines.png"; tilted.save(source)
            meta = prepare_image(source, root / "upright.png", deskew=True)
            self.assertEqual(meta["deskew_status"], "APPLIED")
            self.assertAlmostEqual(meta["deskew_degrees"], -6, delta=0.6)
            Image.new("RGB", (200, 200), "white").save(source)
            blank = prepare_image(source, root / "blank.png", deskew=True)
            self.assertEqual(blank["deskew_degrees"], 0)
            self.assertEqual(blank["deskew_status"], "INSUFFICIENT_EVIDENCE")

    def test_original_candidate_box_is_mapped_from_prepared_pixels(self):
        with tempfile.TemporaryDirectory(prefix="billfit-map-test-") as temporary:
            source = Path(temporary) / "source.png"; image_fixture().save(source)
            before = source.read_bytes()
            calls = []
            def ocr(command, snapshot, **kwargs):
                calls.append(snapshot)
                with Image.open(snapshot) as prepared:
                    self.assertEqual(prepared.size, (80, 120))
                return spans_fixture()
            with patch.dict("os.environ", {"BILLFIT_TESSERACT_PATH": sys.executable}), patch("bill_input.extract_ocr_spans", side_effect=ocr):
                result = extract_bill_fields(str(source), ocr_rotation_degrees=90)
            self.assertEqual(len(calls), 1)
            self.assertFalse(calls[0].exists())
            row = result["candidates"][0]
            self.assertEqual(row["value"], "12.34")
            self.assertEqual(row["source"]["bbox"], [20, 50, 40, 70])
            self.assertEqual(row["source"]["image_size"], [120, 80])
            self.assertEqual(row["source"]["coordinate_system"], "ORIGINAL_ENCODED_IMAGE_PIXELS")
            self.assertEqual(row["source"]["sha256"], hashlib.sha256(before).hexdigest())
            self.assertIn("IMAGE_PREPARATION_REQUIRES_REVIEW", row["quality_flags"])
            self.assertFalse(result["automatic_confirmation"])
            self.assertFalse(result["automatic_calculation"])
            self.assertEqual(source.read_bytes(), before)

    def test_default_path_does_not_prepare_or_require_pillow(self):
        from bill_image import prepare_image
        with tempfile.TemporaryDirectory(prefix="billfit-default-test-") as temporary:
            source = Path(temporary) / "source.png"; image_fixture().save(source)
            with patch.dict("os.environ", {"BILLFIT_TESSERACT_PATH": sys.executable}), patch("bill_image.prepare_image") as prepare, patch("bill_input.extract_ocr_spans", return_value=spans_fixture()):
                result = extract_bill_fields(str(source))
            prepare.assert_not_called()
            self.assertEqual(result["candidates"][0]["source"]["bbox"], [10, 20, 30, 40])

    def test_invalid_parameters_fail_before_reading_any_file(self):
        for options in ({"ocr_rotation_degrees": True}, {"ocr_rotation_degrees": 361}, {"ocr_rotation_degrees": float("nan")},
                        {"ocr_rotation_degrees": "90"}, {"ocr_deskew": "true"}):
            with self.subTest(options=options), patch("bill_input._read_source") as read:
                with self.assertRaises(BillFitError) as error:
                    extract_bill_fields("missing-synthetic-input.png", **options)
                self.assertEqual(error.exception.code, "IMAGE_PREPARATION_OPTIONS_INVALID")
                read.assert_not_called()

    def test_pdf_preparation_is_explicitly_unsupported(self):
        with tempfile.TemporaryDirectory(prefix="billfit-pdf-option-test-") as temporary:
            source = Path(temporary) / "source.pdf"; source.write_bytes(b"%PDF-synthetic")
            with self.assertRaises(BillFitError) as error:
                extract_bill_fields(str(source), ocr_deskew=True)
            self.assertEqual(error.exception.code, "IMAGE_PREPARATION_FORMAT_UNSUPPORTED")

    def test_multiple_tiff_frames_are_not_silently_truncated(self):
        from bill_image import prepare_image
        with tempfile.TemporaryDirectory(prefix="billfit-tiff-test-") as temporary:
            source = Path(temporary) / "source.tiff"
            image_fixture().save(source, save_all=True, append_images=[image_fixture()])
            with self.assertRaises(BillFitError) as error:
                prepare_image(source, Path(temporary) / "prepared.png")
            self.assertEqual(error.exception.code, "IMAGE_PREPARATION_PAGE_LIMIT")

    def test_large_pixel_header_is_rejected_before_image_decode(self):
        from bill_image import prepare_image
        stream = io.BytesIO(); Image.new("RGB", (1, 1)).save(stream, format="PNG")
        data = bytearray(stream.getvalue())
        data[16:24] = struct.pack(">II", 10000, 10000)
        data[29:33] = struct.pack(">I", zlib.crc32(data[12:29]))
        with tempfile.TemporaryDirectory(prefix="billfit-pixel-test-") as temporary:
            source = Path(temporary) / "source.png"; source.write_bytes(data)
            with self.assertRaises(BillFitError) as error:
                prepare_image(source, Path(temporary) / "prepared.png")
            self.assertEqual(error.exception.code, "IMAGE_PREPARATION_PIXEL_LIMIT")

    def test_changed_prepared_file_fails_without_returning_candidates(self):
        with tempfile.TemporaryDirectory(prefix="billfit-prepared-change-") as temporary:
            source = Path(temporary) / "source.png"; image_fixture().save(source)
            def ocr(command, snapshot, **kwargs):
                snapshot.write_bytes(b"SYNTHETIC_CHANGED_PREPARED_IMAGE")
                return spans_fixture()
            with patch.dict("os.environ", {"BILLFIT_TESSERACT_PATH": sys.executable}), patch("bill_input.extract_ocr_spans", side_effect=ocr):
                with self.assertRaises(BillFitError) as error:
                    extract_bill_fields(str(source), ocr_rotation_degrees=90)
            self.assertEqual(error.exception.code, "BILL_SOURCE_CHANGED")

    def test_bad_worker_input_is_redacted_and_optional_dependency_is_explicit(self):
        worker = SCRIPTS / "bill_image_worker.py"
        with tempfile.TemporaryDirectory(prefix="billfit-image-worker-") as temporary:
            source = Path(temporary) / "source.png"; source.write_bytes(b"SYNTHETIC_PRIVATE_HEADER")
            output = Path(temporary) / "prepared.png"
            for no_site, expected in ((False, "IMAGE_PREPARATION_FAILED"), (True, "IMAGE_DEPENDENCY_REQUIRED")):
                with self.subTest(no_site=no_site):
                    command = [sys.executable, "-I", *(["-S"] if no_site else []), str(worker), str(source), str(output), "0", "false"]
                    completed = subprocess.run(command, capture_output=True, timeout=10)
                    self.assertEqual(completed.returncode, 0)
                    self.assertEqual(json.loads(completed.stdout), {"error": expected})
                    self.assertNotIn(b"SYNTHETIC_PRIVATE_HEADER", completed.stdout + completed.stderr)

    def test_mcp_schema_advertises_only_bounded_optional_controls(self):
        import mcp_server
        schema = next(tool["inputSchema"] for tool in mcp_server.TOOLS if tool["name"] == "billfit_extract_bill_fields")
        self.assertEqual(schema["required"], ["bill_file"])
        self.assertEqual(schema["properties"]["ocr_rotation_degrees"]["type"], "number")
        self.assertEqual(schema["properties"]["ocr_rotation_degrees"]["minimum"], -360)
        self.assertEqual(schema["properties"]["ocr_rotation_degrees"]["maximum"], 360)
        self.assertEqual(schema["properties"]["ocr_deskew"]["type"], "boolean")
        self.assertFalse(schema["additionalProperties"])
