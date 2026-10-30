"""Frozen cancellation and admission contracts; no real bills or model calls."""
from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/billfit/scripts'
sys.path.insert(0, str(SCRIPTS))
from bill_input import extract_bill_fields
from bill_process import run_bounded


def checker(event):
    def check():
        if event.is_set():
            raise asyncio.CancelledError()
    return check


class ParserCancellationTests(unittest.TestCase):
    def test_cancelled_request_never_starts_a_child(self):
        from bill_cancellation import cancellation_scope
        stopped = threading.Event()
        stopped.set()
        with cancellation_scope(checker(stopped)), patch('bill_process.subprocess.Popen') as spawn:
            with self.assertRaises(asyncio.CancelledError):
                run_bounded([sys.executable, '-c', 'print("must not run")'])
        spawn.assert_not_called()

    def test_running_owned_child_is_reaped_and_next_request_is_unaffected(self):
        from bill_cancellation import cancellation_scope
        stopped = threading.Event()
        children = []
        real_spawn = subprocess.Popen
        def spawn(*args, **kwargs):
            process = real_spawn(*args, **kwargs)
            children.append(process)
            stopped.set()
            return process
        started = time.monotonic()
        with cancellation_scope(checker(stopped)), patch('bill_process.subprocess.Popen', side_effect=spawn):
            with self.assertRaises(asyncio.CancelledError):
                run_bounded([sys.executable, '-c', 'import time; time.sleep(20)'])
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())
        self.assertEqual(run_bounded([sys.executable, '-c', 'print("next request")']), b'next request\r\n' if sys.platform=='win32' else b'next request\n')

    def test_cancel_after_extraction_does_not_return_candidates_or_modify_source(self):
        from bill_cancellation import cancellation_scope
        stopped = threading.Event()
        with tempfile.TemporaryDirectory(prefix='billfit-cancel-unit-') as directory:
            source = Path(directory) / 'synthetic.pdf'
            source.write_bytes(b'SYNTHETIC_BILL')
            def spans(_):
                stopped.set()
                return [{'text':'Energy Charges $12.34','page':1,'line':1}]
            with cancellation_scope(checker(stopped)), patch('bill_input._pdf_spans', side_effect=spans):
                with self.assertRaises(asyncio.CancelledError):
                    extract_bill_fields(str(source))
            self.assertEqual(source.read_bytes(), b'SYNTHETIC_BILL')


@unittest.skipUnless(importlib.util.find_spec('mcp') and importlib.util.find_spec('pypdf'), 'optional SDK/PDF profiles unavailable')
class ActualSdkCancellationTests(unittest.TestCase):
    async def until(self, predicate, seconds=4):
        deadline = time.monotonic() + seconds
        while not predicate():
            if time.monotonic() >= deadline:
                self.fail('Synthetic parser did not reach the required checkpoint in time')
            await asyncio.sleep(.02)

    async def scenario(self, mode):
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters
        fixture = Path(__file__).parent / 'fixtures/mcp_cancellation_server.py'
        pdf = Path(__file__).parent / 'fixtures/bill-input-v2/repeated-synthetic-pages.pdf'
        with tempfile.TemporaryDirectory(prefix='billfit-cancel-') as directory:
            root = Path(directory)
            (root / 'fixture-marker').write_text('synthetic only')
            source = root / 'slow.pdf'
            source.write_bytes(b'SYNTHETIC_SLOW_BILL')
            params = StdioServerParameters(command=sys.executable,args=[str(fixture),str(root)])
            async with Client(params, mode=mode) as client:
                pending = []
                try:
                    pending.append(asyncio.create_task(client.call_tool('billfit_extract_bill_fields',{'bill_file':str(source)})))
                    await self.until(lambda:(root/'started-1.json').is_file())
                    scope = await asyncio.wait_for(client.call_tool('billfit_get_supported_scope',{}), 2)
                    self.assertFalse(scope.is_error)
                    pending.append(asyncio.create_task(client.call_tool('billfit_extract_bill_fields',{'bill_file':str(source)})))
                    await self.until(lambda:(root/'started-2.json').is_file())
                    busy = await asyncio.wait_for(client.call_tool('billfit_extract_bill_fields',{'bill_file':str(source)}), 2)
                    self.assertTrue(busy.is_error)
                    self.assertEqual(busy.structured_content['error']['code'],'BILL_PARSER_BUSY')
                    self.assertFalse((root/'started-3.json').exists())
                    records=[json.loads((root/f'started-{i}.json').read_text()) for i in (1,2)]
                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*pending,return_exceptions=True)
                    await self.until(lambda:all((root/f'settled-{i}').exists() for i in (1,2)))
                    await self.until(lambda:all(not Path(item['snapshot']).exists() for item in records))
                    self.assertFalse(any(root.glob('returned-*')))
                    self.assertEqual(source.read_bytes(),b'SYNTHETIC_SLOW_BILL')
                    good=await asyncio.wait_for(client.call_tool('billfit_extract_bill_fields',{'bill_file':str(pdf)}),5)
                    self.assertFalse(good.is_error)
                    self.assertEqual(len(good.structured_content['candidates']),10)
                    self.assertEqual(good.structured_content['status'],'REVIEW_REQUIRED')
                    self.assertFalse(good.structured_content['automatic_confirmation'])
                finally:
                    # Release only children owned by this synthetic fixture if
                    # the baseline blocks cancellation; do not scan process names.
                    (root/'release').write_text('test cleanup')
                    await asyncio.gather(*pending,return_exceptions=True)

    def test_modern_sdk_remains_responsive_bounds_parser_work_and_cleans_cancelled_calls(self):
        asyncio.run(self.scenario('2026-07-28'))

    def test_legacy_sdk_remains_responsive_bounds_parser_work_and_cleans_cancelled_calls(self):
        asyncio.run(self.scenario('legacy'))


if __name__ == '__main__':
    unittest.main()
