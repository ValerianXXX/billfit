"""Render source/derived evidence for the two fixed synthetic OCR repair cases."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/billfit/skills/billfit/scripts"))
from bill_image import prepare_image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    assert receipt["synthetic_only"] and receipt["preparation_profile"]["synthetic_only"]
    directory = ROOT / "plugins/billfit/tests/fixtures/bill-input-v2"
    raw_manifest = (directory / "manifest.json").read_bytes()
    assert hashlib.sha256(raw_manifest).hexdigest() == receipt["manifestSha256"]
    manifest = {row["id"]: row for row in json.loads(raw_manifest)["cases"]}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for row in receipt["results"]:
        if row["id"] not in {"skew-6-degrees", "rotated-90-degrees"}:
            continue
        case = manifest[row["id"]]
        source = directory / case["file"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == case["sha256"]
        with tempfile.TemporaryDirectory(prefix="billfit-evidence-render-") as temporary:
            prepared = Path(temporary) / "prepared.png"
            meta = prepare_image(source, prepared, rotation_degrees=row["options"].get("ocr_rotation_degrees", 0), deskew=row["options"]["ocr_deskew"])
            assert meta == row["result"]["image_preparation"]
            with Image.open(source) as original_file, Image.open(prepared) as prepared_file:
                original, derived = original_file.convert("RGB"), prepared_file.convert("RGB")
            left, right = ImageDraw.Draw(original), ImageDraw.Draw(derived)
            for candidate in row["result"]["candidates"]:
                evidence = candidate["source"]
                assert evidence["sha256"] == case["sha256"]
                left.rectangle(evidence["bbox"], outline="#c73e25", width=3)
                for polygon in evidence["source_polygons"]:
                    left.line([tuple(point) for point in polygon] + [tuple(polygon[0])], fill="#225db0", width=2)
                right.rectangle(evidence["prepared_bbox"], outline="#225db0", width=3)
            original.thumbnail((660, 700)); derived.thumbnail((660, 700))
            canvas = Image.new("RGB", (1380, 850), "#f3f5f8")
            draw = ImageDraw.Draw(canvas)
            title, body = ImageFont.load_default(size=22), ImageFont.load_default(size=16)
            draw.text((25, 15), "SYNTHETIC TEST ONLY - NOT A UTILITY BILL OR CUSTOMER RESULT", font=title, fill="#152b49")
            draw.text((25, 55), "Original encoded pixels: red bounds, blue evidence polygons", font=body, fill="#152b49")
            draw.text((715, 55), "Temporary corrected OCR input: blue evidence bounds", font=body, fill="#152b49")
            canvas.paste(original, (25, 90)); canvas.paste(derived, (715, 90))
            draw.text((25, 790), f"{case['id']}: manual rotation {meta['rotation_degrees']:g} deg; pixel deskew {meta['deskew_degrees']:g} deg ({meta['deskew_status']}).", font=body, fill="#152b49")
            draw.text((25, 820), "All fields require source review. Boxes show provenance, not a guarantee that OCR text is correct.", font=body, fill="#152b49")
            output = args.output_dir / f"{case['id']}-20261031.png"
            with output.open("xb") as stream:
                canvas.save(stream, format="PNG")
            outputs.append({"file": output.name, "sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "prepared_hash_verified": True})
    print(json.dumps(outputs))


if __name__ == "__main__":
    main()
