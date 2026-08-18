from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from billfit_core import (
    BillFitError,
    compare_rate_plans,
    get_supported_scope,
    list_human_gates,
    parse_usage_file,
    screen_assistance,
    validate_bill,
)


OPERATIONS: dict[str, Callable[..., dict[str, Any]]] = {
    "scope": get_supported_scope,
    "gates": list_human_gates,
    "parse": parse_usage_file,
    "compare": compare_rate_plans,
    "validate": validate_bill,
    "assistance": screen_assistance,
}


def _load_payload(input_json: str | None, input_file: str | None) -> dict[str, Any]:
    if input_json and input_file:
        raise ValueError("Use either --input-json or --input-file, not both.")
    if input_file:
        raw = Path(input_file).read_text(encoding="utf-8")
    else:
        raw = input_json or "{}"
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("The request must be a JSON object.")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the deterministic BillFit calculator.")
    parser.add_argument("operation", choices=sorted(OPERATIONS))
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument("--input-json", help="Request arguments as one JSON object.")
    input_group.add_argument("--input-file", help="Path to a UTF-8 JSON request file.")
    args = parser.parse_args()

    try:
        payload = _load_payload(args.input_json, args.input_file)
        result = OPERATIONS[args.operation](**payload)
        exit_code = 0
    except BillFitError as exc:
        result = {"status": "error", "error": exc.as_dict()}
        exit_code = 2
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        result = {
            "status": "error",
            "error": {"code": "INVALID_REQUEST", "message": str(exc)},
        }
        exit_code = 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
