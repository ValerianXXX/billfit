from __future__ import annotations

import json
import sys
from typing import Any

from billfit_core import BillFitError, PUBLIC_FUNCTIONS, get_supported_scope


TOOLS: list[dict[str, Any]] = [
    {
        "name": "billfit_get_supported_scope",
        "description": "Return BillFit's supported PG&E customer scope, rate snapshot, exclusions, privacy boundary, and first human steps. Call this before analyzing an uncertain account type.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "billfit_list_human_gates",
        "description": "List actions BillFit intentionally leaves to a person, including account login, data download, tariff confirmation, plan changes, applications, and medical certification.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "billfit_parse_usage_file",
        "description": "Parse a local PG&E Green Button CSV/XML or BillFit interval JSON file and return a privacy-conscious summary and data-quality warnings. It never uploads or returns the full file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "usage_file": {"type": "string", "description": "Absolute or local path to a .csv, .xml, or .json usage file."}
            },
            "required": ["usage_file"],
            "additionalProperties": False,
        },
    },
    {
        "name": "billfit_compare_rate_plans",
        "description": "Deterministically price supported PG&E residential plans from interval usage. Use real usage_file data when available; inline intervals are for demonstrations and tests. Fails closed for solar and CCA.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "usage_file": {"type": "string"},
                "intervals": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "start": {"type": "string", "description": "ISO timestamp, preferably with UTC offset."},
                            "duration_minutes": {"type": "number", "minimum": 0},
                            "kwh": {"type": "number"},
                        },
                        "required": ["start", "kwh"],
                    },
                },
                "current_plan": {"type": "string", "enum": ["E-1", "E-TOU-C", "E-TOU-D", "EV2-A", "E-ELEC"]},
                "candidate_plans": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["E-1", "E-TOU-C", "E-TOU-D", "EV2-A", "E-ELEC"]},
                },
                "baseline_territory": {"type": "string", "enum": ["P", "Q", "R", "S", "T", "V", "W", "X", "Y", "Z"]},
                "service_type": {"type": "string", "enum": ["basic", "all_electric"]},
                "assistance_program": {"type": "string", "enum": ["none", "CARE", "FERA"]},
                "qualifying_technologies": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["electric_vehicle", "battery_storage", "heat_pump_water", "heat_pump_space"],
                    },
                },
                "solar_or_net_export": {"type": "boolean", "default": False},
                "cca_or_direct_access": {"type": "boolean", "default": False},
            },
            "oneOf": [
                {"required": ["usage_file"], "not": {"required": ["intervals"]}},
                {"required": ["intervals"], "not": {"required": ["usage_file"]}},
            ],
            "additionalProperties": False,
        },
    },
    {
        "name": "billfit_validate_bill",
        "description": "Reconstruct comparable energy and Base Services Charge components for the current plan. Do not compare against the whole amount due because taxes, credits, gas, and adjustments are excluded.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "usage_file": {"type": "string"},
                "intervals": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "start": {"type": "string"},
                            "duration_minutes": {"type": "number"},
                            "kwh": {"type": "number"},
                        },
                        "required": ["start", "kwh"],
                    },
                },
                "current_plan": {"type": "string", "enum": ["E-1", "E-TOU-C", "E-TOU-D", "EV2-A", "E-ELEC"]},
                "reported_energy_charge": {"type": "number"},
                "reported_base_services_charge": {"type": "number"},
                "baseline_territory": {"type": "string", "enum": ["P", "Q", "R", "S", "T", "V", "W", "X", "Y", "Z"]},
                "service_type": {"type": "string", "enum": ["basic", "all_electric"]},
                "assistance_program": {"type": "string", "enum": ["none", "CARE", "FERA"]},
                "qualifying_technologies": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["current_plan"],
            "oneOf": [
                {"required": ["usage_file"], "not": {"required": ["intervals"]}},
                {"required": ["intervals"], "not": {"required": ["usage_file"]}},
            ],
            "additionalProperties": False,
        },
    },
    {
        "name": "billfit_screen_assistance",
        "description": "Screen CARE and FERA using the current CPUC household-size and gross-income rules plus categorical programs; separately flag possible Medical Baseline need without collecting medical records.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "household_size": {"type": "integer", "minimum": 1},
                "gross_annual_household_income": {"type": "number", "minimum": 0},
                "enrolled_public_programs": {"type": "array", "items": {"type": "string"}},
                "medical_baseline_need": {"type": ["boolean", "null"]},
            },
            "required": ["household_size"],
            "additionalProperties": False,
        },
    },
]


def _send(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _tool_result(data: dict[str, Any], is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)}],
        "structuredContent": data,
        "isError": is_error,
    }


def _handle(request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    request_id = request.get("id")
    params = request.get("params") or {}
    if request_id is None:
        return None
    if method == "initialize":
        requested_version = params.get("protocolVersion", "2025-06-18")
        supported = {"2024-11-05", "2025-03-26", "2025-06-18"}
        protocol_version = requested_version if requested_version in supported else "2025-06-18"
        result = {
            "protocolVersion": protocol_version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "billfit", "version": "0.2.0"},
            "instructions": "Use BillFit for deterministic PG&E MVP calculations. Never infer missing eligibility facts, request credentials, or perform external enrollment actions.",
        }
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        function = PUBLIC_FUNCTIONS.get(name)
        if function is None:
            error = {"status": "error", "error": {"code": "UNKNOWN_TOOL", "message": f"Unknown tool: {name}"}}
            return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(error, True)}
        try:
            data = function(**arguments)
            result = _tool_result(data)
        except BillFitError as exc:
            result = _tool_result({"status": "error", "error": exc.as_dict()}, True)
        except TypeError as exc:
            result = _tool_result(
                {"status": "error", "error": {"code": "INVALID_ARGUMENTS", "message": str(exc)}},
                True,
            )
        except Exception as exc:  # Fail closed without exposing a traceback over MCP.
            print(f"BillFit internal error: {exc}", file=sys.stderr)
            result = _tool_result(
                {"status": "error", "error": {"code": "INTERNAL_ERROR", "message": "BillFit could not complete the calculation."}},
                True,
            )
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def serve() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("Request must be an object")
            response = _handle(request)
        except (json.JSONDecodeError, ValueError) as exc:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {exc}"},
            }
        if response is not None:
            _send(response)


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        print(json.dumps(get_supported_scope(), ensure_ascii=False, indent=2))
    else:
        serve()
