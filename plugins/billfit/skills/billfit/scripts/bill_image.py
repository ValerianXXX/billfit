"""Owned image preparation and evidence mapping; Pillow stays in its child."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
from bill_cancellation import check_cancelled
from billfit_errors import BillFitError
from bill_image_geometry import checked_size, original_box, transform, validate_options
from bill_process import run_bounded

ERRORS={
    "IMAGE_DEPENDENCY_REQUIRED":"Install the optional image-input requirements for local image preparation.",
    "IMAGE_PREPARATION_PIXEL_LIMIT":"Use an image of at most 25 megapixels and 20,000 pixels per side, including its expanded canvas.",
    "IMAGE_PREPARATION_FILE_LIMIT":"The prepared image exceeds the 25 MB limit.",
    "IMAGE_PREPARATION_PAGE_LIMIT":"Preparation supports one image page. Export the intended TIFF page separately.",
    "IMAGE_PREPARATION_FORMAT_UNSUPPORTED":"Preparation supports single-page PNG, JPEG or TIFF in RGB or grayscale formats.",
    "IMAGE_PREPARATION_OPTIONS_INVALID":"Use a finite clockwise angle from -360 to 360 degrees and a boolean deskew option.",
    "IMAGE_PREPARATION_INVALID":"The image preparation evidence was invalid.",
    "IMAGE_PREPARATION_FAILED":"The local image could not be prepared. Keep the original and provide a readable copy or verified fields.",
}


def prepare_image(source:Path,output:Path,*,rotation_degrees=0,deskew=False,timeout=10):
    rotation,deskew=validate_options(rotation_degrees,deskew)
    check_cancelled()
    raw=run_bounded([sys.executable,"-I",str(Path(__file__).with_name("bill_image_worker.py")),str(source),str(output),
        str(rotation),"true" if deskew else "false"],timeout=timeout,output_limit=16384,kind="IMAGE_PREPARATION")
    try:
        metadata=json.loads(raw)
        if isinstance(metadata,dict) and set(metadata)=={"error"} and metadata["error"] in ERRORS:
            raise BillFitError(metadata["error"],ERRORS[metadata["error"]])
        keys={"schema_version","source_size","prepared_size","source_to_prepared","prepared_to_source",
              "rotation_degrees","deskew_degrees","deskew_status","deskew_score_ratio","exif_orientation",
              "prepared_sha256","coordinate_system","estimator_version"}
        if not isinstance(metadata,dict) or set(metadata)!=keys or type(metadata["schema_version"]) is not int or metadata["schema_version"]!=1:
            raise ValueError()
        checked_size(metadata["source_size"]); checked_size(metadata["prepared_size"])
        angle=metadata["deskew_degrees"]
        status,ratio=metadata["deskew_status"],metadata["deskew_score_ratio"]
        if (type(angle) not in (int,float) or not -10<=angle<=10 or not math.isfinite(angle)
                or (not deskew and angle!=0) or type(metadata["rotation_degrees"]) not in (int,float)
                or metadata["rotation_degrees"]!=rotation
                or metadata["coordinate_system"]!="ORIGINAL_ENCODED_IMAGE_PIXELS" or metadata["estimator_version"]!="band-projection-v1"
                or status not in {"APPLIED","ALREADY_ALIGNED","INSUFFICIENT_EVIDENCE","AMBIGUOUS","NOT_REQUESTED"}
                or (status=="NOT_REQUESTED")!= (not deskew) or (status=="APPLIED")!= (angle!=0)):
            raise ValueError()
        if status in {"NOT_REQUESTED","INSUFFICIENT_EVIDENCE"}:
            if ratio is not None: raise ValueError()
        elif type(ratio) not in (int,float) or ratio<0 or not math.isfinite(ratio):
            raise ValueError()
        for name in ("source_to_prepared","prepared_to_source"):
            matrix=metadata[name]
            if (not isinstance(matrix,list) or len(matrix)!=6
                    or any(type(value) not in (int,float) or not -1_000_000<=value<=1_000_000
                           or not math.isfinite(value) for value in matrix)):
                raise ValueError()
        size,forward,backward=transform(metadata["source_size"],metadata["exif_orientation"],rotation+angle)
        if size!=metadata["prepared_size"] or forward!=metadata["source_to_prepared"] or backward!=metadata["prepared_to_source"]:
            raise ValueError()
        if output.stat().st_size>25_000_000: raise ValueError()
        prepared=output.read_bytes()
        if (prepared[:8]!=b"\x89PNG\r\n\x1a\n" or list(struct.unpack(">II",prepared[16:24]))!=size
                or hashlib.sha256(prepared).hexdigest()!=metadata["prepared_sha256"]):
            raise ValueError()
    except (ValueError,TypeError,KeyError,OSError,OverflowError,struct.error):
        raise BillFitError("IMAGE_PREPARATION_INVALID",ERRORS["IMAGE_PREPARATION_INVALID"]) from None
    check_cancelled()
    return metadata


def map_ocr_spans(spans,metadata):
    result=deepcopy(spans)
    for span in result:
        check_cancelled()
        if span["page"]!=1:
            raise BillFitError("OCR_OUTPUT_INVALID","Prepared-image evidence must refer to its single original page.")
        mapped=original_box(span["bbox"],metadata)
        span["prepared_bbox"],span["bbox"]=span["bbox"],mapped["bbox"]
        span["source_polygon"],span["source_box_clipped"]=mapped["polygon"],mapped["clipped"]
        span["image_preparation"]=metadata
        for word in span.get("words",[]):
            check_cancelled()
            mapped=original_box(word["bbox"],metadata)
            word["prepared_bbox"],word["bbox"]=word["bbox"],mapped["bbox"]
            word["source_polygon"]=mapped["polygon"]
            word["source_box_clipped"]=mapped["clipped"]
    return result
