"""ShopWise AI evaluation runner (Module 4A).

    python -m app.eval.run --list                     # preview scenarios: no network, no AWS
    python -m app.eval.run --live --max-cases 3       # small smoke test against the running backend
    python -m app.eval.run --live                     # full evaluation

Live mode sends the fixed scenarios to the RUNNING backend over HTTP (the same /chat and
/compare/analyze paths the browser uses), so real Nova Lite and Titan V2 are called by the app's own
integration. Ground truth is the PostgreSQL catalog, read through GET /products. Nothing here ever runs
on startup or in pytest: real provider calls need the explicit --live flag.

Bounded: one request at a time, a per-request timeout, NO retries, a pause between cases, and a failed
case is recorded and skipped. Only fixed synthetic prompts are sent; reports store the API responses
(no headers, no credentials). Offline mode = the pytest suite in tests/test_eval_*.py.
"""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from app.eval.checks import Catalog, Outcome, evaluate_chat, evaluate_compare
from app.eval.dataset import SCENARIOS_PATH, load_scenarios
from app.eval.report import summarize, to_markdown, write_reports

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_OUT_DIR = Path(__file__).resolve().parents[2] / "eval_reports"  # backend/eval_reports (git-ignored)
DEFAULT_TIMEOUT_S = 90.0  # the agent's own deadline is 60 s
CATALOG_LIMIT = 100  # GET /products maximum page size


class Transport(Protocol):
    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Outcome: ...


class HttpTransport:
    """Plain urllib, no retries. Only the JSON body is kept; response headers are never stored."""

    def __init__(self, base_url: str, timeout_s: float = DEFAULT_TIMEOUT_S, clock: Callable[[], float] = time.monotonic):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.clock = clock

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Outcome:
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.base_url + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if data else {})  # fmt: skip
        started = self.clock()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                return _parse(resp.status, resp.read(), self.clock() - started)
        except urllib.error.HTTPError as exc:
            return _parse(exc.code, exc.read(), self.clock() - started)
        except (TimeoutError, socket.timeout):
            return Outcome("timeout", error=f"no response within {self.timeout_s:g} s", latency_s=self.clock() - started)
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                return Outcome("timeout", error=f"no response within {self.timeout_s:g} s", latency_s=self.clock() - started)
            return Outcome("network_error", error=type(exc.reason).__name__, latency_s=self.clock() - started)


def _parse(status: int, raw: bytes, latency: float) -> Outcome:
    try:
        body = json.loads(raw) if raw else None
    except ValueError:
        return Outcome("malformed", http_status=status, error="response is not JSON", latency_s=latency)
    return Outcome("ok" if status < 400 else "http_error", http_status=status, body=body, latency_s=latency)


def load_catalog(transport: Transport) -> Catalog:
    """The catalog as stored in PostgreSQL, through the existing GET /products API."""
    outcome = transport.request("GET", f"/products?limit={CATALOG_LIMIT}&offset=0")
    if outcome.status != "ok" or not isinstance(outcome.body, dict):
        raise RuntimeError(f"could not load the catalog from /products: {outcome.status} {outcome.http_status or ''} {outcome.error}")
    items, total = outcome.body.get("items", []), outcome.body.get("total", 0)
    if total > len(items):
        raise RuntimeError(f"catalog has {total} products; the evaluator reads at most {CATALOG_LIMIT}")
    return {int(p["id"]): p for p in items}


def run_scenarios(
    scenarios: list[dict[str, Any]], transport: Transport, catalog: Catalog, *, delay_s: float = 0.0,
    sleep: Callable[[float], None] = time.sleep, progress: Callable[[str], None] = lambda _msg: None,
) -> list[dict[str, Any]]:  # fmt: skip
    by_sku = {p["sku"]: pid for pid, p in catalog.items()}
    cases = []
    for n, scenario in enumerate(scenarios, 1):
        case: dict[str, Any] = {"id": scenario["id"], "category": scenario["category"], "endpoint": scenario["endpoint"], "checks": []}
        try:
            if scenario["endpoint"] == "chat":
                outcome = transport.request("POST", "/chat", {"message": scenario["input"]["message"]})
                checks = evaluate_chat(scenario, outcome, catalog)
                case["request_ok"] = outcome.status == "ok"
            else:
                missing = [s for s in scenario["input"]["skus"] if s not in by_sku]
                if missing:
                    raise LookupError(f"SKUs not in the catalog: {missing}")
                ids = [by_sku[s] for s in scenario["input"]["skus"]] + list(scenario["input"].get("raw_ids", []))
                payload: dict[str, Any] = {"product_ids": ids}
                if "use_case" in scenario["input"]:
                    payload["use_case"] = scenario["input"]["use_case"]
                outcome = transport.request("POST", "/compare/analyze", payload)
                checks = evaluate_compare(scenario, outcome, catalog, ids)
                case["request_ok"] = outcome.http_status == scenario["expect"]["http_status"]
            case["outcome"] = {"status": outcome.status, "http_status": outcome.http_status, "error": outcome.error,
                               "latency_s": None if outcome.latency_s is None else round(outcome.latency_s, 2)}  # fmt: skip
            case["response"] = outcome.body
            case["checks"] = [c.to_dict() for c in checks]
        except Exception as exc:  # noqa: BLE001 - one broken case must not stop the run
            case["error"] = f"{type(exc).__name__}: {exc}"[:300]
            case["request_ok"] = False
        cases.append(case)
        fails = sum(c["status"] == "FAIL" for c in case["checks"])
        progress(f"[{n}/{len(scenarios)}] {scenario['id']}: {case.get('outcome', {}).get('status', 'error')}, {fails} failed checks")
        if delay_s and n < len(scenarios):
            sleep(delay_s)
    return cases


def report_meta(mode: str, base_url: str | None, scenario_version: Any) -> dict[str, Any]:
    from app.config import settings  # model ids only; no credentials are part of Settings

    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5,
                                cwd=Path(__file__).resolve().parent).stdout.strip() or None  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        commit = None
    return {
        "mode": mode,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base_url": base_url,
        "git_commit": commit,
        "scenario_version": scenario_version,
        "models": {"chat": settings.bedrock_model_id, "embedding": settings.embedding_model_id,
                   "source": "evaluator settings (.env / defaults); the server may be configured differently"},  # fmt: skip
    }


def select(scenarios, only: list[str] | None, category: str | None, max_cases: int | None):
    picked = [s for s in scenarios if (not only or s["id"] in only) and (not category or s["category"] == category)]
    return picked[:max_cases] if max_cases else picked


def print_list(scenarios: list[dict[str, Any]]) -> None:
    aws = {"chat": "yes (Nova; Titan if semantic search runs)", "compare": "yes (Nova)"}
    print(f"{len(scenarios)} scenarios from {SCENARIOS_PATH} (preview only: nothing is sent)\n")
    for s in scenarios:
        calls_aws = "no (rejected before AWS)" if s["endpoint"] == "compare" and s["expect"]["http_status"] >= 400 else aws[s["endpoint"]]
        text = s["input"].get("message") or f"compare {s['input']['skus'] + s['input'].get('raw_ids', [])}"
        print(f"- {s['id']:<17} {s['category']:<19} AWS: {calls_aws}")
        print(f"    input: {text[:100]}")
        if s.get("constraints"):
            print(f"    constraints: {s['constraints']}")
        if s.get("tools"):
            print(f"    tools: {s['tools']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.eval.run", description="ShopWise AI quality evaluation.")
    parser.add_argument("--live", action="store_true", help="call the running backend (real Nova Lite / Titan; costs a few cents)")
    parser.add_argument("--list", "--dry-run", dest="list", action="store_true", help="preview scenarios; no network, no AWS")
    parser.add_argument("--max-cases", type=int, help="run only the first N selected scenarios")
    parser.add_argument("--only", action="append", help="scenario id (repeatable)")
    parser.add_argument("--category", help="run one category only")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S, help="seconds per request (no retries)")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between cases")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR, help="report directory")
    args = parser.parse_args(argv)
    if args.max_cases is not None and args.max_cases < 1:
        parser.error("--max-cases must be at least 1")

    data_version = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8")).get("version")
    scenarios = select(load_scenarios(), args.only, args.category, args.max_cases)
    if not scenarios:
        parser.error("no scenarios selected")
    if args.list:
        print_list(scenarios)
        return 0
    if not args.live:
        print("Nothing was run. Use --list to preview scenarios, or --live to call the running backend "
              "(real Nova Lite / Titan V2 calls).", file=sys.stderr)  # fmt: skip
        return 2

    transport = HttpTransport(args.base_url, args.timeout)
    try:
        catalog = load_catalog(transport)
    except RuntimeError as exc:
        print(f"Aborted before any AI call: {exc}. Is the backend running at {args.base_url}?", file=sys.stderr)
        return 1
    print(f"Catalog: {len(catalog)} products from {args.base_url}/products. Running {len(scenarios)} scenarios (live)...")
    cases = run_scenarios(scenarios, transport, catalog, delay_s=args.delay, progress=print)
    report = summarize(cases, report_meta("live", args.base_url, data_version))
    json_path, md_path = write_reports(report, args.out)
    print("\n" + to_markdown(report).split("## Tool selection")[0].strip())
    print(f"\nReports:\n  {json_path}\n  {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
