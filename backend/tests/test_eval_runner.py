"""Evaluation runner, aggregation and reports (offline mode). No AWS, no network, no PostgreSQL.

The end-to-end tests drive the REAL /chat and /compare/analyze routes in-process with a rule-based fake
model. Their pass rates measure the evaluator and the plumbing, NOT Nova Lite quality.
"""
import io
import json
import re
import socket
import urllib.error

import pytest

from app import crud
from app.eval import run as runner
from app.eval.checks import FAIL, PASS, UNKNOWN, Outcome
from app.eval.dataset import load_scenarios, violations
from app.eval.report import case_verdict, summarize, to_markdown, write_reports
from app.product_filters import ProductFilters
from app.routers import chat as chat_router
from app.routers import compare as compare_router
from app.routers import semantic as semantic_router
from tests.eval_support import TestClientTransport, catalog_dict, catalog_products, chat_ok

SCENARIOS = load_scenarios()
META = {"mode": "offline", "generated_at": "2026-10-21T00:00:00+00:00", "base_url": None, "git_commit": "test",
        "scenario_version": 1, "models": {"chat": "fake-nova", "embedding": "fake-titan", "source": "test"}}  # fmt: skip


# ------------------------------------------------------------------ runner robustness
class ScriptedTransport:
    def __init__(self, outcomes):
        self.outcomes, self.calls = list(outcomes), []

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        nxt = self.outcomes.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def test_runner_records_failures_and_timeouts_and_keeps_going():
    picked = [s for s in SCENARIOS if s["endpoint"] == "chat"][:4]
    transport = ScriptedTransport([
        Outcome("timeout", error="no response within 90 s", latency_s=90.0),
        RuntimeError("connection reset"),
        Outcome("malformed", 200, error="response is not JSON"),
        chat_ok("Here are some. Synthetic demo data.", [], ["search_products"]),
    ])  # fmt: skip
    pauses = []
    cases = runner.run_scenarios(picked, transport, catalog_dict(), delay_s=1.5, sleep=pauses.append)
    assert len(cases) == 4 and len(transport.calls) == 4  # nothing retried, nothing skipped
    assert pauses == [1.5, 1.5, 1.5]
    assert [case_verdict(c) for c in cases[:3]] == ["ERROR"] * 3
    assert cases[0]["outcome"]["status"] == "timeout" and "connection reset" in cases[1]["error"]
    assert case_verdict(cases[3]) != "ERROR"


def test_unknown_sku_in_a_compare_scenario_is_a_case_error_without_a_request():
    scenario = {**next(s for s in SCENARIOS if s["id"] == "compare-01"), "input": {"skus": ["NOPE-1", "MOCK-LEN-001"]}}
    transport = ScriptedTransport([])
    case = runner.run_scenarios([scenario], transport, catalog_dict())[0]
    assert transport.calls == [] and "NOPE-1" in case["error"] and case_verdict(case) == "ERROR"


# ------------------------------------------------------------------ http transport (urllib), mocked
@pytest.mark.parametrize(
    "raised, expected",
    [(socket.timeout("timed out"), "timeout"), (urllib.error.URLError(TimeoutError()), "timeout"),
     (urllib.error.URLError(ConnectionRefusedError()), "network_error")],
)  # fmt: skip
def test_http_transport_maps_timeouts_and_network_errors(monkeypatch, raised, expected):
    def boom(*args, **kwargs):
        raise raised

    monkeypatch.setattr(runner.urllib.request, "urlopen", boom)
    assert runner.HttpTransport("http://backend.test", timeout_s=1).request("POST", "/chat", {"message": "x"}).status == expected


def test_http_transport_parses_error_bodies_and_rejects_non_json(monkeypatch):
    def http_503(*args, **kwargs):
        raise urllib.error.HTTPError("http://backend.test/chat", 503, "x", {}, io.BytesIO(b'{"detail": {"code": "ai_timeout", "message": "m"}}'))

    monkeypatch.setattr(runner.urllib.request, "urlopen", http_503)
    out = runner.HttpTransport("http://backend.test").request("POST", "/chat", {"message": "x"})
    assert (out.status, out.http_status, out.body["detail"]["code"]) == ("http_error", 503, "ai_timeout")
    assert runner._parse(200, b"<html>", 0.1).status == "malformed"


# ------------------------------------------------------------------ aggregation & reports
def _case(cid, statuses, endpoint="chat", request_ok=True):
    checks = [{"family": "grounding", "name": f"c{i}", "status": s, "detail": "", "heuristic": i > 0, "data": {}} for i, s in enumerate(statuses)]
    return {"id": cid, "category": "exact_search", "endpoint": endpoint, "checks": checks, "request_ok": request_ok,
            "outcome": {"status": "ok", "http_status": 200, "error": "", "latency_s": 1.0}, "response": {"tools_used": []}}  # fmt: skip


def test_unknown_is_never_counted_as_pass():
    report = summarize([_case("a", [PASS, UNKNOWN]), _case("b", [PASS, PASS]), _case("c", [UNKNOWN, FAIL])], dict(META))
    assert report["verdicts"] == {"INCOMPLETE": 1, "PASS": 1, "FAIL": 1}
    assert report["families"]["grounding"] == {PASS: 3, FAIL: 1, UNKNOWN: 2, "total": 6}
    assert report["heuristic_checks"] == {PASS: 1, FAIL: 1, UNKNOWN: 1, "total": 3}
    assert [f["id"] for f in report["failed_cases"]] == ["c"]
    md = to_markdown(report)
    assert "| grounding | 3 | 1 | 2 | 6 |" in md and "| INCOMPLETE | 1 / 3 |" in md


def test_reports_are_written_as_json_and_markdown(tmp_path):
    report = summarize([_case("a", [PASS]), _case("b", [FAIL], request_ok=False)], dict(META))
    json_path, md_path = write_reports(report, tmp_path / "reports")
    data = json.loads(json_path.read_text())
    md = md_path.read_text()
    for key in ("generated_at", "models", "scenarios_attempted", "requests", "families", "honesty_flags", "tool_usage",
                "failed_cases", "blind_spots", "cases"):  # fmt: skip
        assert key in data
    assert data["requests"] == {"successful": 1, "errors": 1, "by_outcome": {"ok": 2}, "timeouts": 0}
    for section in ("## Case verdicts", "## Checks by family", "## Tool selection", "## Honesty / hallucination flags", "## Failed cases", "## Blind spots"):
        assert section in md
    assert "UNKNOWN is never counted as PASS" in md and "fake-nova" in md


# ------------------------------------------------------------------ CLI safety
def _no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network access is not allowed here")

    monkeypatch.setattr(runner.urllib.request, "urlopen", forbidden)


def test_list_previews_without_network(monkeypatch, capsys):
    _no_network(monkeypatch)
    assert runner.main(["--list"]) == 0
    out = capsys.readouterr().out
    assert "24 scenarios" in out and "nothing is sent" in out and "exact-01" in out


def test_without_live_flag_nothing_runs(monkeypatch, capsys, tmp_path):
    _no_network(monkeypatch)
    assert runner.main(["--out", str(tmp_path)]) == 2
    assert "Nothing was run" in capsys.readouterr().err and not list(tmp_path.iterdir())


def test_live_aborts_cleanly_when_the_backend_is_unreachable(monkeypatch, capsys, tmp_path):
    def refused(*args, **kwargs):
        raise urllib.error.URLError(ConnectionRefusedError())

    monkeypatch.setattr(runner.urllib.request, "urlopen", refused)
    assert runner.main(["--live", "--max-cases", "2", "--out", str(tmp_path)]) == 1
    assert "Aborted before any AI call" in capsys.readouterr().err and not list(tmp_path.iterdir())


def test_max_cases_and_filters():
    assert [s["id"] for s in runner.select(SCENARIOS, None, None, 3)] == ["exact-01", "exact-02", "exact-03"]
    assert {s["category"] for s in runner.select(SCENARIOS, None, "comparison", None)} == {"comparison"}
    assert [s["id"] for s in runner.select(SCENARIOS, ["nomatch-01"], None, None)] == ["nomatch-01"]


# ------------------------------------------------------------------ offline end to end through the real routes
class RuleBasedNova:
    """Fake Bedrock client: answers /chat with one search_products call, /compare with a valid analysis.

    `misbehave=True` makes it invent stock and a wrong price, so the evaluator must report failures.
    """

    def __init__(self, misbehave=False):
        self.misbehave, self.calls, self.titan_calls = misbehave, 0, 0

    def converse(self, **kwargs):
        self.calls += 1
        messages = kwargs["messages"]
        if "toolChoice" in kwargs["toolConfig"]:  # /compare/analyze
            ids = [p["id"] for p in json.loads(messages[0]["content"][0]["text"].split("<catalog_data>\n")[1].split("\n</catalog_data>")[0])["products"]]
            out = {"summary": "Synthetic demo comparison.", "recommended_product_id": ids[0], "recommendation_reason": "Listed specs.",
                   "tradeoffs": ["Different prices."], "missing_data": ["No CPU benchmarks in the data."]}  # fmt: skip
            return {"stopReason": "tool_use", "output": {"message": {"role": "assistant", "content": [{"toolUse": {"toolUseId": "c", "name": "submit_comparison", "input": out}}]}}}
        last = messages[-1]["content"][0]
        if "text" in last:  # first turn: search with the numbers stated in the question
            text = last["text"]
            args = {}
            if m := re.search(r"\$(\d+)", text):
                args["max_price"] = int(m.group(1))
            if m := re.search(r"(\d+)\s?GB", text):
                args["min_ram_gb"] = int(m.group(1))
            return {"stopReason": "tool_use", "output": {"message": {"role": "assistant", "content": [{"toolUse": {"toolUseId": "t", "name": "search_products", "input": args}}]}}}
        products = json.loads(last["toolResult"]["content"][0]["text"])["products"][:2]
        if not products:
            reply = "There are no laptops matching that in this synthetic catalog."
        elif self.misbehave:
            reply = f"{products[0]['name']} - ${products[0]['price'] - 100:.2f}. It is in stock and ships today."
        else:
            reply = "\n".join(f"{p['name']} - ${p['price']:.2f}, {p['ram_gb']}GB RAM." for p in products) + "\n(Synthetic demo data.)"
        return {"stopReason": "end_turn", "output": {"message": {"role": "assistant", "content": [{"text": reply}]}}}

    def invoke_model(self, **kwargs):
        raise AssertionError("not used by RuleBasedNova")


@pytest.fixture
def offline_app(monkeypatch, client):
    """Real routes; database queries served from the seed CSV; AWS replaced; any real AWS/HTTP use fails the test."""
    rows = catalog_products()
    by_id = {p.id: p for p in rows}

    def matching(filters):
        c = {k: v for k, v in (("max_price", filters.max_price), ("min_price", filters.min_price), ("min_ram_gb", filters.min_ram_gb)) if v is not None}
        return [p for p in rows if not violations({"price": p.price, "ram_gb": p.ram_gb, "brand": p.brand, "os": p.os, "gpu": p.gpu}, c)]

    monkeypatch.setattr(crud, "list_products", lambda db, limit, offset, filters=None: matching(filters or ProductFilters())[offset:offset + limit])
    monkeypatch.setattr(crud, "count_products", lambda db, filters=None: len(matching(filters or ProductFilters())))
    monkeypatch.setattr(crud, "get_products_by_ids", lambda db, ids: [by_id[i] for i in ids if i in by_id])

    def no_boto(*args, **kwargs):
        raise AssertionError("boto3 must not be used in offline mode")

    for module in (chat_router, compare_router, semantic_router):
        monkeypatch.setattr(module, "create_bedrock_client", no_boto)
    monkeypatch.setattr(chat_router.boto3, "client", no_boto)
    _no_network(monkeypatch)

    def use(fake):
        for module in (chat_router, compare_router):
            monkeypatch.setattr(module, "create_bedrock_client", lambda: fake)
        return TestClientTransport(client)

    return use


def test_offline_end_to_end_runs_every_scenario_without_aws(offline_app, tmp_path):
    fake = RuleBasedNova()
    transport = offline_app(fake)
    catalog = runner.load_catalog(transport)  # through the real GET /products route
    assert len(catalog) == 41

    cases = runner.run_scenarios(SCENARIOS, transport, catalog)
    report = summarize(cases, dict(META))
    json_path, md_path = write_reports(report, tmp_path)

    assert report["scenarios_attempted"] == 24 and report["requests"]["successful"] == 24
    by_id = {c["id"]: c for c in cases}
    assert by_id["compare-03"]["outcome"]["http_status"] == 422 and by_id["compare-04"]["outcome"]["http_status"] == 404
    assert by_id["compare-01"]["verdict"] in ("PASS", "INCOMPLETE")
    exact = {c["name"]: c["status"] for c in by_id["exact-01"]["checks"]}
    assert exact["structured_fields_match"] == PASS and exact["reply_specs_match"] == PASS
    assert {c["name"]: c["status"] for c in by_id["nomatch-01"]["checks"]}["no_match_explained"] == PASS
    # The naive fake searches even for the weather question: the evaluator must report that.
    assert {c["name"]: c["status"] for c in by_id["out-of-domain-01"]["checks"]}["expected_tools"] == FAIL
    assert fake.calls > 0 and fake.titan_calls == 0
    assert json_path.exists() and md_path.exists()


def test_offline_misbehaving_model_is_detected(offline_app):
    transport = offline_app(RuleBasedNova(misbehave=True))
    catalog = runner.load_catalog(transport)
    cases = runner.run_scenarios([s for s in SCENARIOS if s["id"] == "exact-01"], transport, catalog)
    report = summarize(cases, dict(META))
    failed = {c["name"] for c in cases[0]["checks"] if c["status"] == FAIL}
    assert {"reply_specs_match", "unsupported_claims", "synthetic_disclaimer"} <= failed
    assert report["verdicts"] == {"FAIL": 1} and report["honesty_flags"]
