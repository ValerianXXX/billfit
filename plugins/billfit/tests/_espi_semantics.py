"""Synthetic input generator shared by the frozen API and CLI comparisons."""
import json
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring

ROOT=Path(__file__).resolve().parents[3]
FIXTURE=ROOT/'evaluations/espi-semantics/cases.json'
CASES=json.loads(FIXTURE.read_text(encoding='utf8'))['cases']
FIELDS={'accumulationBehaviour':'4','commodity':'1','flowDirection':'1','kind':'12',
        'dataQualifier':'12','powerOfTenMultiplier':'0','uom':'72','defaultQuality':'0'}

def fixture_xml(case, count=1):
    namespace='http://naesb.org/espi' if case.get('namespace',True) else ''
    def tag(name):
        return '{'+namespace+'}'+name if namespace else name
    root=Element('feed');reading_type=SubElement(root,tag('ReadingType'))
    for key,value in {**FIELDS,**case.get('metadata',{})}.items():
        if value is None:
            continue
        parent=SubElement(reading_type,tag('extension')) if key in case.get('nested',[]) else reading_type
        field_tag='{urn:synthetic-foreign}'+key if key in case.get('foreign',[]) else tag(key)
        SubElement(parent,field_tag).text=value
        if key in case.get('duplicates',[]):
            SubElement(reading_type,tag(key)).text=value
    for _ in range(case.get('meter_count',1)):
        SubElement(root,tag('MeterReading'))
    if case.get('service_kind','0') is not None:
        usage_point=SubElement(root,tag('UsagePoint'))
        service=SubElement(usage_point,tag('ServiceCategory'))
        SubElement(service,tag('kind')).text=case.get('service_kind','0')
    block=SubElement(root,tag('IntervalBlock'))
    for index in range(count):
        reading=SubElement(block,tag('IntervalReading'))
        period=SubElement(reading,tag('timePeriod'))
        SubElement(period,tag('start')).text=str(1783234800+index*3600)
        SubElement(period,tag('duration')).text='3600'
        SubElement(reading,tag('value')).text=case.get('value','250')
        for quality in case.get('quality',[]):
            node=SubElement(reading,tag('ReadingQuality'))
            if case.get('quality_style')=='scalar':
                node.text=str(quality)
            else:
                SubElement(node,tag('quality')).text=str(quality)
    return tostring(root,encoding='unicode')
