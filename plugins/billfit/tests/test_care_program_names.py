"""Frozen source-based labels and negative controls; no customer enrollment."""
import asyncio
from copy import deepcopy
from datetime import date, timedelta
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/billfit/scripts'
sys.path.insert(0, str(SCRIPTS))
import billfit_core as core
import mcp_server
import tariff_review_bundle

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/care-program-names-v1.json').read_text(encoding='utf-8'))


class CareProgramNameTests(unittest.TestCase):
    def setUp(self):
        self.rules = core.assistance_data()
        self.as_of = date.fromisoformat(self.rules['verified_on'])

    def screen(self, programs=None, income=999999, **kwargs):
        return core._screen_assistance_snapshot(self.rules, 2, income, programs,
            as_of=kwargs.pop('as_of', self.as_of), **kwargs)

    def test_official_qualified_labels_keep_the_categorical_path(self):
        for label, canonical in FIXTURE['recognized'].items():
            with self.subTest(label=label):
                result = self.screen([label])
                self.assertEqual(result['care']['status'], 'likely_eligible')
                self.assertEqual(result['care']['basis'], 'categorical_program')
                self.assertEqual(result['care']['matching_programs'], [canonical])
                self.assertEqual(result['fera']['status'], 'not_primary_path')

    def test_existing_canonical_ids_and_aliases_remain_supported(self):
        entries = {name: name for name in self.rules['care_categorical_programs']}
        entries.update(self.rules['program_aliases'])
        for label, canonical in entries.items():
            with self.subTest(label=label):
                self.assertEqual(self.screen([label])['care']['matching_programs'], [canonical])

    def test_case_punctuation_and_fullwidth_text_do_not_require_fuzzy_matching(self):
        for label, canonical in [('  women, INFANTS and children (wic)  ', 'wic'),
                                 ('Medicaid—Medi-Cal (under age 65)', 'medicaid_medi_cal'),
                                 ('ＷＩＣ', 'wic')]:
            with self.subTest(label=label):
                self.assertEqual(self.screen([label])['care']['matching_programs'], [canonical])

    def test_ambiguous_and_unrecognized_names_are_visible_without_invented_eligibility(self):
        for label in FIXTURE['unresolved']:
            with self.subTest(label=label):
                result = self.screen([label])
                self.assertEqual(result['care']['status'], 'likely_not_eligible_by_income')
                review = result['categorical_program_review']
                self.assertEqual(review['status'], 'needs_confirmation')
                self.assertEqual(review['matches'], [])
                self.assertEqual(review['unrecognized'], [{'input_index': 0, 'input': label}])
                self.assertIn('ASSISTANCE_PROGRAM_CONFIRMATION', {gate['id'] for gate in result['human_gates']})
                self.assertNotIn('ASSISTANCE_APPLICATION', {gate['id'] for gate in result['human_gates']})

    def test_matching_names_preserve_supplied_evidence_and_deduplicate_canonical_paths(self):
        labels = ['SNAP', 'UNRECOGNIZED_SYNTHETIC_PROGRAM', 'CalFresh', 'SNAP']
        result = self.screen(labels)
        self.assertEqual(result['care']['matching_programs'], ['calfresh_snap'])
        review = result['categorical_program_review']
        self.assertEqual(review['status'], 'needs_confirmation')
        self.assertEqual([item['input_index'] for item in review['matches']], [0, 2, 3])
        self.assertEqual([item['input'] for item in review['matches']], ['SNAP', 'CalFresh', 'SNAP'])
        self.assertEqual(review['unrecognized'], [{'input_index': 1, 'input': labels[1]}])
        self.assertEqual(labels, ['SNAP', 'UNRECOGNIZED_SYNTHETIC_PROGRAM', 'CalFresh', 'SNAP'])

    def test_no_program_input_and_unknown_names_do_not_erase_income_paths(self):
        for labels in (None, []):
            result = self.screen(labels, income=0)
            self.assertEqual(result['categorical_program_review']['status'], 'not_provided')
            self.assertEqual(result['care']['basis'], 'income')
            self.assertNotIn('ASSISTANCE_PROGRAM_CONFIRMATION', {g['id'] for g in result['human_gates']})
        for income, field in ((0, 'care'), (50000, 'fera')):
            result = self.screen(['Medicare'], income=income)
            self.assertEqual(result[field]['status'], 'likely_eligible')
            self.assertEqual(result[field]['basis'], 'income')
            self.assertEqual(result['categorical_program_review']['status'], 'needs_confirmation')

    def test_invalid_program_container_members_and_bounds_fail_with_redacted_domain_error(self):
        for value in ('SNAP', {'PRIVATE_SENTINEL': True}, [None], [1], [True], [''], ['   '],
                      ['PRIVATE_SENTINEL' * 20], ['SNAP'] * 33):
            with self.subTest(type=type(value).__name__):
                with self.assertRaises(core.BillFitError) as raised:
                    self.screen(value)
                self.assertEqual(raised.exception.code, 'INVALID_PUBLIC_PROGRAMS')
                self.assertNotIn('PRIVATE_SENTINEL', str(raised.exception))

    def test_name_review_does_not_redate_income_rules_or_bypass_stale_and_expired_gates(self):
        result = self.screen(['Women, Infants, and Children (WIC)'],
                             as_of=self.as_of + timedelta(days=46))
        self.assertEqual(result['care']['status'], 'likely_eligible')
        self.assertTrue(result['rules_freshness']['stale'])
        self.assertIn('OFFICIAL_RATE_CONFIRMATION', {g['id'] for g in result['human_gates']})
        review = result['categorical_program_review']
        self.assertEqual(review['mapping_checked_on'], '2026-11-01')
        self.assertEqual(set(review['sources']), set(FIXTURE['sources']))
        self.assertEqual(self.rules['verified_on'], '2026-10-27')
        expired = self.screen(['WIC'], as_of=date.fromisoformat(self.rules['effective_to']) + timedelta(days=1))
        self.assertEqual(expired['status'], 'rules_outside_effective_window')
        self.assertEqual(expired['care']['status'], 'not_screened')

    def test_missing_income_medical_and_fractional_uncertainty_remain_separate(self):
        result = self.screen(['Medi-Cal for Families (Healthy Families A & B)'], income=None,
                             medical_baseline_need=True)
        self.assertEqual(result['care']['basis'], 'categorical_program')
        self.assertEqual(result['medical_baseline']['status'], 'possible_candidate_needs_certification')
        result = self.screen(['Medicare'], income=43280.5)
        self.assertEqual(result['fera']['status'], 'needs_official_confirmation')
        self.assertEqual({g['id'] for g in result['human_gates']},
                         {'ASSISTANCE_PROGRAM_CONFIRMATION', 'INCOME_BOUNDARY_CONFIRMATION'})

    def test_snapshot_and_maintained_data_are_not_mutated_by_name_resolution(self):
        before = deepcopy(self.rules)
        result = self.screen(['WIC'])
        result['categorical_program_review']['sources'].clear()
        result['categorical_program_review']['matches'].clear()
        self.assertEqual(self.rules, before)
        self.assertEqual(core.assistance_data(), before)
        self.assertEqual(len(self.screen(['WIC'])['categorical_program_review']['sources']), 2)

    def test_review_packages_bind_the_program_resolver_and_keep_program_edits_blocked(self):
        self.assertIn('scripts/assistance_programs.py', tariff_review_bundle._runtime_hashes())
        from assistance_review import compare_assistance_candidate
        candidate = deepcopy(self.rules)
        candidate['program_aliases']['medicare'] = 'medicaid_medi_cal'
        with self.assertRaises(ValueError):
            compare_assistance_candidate(candidate)

    def test_public_schema_declares_the_same_bounded_program_input(self):
        tool = next(t for t in mcp_server.TOOLS if t['name'] == 'billfit_screen_assistance')
        schema = tool['inputSchema']['properties']['enrolled_public_programs']
        self.assertEqual(schema['maxItems'], 32)
        self.assertEqual(schema['items']['minLength'], 1)
        self.assertEqual(schema['items']['maxLength'], 160)

    def test_actual_cli_rejects_malformed_programs_without_traceback_then_recovers(self):
        with tempfile.TemporaryDirectory(prefix='billfit-programs-') as raw:
            request = Path(raw) / 'request.json'
            for labels, expected_exit in (([None], 2), (['Women, Infants, and Children (WIC)'], 0)):
                request.write_text(json.dumps({**FIXTURE['synthetic_household'],
                                              'enrolled_public_programs': labels}), encoding='utf-8')
                run = subprocess.run([sys.executable, str(SCRIPTS / 'billfit_cli.py'), 'assistance',
                                      '--input-file', str(request)], capture_output=True, text=True, timeout=15)
                self.assertEqual(run.returncode, expected_exit, run.stderr)
                self.assertEqual(run.stderr, '')
                result = json.loads(run.stdout)
                if expected_exit:
                    self.assertEqual(result['error']['code'], 'INVALID_PUBLIC_PROGRAMS')
                else:
                    self.assertEqual(result['care']['matching_programs'], ['wic'])

    @unittest.skipUnless(importlib.util.find_spec('mcp'), 'Optional MCP SDK unavailable')
    def test_actual_sdk_both_profiles_preserve_review_and_recover_after_invalid_input(self):
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters
        async def scenario(mode):
            params = StdioServerParameters(command=sys.executable, args=[str(SCRIPTS / 'mcp_server.py'), '--sdk'])
            async with Client(params, mode=mode) as client:
                valid = {**FIXTURE['synthetic_household'], 'enrolled_public_programs': ['Healthy Families A & B']}
                result = await client.call_tool('billfit_screen_assistance', valid)
                self.assertFalse(result.is_error)
                self.assertEqual(result.structured_content['care']['matching_programs'], ['medicaid_medi_cal'])
                invalid = await client.call_tool('billfit_screen_assistance', {**valid, 'enrolled_public_programs': [None]})
                self.assertTrue(invalid.is_error)
                self.assertEqual(invalid.structured_content['error']['code'], 'INVALID_ARGUMENTS')
                recovered = await client.call_tool('billfit_screen_assistance', {**valid, 'enrolled_public_programs': ['Medicare']})
                self.assertFalse(recovered.is_error)
                self.assertEqual(recovered.structured_content['categorical_program_review']['status'], 'needs_confirmation')
        for mode in ('2026-07-28', 'legacy'):
            with self.subTest(mode=mode):
                asyncio.run(scenario(mode))


if __name__ == '__main__':
    unittest.main()
