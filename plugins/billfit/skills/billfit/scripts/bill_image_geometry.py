"""Image-edge affine coordinates; independent of OCR text and calculator rules."""
from __future__ import annotations
import math
from billfit_errors import BillFitError

MAX_PIXELS = 25_000_000


def validate_options(rotation_degrees=0, deskew=False):
    if (type(rotation_degrees) not in (int, float) or not -360 <= rotation_degrees <= 360
            or not math.isfinite(rotation_degrees) or type(deskew) is not bool):
        raise BillFitError("IMAGE_PREPARATION_OPTIONS_INVALID", "Use a finite clockwise rotation from -360 to 360 degrees and a boolean deskew option.")
    return float(rotation_degrees), deskew


def checked_size(size):
    if (not isinstance(size, (list, tuple)) or len(size) != 2
            or any(type(value) is not int or not 1 <= value <= 20000 for value in size)
            or size[0] * size[1] > MAX_PIXELS):
        raise BillFitError("IMAGE_PREPARATION_PIXEL_LIMIT", "Use a single image of at most 25 megapixels and 20,000 pixels per side.")
    return tuple(size)


def point(matrix, x, y):
    a, b, c, d, e, f = matrix
    return a*x + b*y + c, d*x + e*y + f


def compose(left, right):
    a,b,c,d,e,f = left; g,h,i,j,k,l = right
    return [a*g+b*j, a*h+b*k, a*i+b*l+c, d*g+e*j, d*h+e*k, d*i+e*l+f]


def inverse(matrix):
    a,b,c,d,e,f = matrix
    det = a*e-b*d
    if not math.isfinite(det) or abs(det) < 1e-8:
        raise BillFitError("IMAGE_PREPARATION_INVALID", "The image coordinate transform is invalid.")
    return [e/det, -b/det, (b*f-e*c)/det, -d/det, a/det, (d*c-a*f)/det]


def transform(size, orientation, clockwise_degrees):
    width, height = checked_size(size)
    if type(orientation) is not int or not 1 <= orientation <= 8:
        raise BillFitError("IMAGE_PREPARATION_INVALID", "The image orientation metadata is invalid.")
    orientations = {
        1:[1,0,0,0,1,0], 2:[-1,0,width,0,1,0], 3:[-1,0,width,0,-1,height],
        4:[1,0,0,0,-1,height], 5:[0,1,0,1,0,0], 6:[0,-1,height,1,0,0],
        7:[0,-1,height,-1,0,width], 8:[0,1,0,-1,0,width],
    }
    oriented_width, oriented_height = (height,width) if orientation >= 5 else (width,height)
    angle = math.radians(clockwise_degrees % 360)
    cosine, sine = round(math.cos(angle), 12), round(math.sin(angle), 12)
    rotation = [cosine,-sine,0,sine,cosine,0]
    corners = [point(rotation,x,y) for x,y in ((0,0),(oriented_width,0),(oriented_width,oriented_height),(0,oriented_height))]
    minimum_x, minimum_y = min(x for x,y in corners), min(y for x,y in corners)
    rotation[2], rotation[5] = -minimum_x, -minimum_y
    prepared = [math.ceil(max(x for x,y in corners)-minimum_x-1e-9), math.ceil(max(y for x,y in corners)-minimum_y-1e-9)]
    checked_size(prepared)
    forward = compose(rotation, orientations[orientation])
    return prepared, forward, inverse(forward)


def original_box(box, metadata):
    prepared_width, prepared_height = metadata["prepared_size"]
    if (not isinstance(box, (list,tuple)) or len(box) != 4
            or any(type(value) not in (int,float) or not math.isfinite(value) for value in box)
            or not 0 <= box[0] < box[2] <= prepared_width or not 0 <= box[1] < box[3] <= prepared_height):
        raise BillFitError("OCR_OUTPUT_INVALID", "OCR returned a region outside the prepared image.")
    vertices = [point(metadata["prepared_to_source"],x,y) for x,y in
                ((box[0],box[1]),(box[2],box[1]),(box[2],box[3]),(box[0],box[3]))]
    width, height = metadata["source_size"]
    clipped = any(not -1e-7 <= x <= width+1e-7 or not -1e-7 <= y <= height+1e-7 for x,y in vertices)
    # Clip the inverse quadrilateral to original image edges, preserving its
    # intersection rather than assigning off-image pixels to source evidence.
    for axis, bound, lower in ((0,0,True),(0,width,False),(1,0,True),(1,height,False)):
        output=[]
        for index, current in enumerate(vertices):
            previous=vertices[index-1]
            inside=lambda p: p[axis] >= bound if lower else p[axis] <= bound
            if inside(current) != inside(previous):
                fraction=(bound-previous[axis])/(current[axis]-previous[axis])
                output.append(tuple(previous[i]+fraction*(current[i]-previous[i]) for i in (0,1)))
            if inside(current): output.append(current)
        vertices=output
        if not vertices: raise BillFitError("OCR_OUTPUT_INVALID", "OCR returned a region with no original-image evidence.")
    coordinates = [[round(max(0,min(width,x)),6),round(max(0,min(height,y)),6)] for x,y in vertices]
    bbox = [max(0,math.floor(min(x for x,y in coordinates))), max(0,math.floor(min(y for x,y in coordinates))),
            min(width,math.ceil(max(x for x,y in coordinates))), min(height,math.ceil(max(y for x,y in coordinates)))]
    if bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
        raise BillFitError("OCR_OUTPUT_INVALID", "OCR returned empty source evidence.")
    return {"bbox":bbox,"polygon":coordinates,"clipped":clipped}
