"""Decoder, evidence and process boundary checks for optional image preparation."""
from copy import deepcopy
import asyncio
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from PIL import Image
from test_image_preparation import image_fixture, spans_fixture, SCRIPTS
from bill_cancellation import cancellation_scope
from bill_image import prepare_image
from bill_input import extract_bill_fields
from billfit_errors import BillFitError


class ImagePreparationRuntimeTests(unittest.TestCase):
    def test_tiff_orientation_preserves_original_encoded_grid(self):
        transposes = {1: None, 2: Image.Transpose.FLIP_LEFT_RIGHT,
                      3: Image.Transpose.ROTATE_180, 4: Image.Transpose.FLIP_TOP_BOTTOM,
                      5: Image.Transpose.TRANSPOSE, 6: Image.Transpose.ROTATE_270,
                      7: Image.Transpose.TRANSVERSE, 8: Image.Transpose.ROTATE_90}
        with tempfile.TemporaryDirectory(prefix="billfit-tiff-orientation-") as temporary:
            root = Path(temporary)
            for orientation, operation in transposes.items():
                with self.subTest(orientation=orientation):
                    source, output = root / f"source-{orientation}.tiff", root / f"output-{orientation}.png"
                    original = image_fixture()
                    original.save(source, tiffinfo={274: orientation})
                    expected = original if operation is None else original.transpose(operation)
                    metadata = prepare_image(source, output)
                    self.assertEqual(metadata["source_size"], [120, 80])
                    with Image.open(output) as result:
                        self.assertEqual(result.size, expected.size)
                        self.assertEqual(result.tobytes(), expected.tobytes())

    def test_jpeg_orientation_matches_decoded_source_pixels(self):
        from PIL import ImageOps
        with tempfile.TemporaryDirectory(prefix="billfit-jpeg-orientation-") as temporary:
            root = Path(temporary)
            source, output = root / "source.jpg", root / "output.png"
            exif = Image.Exif(); exif[274] = 6
            image_fixture().save(source, exif=exif, quality=95)
            prepare_image(source, output)
            with Image.open(source) as original, Image.open(output) as result:
                self.assertEqual(result.tobytes(), ImageOps.exif_transpose(original).tobytes())

    def test_inconsistent_worker_metadata_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="billfit-invalid-transform-") as temporary:
            root = Path(temporary)
            source, output = root / "source.png", root / "prepared.png"
            image_fixture().save(source)
            valid = prepare_image(source, output)
            changes = [{"rotation_degrees": False}, {"deskew_score_ratio": float("nan")},
                       {"deskew_status": "APPLIED", "deskew_degrees": 0},
                       {"deskew_status": "AMBIGUOUS"}, {"deskew_score_ratio": -1},
                       {"prepared_to_source": [True, 0, 0, 0, True, 0]}]
            for change in changes:
                with self.subTest(change=change):
                    metadata = {**valid, **change}
                    with patch("bill_image.run_bounded", return_value=json.dumps(metadata).encode()):
                        with self.assertRaises(BillFitError) as caught:
                            prepare_image(source, output)
                    self.assertEqual(caught.exception.code, "IMAGE_PREPARATION_INVALID")

    def test_unbounded_integer_is_an_options_error_not_an_overflow(self):
        with self.assertRaises(BillFitError) as caught:
            extract_bill_fields("missing.png", ocr_rotation_degrees=10**400)
        self.assertEqual(caught.exception.code, "IMAGE_PREPARATION_OPTIONS_INVALID")

    def test_cancellation_reaps_preparation_child_removes_temp_and_never_starts_ocr(self):
        stopped, children, snapshots = threading.Event(), [], []
        real_spawn = subprocess.Popen
        def cancelled():
            if stopped.is_set():
                raise asyncio.CancelledError()
        def spawn(command, **kwargs):
            child = real_spawn(command, **kwargs)
            children.append(child)
            snapshots.append(Path(command[3]))
            stopped.set()
            return child
        with tempfile.TemporaryDirectory(prefix="billfit-cancel-image-") as temporary:
            source = Path(temporary) / "source.png"; image_fixture().save(source)
            before = source.read_bytes()
            with cancellation_scope(cancelled), patch.dict("os.environ", {"BILLFIT_TESSERACT_PATH": sys.executable}), \
                    patch("bill_process.subprocess.Popen", side_effect=spawn), patch("bill_input.extract_ocr_spans") as ocr:
                with self.assertRaises(asyncio.CancelledError):
                    extract_bill_fields(str(source), ocr_deskew=True)
            ocr.assert_not_called()
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(len(children), 1)
            self.assertIsNotNone(children[0].poll())
            self.assertTrue(all(not path.exists() for path in snapshots))

    def test_ocr_receives_only_remaining_budget_and_source_polygons(self):
        with tempfile.TemporaryDirectory(prefix="billfit-image-budget-") as temporary:
            source = Path(temporary) / "source.png"; image_fixture().save(source)
            with patch.dict("os.environ", {"BILLFIT_TESSERACT_PATH": sys.executable}), \
                    patch("bill_input.extract_ocr_spans", return_value=spans_fixture()) as ocr:
                result = extract_bill_fields(str(source), ocr_rotation_degrees=90)
            self.assertGreater(ocr.call_args.kwargs["timeout"], 0)
            self.assertLess(ocr.call_args.kwargs["timeout"], 30)
            source = result["candidates"][0]["source"]
            self.assertEqual(source["prepared_bbox"], [10, 20, 30, 40])
            self.assertEqual(source["source_polygons"], [[[20, 70], [20, 50], [40, 50], [40, 70]]])
            self.assertFalse(source["source_box_clipped"])

