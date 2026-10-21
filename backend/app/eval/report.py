"""Aggregate evaluation results and write JSON + Markdown reports. Counts only what was measured."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.eval.checks import FAIL, FAMILIES, PASS, UNKNOWN

BLIND_SPOTS = [
    "Text checks are regular-expression heuristics: PASS means no problem was detected, not that the reply is correct.",
    "Invented product names that are not in the catalog cannot be detected reliably; only catalog names are matched.",
    "Reply spec checks only cover lines that name exactly one catalog product; multi-product lines are UNKNOWN.",
    "Recommendation quality (is this the best laptop for the need?) is not scored; no model-as-judge is used.",
    "`products` in /chat holds every row the tools returned, not only the ones the reply recommends.",
    "Each scenario runs once; model output varies between runs, so small differences between reports may be noise.",
    "Models are read from the evaluator's local settings (.env / defaults); the server could be configured differently.",
    "Offline (pytest) results test the evaluator with scripted fakes; they say nothing about real Nova Lite quality.",
]


def case_verdict(case: dict[str, Any]) -> str:
    """ERROR = request failed; FAIL = any check failed; INCOMPLETE = no failure but something UNKNOWN; PASS = all PASS."""
    statuses = [c["status"] for c in case["checks"]]
    if case.get("error") or (case["checks"] and case["checks"][0]["name"] == "response" and statuses[0] == FAIL):
        return "ERROR"
    if FAIL in statuses:
        return "FAIL"
    if UNKNOWN in statuses or not statuses:
        return "INCOMPLETE"
    return "PASS"


def summarize(cases: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    for case in cases:
        case["verdict"] = case_verdict(case)
    families = {f: {PASS: 0, FAIL: 0, UNKNOWN: 0, "total": 0} for f in FAMILIES}
    heuristic = {PASS: 0, FAIL: 0, UNKNOWN: 0, "total": 0}
    for case in cases:
        for c in case["checks"]:
            families[c["family"]][c["status"]] += 1
            families[c["family"]]["total"] += 1
            if c["heuristic"]:
                heuristic[c["status"]] += 1
                heuristic["total"] += 1

    outcomes = Counter(case["outcome"]["status"] for case in cases if case.get("outcome"))
    latencies = [case["outcome"]["latency_s"] for case in cases if case.get("outcome") and case["outcome"].get("latency_s") is not None]
    tool_rows = [
        {"id": case["id"], "tools_used": (case.get("response") or {}).get("tools_used"),
         "preferred_hit": next((c["data"].get("preferred_hit") for c in case["checks"] if c["name"] == "expected_tools"), None)}
        for case in cases if case["endpoint"] == "chat"
    ]  # fmt: skip
    preferred = [r["preferred_hit"] for r in tool_rows if r["preferred_hit"] is not None]
    successful = sum(1 for case in cases if case.get("request_ok"))  # got the HTTP status the scenario expects

    return {
        **meta,
        "scenarios_attempted": len(cases),
        "requests": {
            "successful": successful,
            "errors": len(cases) - successful,
            "by_outcome": dict(outcomes),
            "timeouts": outcomes.get("timeout", 0),
        },
        "latency_s": {"mean": round(sum(latencies) / len(latencies), 2) if latencies else None, "max": max(latencies, default=None)},
        "verdicts": dict(Counter(case["verdict"] for case in cases)),
        "families": families,
        "heuristic_checks": heuristic,
        "honesty_flags": [
            {"id": case["id"], "check": c["name"], "detail": c["detail"]}
            for case in cases for c in case["checks"] if c["family"] == "honesty" and c["status"] == FAIL
        ],  # fmt: skip
        "tool_usage": tool_rows,
        "preferred_tool_rate": {"hits": sum(preferred), "measured": len(preferred)},
        "failed_cases": [
            {"id": case["id"], "verdict": case["verdict"],
             "reasons": [f"{c['family']}.{c['name']}: {c['detail']}" for c in case["checks"] if c["status"] == FAIL] or [case.get("error", "")]}
            for case in cases if case["verdict"] in ("FAIL", "ERROR")
        ],  # fmt: skip
        "blind_spots": BLIND_SPOTS,
        "cases": cases,
    }


def _rate(d: dict[str, int]) -> str:
    return f"{d[PASS]} PASS / {d[FAIL]} FAIL / {d[UNKNOWN]} UNKNOWN (of {d['total']} checks)"


def to_markdown(r: dict[str, Any]) -> str:
    lines = [
        f"# ShopWise AI evaluation report ({r['mode']})",
        "",
        f"- Date: {r['generated_at']}",
        f"- Models (evaluator settings): chat `{r['models']['chat']}`, embeddings `{r['models']['embedding']}`",
        f"- Target: {r.get('base_url') or 'in-process test client'} · git `{r.get('git_commit') or 'unknown'}` · scenarios v{r.get('scenario_version')}",
        f"- Scenarios attempted: {r['scenarios_attempted']} · successful requests: {r['requests']['successful']} · "
        f"errors: {r['requests']['errors']} (timeouts: {r['requests']['timeouts']})",
        f"- Latency: mean {r['latency_s']['mean']} s, max {r['latency_s']['max']} s",
        "",
        "> Heuristic checks flag likely problems; they cannot prove that no hallucination occurred. UNKNOWN is never counted as PASS.",
        "",
        "## Case verdicts",
        "",
        "| Verdict | Cases |",
        "| --- | --- |",
        *[f"| {v} | {n} / {r['scenarios_attempted']} |" for v, n in sorted(r["verdicts"].items())],
        "",
        "PASS = every check passed · INCOMPLETE = no failure, some checks not measurable · FAIL = at least one check failed · ERROR = request failed",
        "",
        "## Checks by family",
        "",
        "| Family | PASS | FAIL | UNKNOWN | Total |",
        "| --- | --- | --- | --- | --- |",
        *[f"| {f} | {d[PASS]} | {d[FAIL]} | {d[UNKNOWN]} | {d['total']} |" for f, d in r["families"].items() if d["total"]],
        "",
        f"Heuristic checks: {_rate(r['heuristic_checks'])}",
        "",
        "## Tool selection",
        "",
        f"Preferred tool used in {r['preferred_tool_rate']['hits']} of {r['preferred_tool_rate']['measured']} scenarios that state a preference "
        "(using an acceptable alternative is not a failure).",
        "",
        "| Case | tools_used | Preferred |",
        "| --- | --- | --- |",
        *[f"| {t['id']} | {', '.join(t['tools_used'] or []) or '—'} | {'—' if t['preferred_hit'] is None else ('yes' if t['preferred_hit'] else 'no')} |" for t in r["tool_usage"]],
        "",
        "## Honesty / hallucination flags",
        "",
        *([f"- **{h['id']}** `{h['check']}`: {h['detail']}" for h in r["honesty_flags"]] or ["- none detected"]),
        "",
        "## Failed cases",
        "",
    ]
    for fc in r["failed_cases"] or []:
        lines.append(f"- **{fc['id']}** ({fc['verdict']})")
        lines += [f"  - {reason}" for reason in fc["reasons"]]
    if not r["failed_cases"]:
        lines.append("- none")
    lines += ["", "## Blind spots", "", *[f"- {b}" for b in r["blind_spots"]], ""]
    return "\n".join(lines)


def write_reports(report: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path, md_path = out_dir / f"eval-{report['mode']}-{stamp}.json", out_dir / f"eval-{report['mode']}-{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(to_markdown(report), encoding="utf-8")
    return json_path, md_path
