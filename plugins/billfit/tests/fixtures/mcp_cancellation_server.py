"""Actual SDK/owned-process cancellation fixture; accepts only synthetic files."""
from pathlib import Path
import json
import subprocess
import sys
import threading

SCRIPTS = Path(__file__).resolve().parents[2] / 'skills/billfit/scripts'
sys.path.insert(0, str(SCRIPTS))
import bill_input
import bill_process
import mcp_server


def main():
    root = Path(sys.argv[1]).resolve(strict=True)
    if not root.name.startswith('billfit-cancel-') or not (root / 'fixture-marker').is_file():
        raise SystemExit('Synthetic fixture directory required')
    real_run = bill_process.run_bounded
    counter = 0
    lock = threading.Lock()

    def controlled(command, **kwargs):
        nonlocal counter
        snapshot = Path(command[-1])
        if snapshot.read_bytes() != b'SYNTHETIC_SLOW_BILL':
            return real_run(command, **kwargs)
        with lock:
            counter += 1
            number = counter
        # The owned child waits for an explicit test cleanup marker; the 20s
        # fallback prevents an interrupted test leaving a permanent process.
        script = (
            "import json,os,pathlib,time,sys; root=pathlib.Path(sys.argv[1]); "
            "number=sys.argv[2]; snapshot=sys.argv[3]; "
            "(root/('started-'+number+'.json')).write_text(json.dumps({'pid':os.getpid(),'snapshot':snapshot})); "
            "deadline=time.monotonic()+20\n"
            "while not (root/'release').exists() and time.monotonic()<deadline: time.sleep(.02)\n"
            "print(json.dumps({'spans':[]}))"
        )
        try:
            result = real_run([sys.executable, '-u', '-c', script, str(root), str(number), str(snapshot)],
                              timeout=25, output_limit=20000, kind='PDF')
            (root / f'returned-{number}').write_text('normal return')
            return result
        finally:
            (root / f'settled-{number}').write_text('parser unwound')

    bill_input.run_bounded = controlled
    mcp_server.serve_sdk()


if __name__ == '__main__':
    main()
