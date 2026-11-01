"""Declared Green Button quantity meaning and reading-quality boundaries.

No tariff arithmetic, account mapping, cumulative differencing or inferred
direction lives here. Schema references and supported scope are in the dated
ESPI guide; this small profile is not full ESPI/XSD certification.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from xml.etree.ElementTree import Element

from billfit_errors import BillFitError

REVIEW_MARKERS=('ESPI_READING_METADATA_REVIEW','ESPI_READING_QUALITY_REVIEW')
MEANING={'accumulationBehaviour':4,'commodity':1,'flowDirection':1,'kind':12}
FINAL_UNMODIFIED_QUALITY={0,19}

def local_name(element: Element) -> str:
    return element.tag.rsplit('}',1)[-1]

def _namespace_ok(element: Element) -> bool:
    return not element.tag.startswith('{') or element.tag.startswith('{http://naesb.org/espi}')

def single_text(parent: Element, name: str) -> str | None:
    matches=[node for node in parent.iter() if node is not parent and local_name(node)==name]
    if len(matches)>1:
        raise BillFitError('AMBIGUOUS_ESPI_METADATA',f'ESPI {name} occurs more than once; no value was selected.')
    if not matches:
        return None
    node=matches[0]
    value=(node.text or '').strip()
    if node not in list(parent) or not _namespace_ok(node) or len(node) or not value:
        raise BillFitError('INVALID_ESPI_METADATA',f'ESPI {name} needs one direct, nonempty field in the supported namespace.')
    return value

def _code(value: str | None, name: str) -> int | None:
    if value is None:
        return None
    if not re.fullmatch(r'\+?[0-9]{1,5}',value) or int(value)>65535:
        raise BillFitError('INVALID_ESPI_METADATA',f'ESPI {name} needs a supported nonnegative integer code; no label was guessed.')
    return int(value)

def reading_requires_review(warnings: list[str]) -> bool:
    return any(warning.startswith(marker+':') for warning in warnings for marker in REVIEW_MARKERS)

@dataclass(frozen=True)
class ReadingProfile:
    default_quality: int | None
    unresolved_fields: tuple[str,...]

    def warnings(self) -> list[str]:
        if not self.unresolved_fields:
            return []
        return [REVIEW_MARKERS[0]+': Missing or unspecified ReadingType fields: '+
                ', '.join(self.unresolved_fields)+'. Confirm a utility file of incremental imported electric energy; no quantity meaning was inferred.']

    def quality(self, reading: Element) -> tuple[int | None,...]:
        nodes=[node for node in reading.iter() if local_name(node)=='ReadingQuality']
        if not nodes:
            return (self.default_quality,)
        values=[]
        for node in nodes:
            if node not in list(reading) or not _namespace_ok(node):
                raise BillFitError('INVALID_ESPI_METADATA','ReadingQuality must be a direct supported-namespace field of its interval.')
            if len(node):
                if (node.text or '').strip():
                    raise BillFitError('INVALID_ESPI_METADATA','ReadingQuality cannot combine scalar and structured codes.')
                value=single_text(node,'quality')
            else:
                value=(node.text or '').strip()
            if not value:
                raise BillFitError('INVALID_ESPI_METADATA','ReadingQuality must contain an explicit quality code.')
            values.append(_code(value,'ReadingQuality'))
        return tuple(values)

def reading_profile(root: Element, reading_type: Element) -> ReadingProfile:
    if not _namespace_ok(reading_type):
        raise BillFitError('INVALID_ESPI_METADATA','ReadingType uses an unsupported XML namespace.')
    if sum(local_name(node)=='MeterReading' for node in root.iter())>1:
        raise BillFitError('MULTIPLE_ESPI_METER_READINGS','Separate meter-reading streams; a shared unit does not authorize adding them together.')
    for service in (node for node in root.iter() if local_name(node)=='ServiceCategory'):
        kind=_code(single_text(service,'kind'),'ServiceCategory.kind')
        if kind is not None and kind!=0:
            raise BillFitError('UNSUPPORTED_ESPI_SERVICE_KIND','Only electricity service is supported; other service categories cannot be priced as electricity.')
    unresolved=[]
    for name,required in MEANING.items():
        value=_code(single_text(reading_type,name),name)
        if value in (None,0):
            unresolved.append(name)
        elif value!=required:
            raise BillFitError('UNSUPPORTED_ESPI_READING_TYPE',
                f'ESPI {name} is outside the incremental forward metered-electric-energy profile. Obtain a utility file of incremental imported energy; do not relabel or add cumulative/net/export readings.')
    qualifier=_code(single_text(reading_type,'dataQualifier'),'dataQualifier')
    if qualifier not in (None,0,12):
        raise BillFitError('UNSUPPORTED_ESPI_READING_TYPE','Average, extrema, threshold and other qualified readings cannot be added as ordinary interval consumption.')
    default=_code(single_text(reading_type,'defaultQuality'),'defaultQuality')
    return ReadingProfile(default,tuple(sorted(unresolved)))

def quality_warning(reviewed_intervals: int, codes: set[int | None]) -> str | None:
    if not reviewed_intervals:
        return None
    numeric=sorted(code for code in codes if code is not None)
    labels=(["unspecified"] if None in codes else [])+[str(code) for code in numeric[:16]]
    if len(numeric)>16:
        labels.append('additional codes omitted from this summary')
    return (REVIEW_MARKERS[1]+f': {reviewed_intervals} interval(s) have unspecified, adjusted, estimated or other review-required quality ('+
            ', '.join(labels)+'). Preserve the source and confirm its measurement basis before switching guidance or bill validation. These flags do not certify the utility bill.')
