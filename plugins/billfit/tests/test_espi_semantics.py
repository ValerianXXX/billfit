"""Freeze quantity meaning and explicit quality before correcting the parser."""
import asyncio
from datetime import date
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from _espi_semantics import CASES,fixture_xml
SCRIPTS=Path(__file__).resolve().parents[1]/'skills/billfit/scripts'
sys.path.insert(0,str(SCRIPTS))
import billfit_core as core

class FixedDate(date):
    @classmethod
    def today(cls): return cls(2026,11,1)

class ESPISemanticsTests(unittest.TestCase):
    def test_frozen_input_matrix(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'synthetic.xml'
            for case in CASES:
                with self.subTest(case=case['id']):
                    path.write_text(fixture_xml(case),encoding='utf8')
                    original=path.read_bytes()
                    if case['expected']=='reject':
                        with self.assertRaises(core.BillFitError) as caught:
                            core.parse_usage_file(str(path))
                        self.assertEqual(caught.exception.code,case['error'])
                    else:
                        result=core.parse_usage_file(str(path))
                        self.assertEqual(result['summary']['total_kwh'],case.get('expected_kwh',.25))
                        review=[w for w in result['warnings'] if w.startswith('ESPI_')]
                        if case['expected']=='review':
                            self.assertTrue(any(case['marker'] in w for w in review))
                            self.assertIn('USAGE_QUALITY_REVIEW',[g['id'] for g in result['human_gates']])
                        else:
                            self.assertFalse(review)
                    self.assertEqual(path.read_bytes(),original)

    def test_positive_export_and_cumulative_values_cannot_reach_pricing(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'synthetic.xml'
            for metadata in ({'flowDirection':'19'},{'accumulationBehaviour':'3'}):
                path.write_text(fixture_xml({'metadata':metadata}),encoding='utf8')
                for operation,kwargs in ((core.compare_rate_plans,{'candidate_plans':['E-TOU-D']}),
                    (core.validate_bill,{'current_plan':'E-TOU-D','reported_energy_charge':1})):
                    with self.subTest(metadata=metadata,operation=operation.__name__):
                        with self.assertRaises(core.BillFitError) as caught:
                            operation(usage_file=str(path),**kwargs)
                        self.assertEqual(caught.exception.code,'UNSUPPORTED_ESPI_READING_TYPE')

    def test_complete_28_days_do_not_hide_missing_meaning_or_estimated_quality(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'date',FixedDate):
            path=Path(directory)/'synthetic.xml'
            for case in ({'metadata':{'flowDirection':None}},{'metadata':{'defaultQuality':'9'}}):
                path.write_text(fixture_xml(case,count=28*24),encoding='utf8')
                result=core.compare_rate_plans(usage_file=str(path),current_plan='E-TOU-D',candidate_plans=['E-TOU-D'])
                self.assertEqual(result['usage_summary']['quality'],'good')
                self.assertEqual(result['recommendation']['status'],'withheld_pending_usage_quality')
                self.assertNotIn('estimated_annual_savings',result['recommendation'])
                self.assertIn('USAGE_QUALITY_REVIEW',[g['id'] for g in result['human_gates']])

    def test_matching_bill_does_not_erase_declared_quality_review(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'date',FixedDate):
            path=Path(directory)/'synthetic.xml'
            path.write_text(fixture_xml({'metadata':{'defaultQuality':'12'}},count=24),encoding='utf8')
            amount=core.compare_rate_plans(usage_file=str(path),candidate_plans=['E-TOU-D'])['results'][0]['energy_charge_after_discount']
            result=core.validate_bill(usage_file=str(path),current_plan='E-TOU-D',reported_energy_charge=amount,
                billing_period={'start_date':'2026-07-05','end_date_exclusive':'2026-07-06'})
            self.assertEqual(result['arithmetic_status'],'matched')
            self.assertEqual(result['status'],'needs_review')
            self.assertIn('USAGE_ASSUMPTIONS_REQUIRE_REVIEW',result['required_reviews'])

    def test_declared_supported_28_day_input_preserves_existing_calculation(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'date',FixedDate):
            path=Path(directory)/'synthetic.xml';path.write_text(fixture_xml({},count=28*24),encoding='utf8')
            parsed,_,_=core.load_usage(usage_file=str(path))
            inline=[{'start':v.start.isoformat(),'duration_minutes':v.duration_minutes,'kwh':v.kwh} for v in parsed]
            from_file=core.compare_rate_plans(usage_file=str(path),current_plan='E-TOU-D',candidate_plans=['E-TOU-D'])
            reference=core.compare_rate_plans(intervals=inline,current_plan='E-TOU-D',candidate_plans=['E-TOU-D'])
            self.assertEqual(from_file['results'],reference['results'])
            self.assertEqual(from_file['recommendation'],reference['recommendation'])

    @unittest.skipUnless(importlib.util.find_spec('mcp'),'optional SDK unavailable')
    def test_actual_sdk_rejects_export_then_recovers_on_same_connection(self):
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters
        async def scenario(mode):
            with tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'synthetic.xml'
                params=StdioServerParameters(command=sys.executable,args=[str(SCRIPTS/'mcp_server.py'),'--sdk'])
                async with Client(params,mode=mode) as client:
                    path.write_text(fixture_xml({'metadata':{'flowDirection':'19'}}),encoding='utf8')
                    result=await client.call_tool('billfit_parse_usage_file',{'usage_file':str(path)})
                    self.assertTrue(result.is_error)
                    self.assertEqual(result.structured_content['error']['code'],'UNSUPPORTED_ESPI_READING_TYPE')
                    path.write_text(fixture_xml({}),encoding='utf8')
                    result=await client.call_tool('billfit_parse_usage_file',{'usage_file':str(path)})
                    self.assertFalse(result.is_error)
                    self.assertEqual(result.structured_content['summary']['total_kwh'],.25)
        for mode in ['2026-07-28','legacy']:
            with self.subTest(mode=mode):asyncio.run(scenario(mode))

if __name__=='__main__':unittest.main()
