"""Optional Pillow preparation in an owned child; fixed, value-free diagnostics."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys
import warnings
from statistics import median

sys.path.insert(0,str(Path(__file__).resolve().parent))
from bill_image_geometry import MAX_PIXELS, checked_size, transform, validate_options
from billfit_errors import BillFitError


def estimate_deskew(image):
    from PIL import Image
    preview=image.convert("L")
    preview.thumbnail((800,800),Image.Resampling.LANCZOS)
    # Pixel geometry only: no field parsing, OCR retries or amount-based selection.
    ink=preview.point(lambda value: 0 if value < 200 else 255)
    ink_count=ink.tobytes().count(0)
    if ink_count < 30 or not 0.0005 <= ink_count/(ink.width*ink.height) <= 0.5:
        return 0.0,"INSUFFICIENT_EVIDENCE",None
    def score(angle):
        rotated=ink.rotate(-angle,resample=Image.Resampling.NEAREST,fillcolor=255)
        raw=rotated.tobytes(); width=rotated.width
        rows=[raw[start:start+width].count(0) for start in range(0,len(raw),width)]
        # Page borders/full-width rules must not dominate a text-line estimate.
        rows=[value if value < width*0.85 else 0 for value in rows]
        bands=[]
        # An upright letterhead must not outweigh several body text regions.
        # Give each nonempty horizontal band equal influence, using pixels only.
        for index in range(4):
            band=rows[index*len(rows)//4:(index+1)*len(rows)//4]
            count=sum(band)
            if count>=30:
                bands.append(sum((right-left)**2 for left,right in zip(band,band[1:]))/count)
        return median(bands) if bands else 0.0
    coarse={float(angle):score(angle) for angle in range(-10,11)}
    best=max(coarse,key=coarse.get)
    fine={round(best+offset/4,2):score(best+offset/4) for offset in range(-3,4)
          if -10 <= best+offset/4 <= 10}
    best=max(fine,key=fine.get); highest=fine[best]; baseline=coarse[0.0]
    alternative=max(value for angle,value in coarse.items() if abs(angle-best)>=2)
    ratio=highest/max(baseline,1e-9)
    if abs(best)<0.25:
        return 0.0,"ALREADY_ALIGNED",round(ratio,5)
    if abs(best)>=9.75 or ratio<1.2 or highest<alternative*1.05:
        return 0.0,"AMBIGUOUS",round(ratio,5)
    return best,"APPLIED",round(ratio,5)


def prepare(source, output, rotation, deskew):
    try:
        from PIL import Image
    except ImportError:
        raise BillFitError("IMAGE_DEPENDENCY_REQUIRED", "Install the optional image-input requirements.") from None
    Image.MAX_IMAGE_PIXELS=MAX_PIXELS
    try:
        if source.stat().st_size > 25_000_000 or output.exists() or source.resolve()==output.resolve():
            raise BillFitError("IMAGE_PREPARATION_FAILED", "Use a bounded original and a fresh temporary output.")
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            with Image.open(source) as original:
                is_tiff=original.format=="TIFF"
                # Pillow 13 reports/decodes TIFF in display orientation. Its
                # public width/height tags retain the encoded source grid.
                size=list(checked_size((original.tag_v2[256],original.tag_v2[257]) if is_tiff else original.size))
                if original.format not in {"PNG","JPEG","TIFF"} or original.mode not in {"1","L","LA","P","RGB","RGBA"}:
                    raise BillFitError("IMAGE_PREPARATION_FORMAT_UNSUPPORTED", "Use a supported single-page RGB or grayscale image.")
                if getattr(original,"n_frames",1) != 1:
                    raise BillFitError("IMAGE_PREPARATION_PAGE_LIMIT", "Image preparation requires one page. Export the intended TIFF page separately.")
                orientation=original.getexif().get(274,1)
                prepared,forward,backward=transform(size,orientation,rotation)
                original.load()
                if original.mode in {"RGBA","LA"} or "transparency" in original.info:
                    rgba=original.convert("RGBA"); image=Image.new("RGB",original.size,"white")
                    image.paste(rgba,mask=rgba.getchannel("A"))
                else:
                    image=original.convert("RGB")
                if is_tiff and orientation!=1:
                    # Undo the decoder's lossless orientation first; the one
                    # affine map below must start in original encoded pixels.
                    undo={2:Image.Transpose.FLIP_LEFT_RIGHT,3:Image.Transpose.ROTATE_180,
                          4:Image.Transpose.FLIP_TOP_BOTTOM,5:Image.Transpose.TRANSPOSE,
                          6:Image.Transpose.ROTATE_90,7:Image.Transpose.TRANSVERSE,
                          8:Image.Transpose.ROTATE_270}
                    restored=image.transpose(undo[orientation]); image.close(); image=restored
                if list(image.size)!=size:
                    raise BillFitError("IMAGE_PREPARATION_INVALID", "The decoder did not preserve the encoded source grid.")
            skew,status,ratio=0.0,"NOT_REQUESTED",None
            if deskew:
                oriented=image.transform(tuple(prepared),Image.Transform.AFFINE,tuple(backward),
                    resample=Image.Resampling.BICUBIC,fillcolor="white")
                skew,status,ratio=estimate_deskew(oriented)
                oriented.close()
                prepared,forward,backward=transform(size,orientation,rotation+skew)
            result=image.transform(tuple(prepared),Image.Transform.AFFINE,tuple(backward),
                resample=Image.Resampling.BICUBIC,fillcolor="white")
            # Strip inherited EXIF so clients do not rotate the prepared PNG twice.
            result.info.clear()
            with output.open("xb") as stream: result.save(stream,format="PNG")
            result.close(); image.close()
            if output.stat().st_size > 25_000_000:
                raise BillFitError("IMAGE_PREPARATION_FILE_LIMIT", "The prepared image exceeds the byte limit.")
            return {"schema_version":1,"source_size":size,"prepared_size":prepared,
                "source_to_prepared":forward,"prepared_to_source":backward,"rotation_degrees":rotation,
                "deskew_degrees":skew,"deskew_status":status,"deskew_score_ratio":ratio,
                "exif_orientation":orientation,"prepared_sha256":hashlib.sha256(output.read_bytes()).hexdigest(),
                "coordinate_system":"ORIGINAL_ENCODED_IMAGE_PIXELS","estimator_version":"band-projection-v1"}
    except (Image.DecompressionBombError,Image.DecompressionBombWarning):
        raise BillFitError("IMAGE_PREPARATION_PIXEL_LIMIT", "The image exceeds the pixel limit.") from None


def main():
    try:
        if len(sys.argv)!=5 or sys.argv[4] not in {"true","false"}: raise ValueError()
        rotation,deskew=validate_options(float(sys.argv[3]),sys.argv[4]=="true")
        value=prepare(Path(sys.argv[1]),Path(sys.argv[2]),rotation,deskew)
    except BillFitError as error:
        value={"error":error.code}
    except Exception:
        value={"error":"IMAGE_PREPARATION_FAILED"}
    sys.stdout.write(json.dumps(value,allow_nan=False)+"\n")


if __name__ == "__main__": main()
