#!/usr/bin/env python3
"""Repeatable backend load test runner.

The default scenario is a small, read-only smoke run. Larger scenarios are
opt-in so we do not accidentally hit write-heavy or third-party dependent
routes.

Examples:
    python scripts/loadtest_backend.py --scenario smoke --concurrency 10 --duration 30
    python scripts/loadtest_backend.py --scenario public_catalog --concurrency 25 --duration 60
    python scripts/loadtest_backend.py --scenario authenticated_read --auth-bearer-token <token>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx


@dataclass(frozen=True)
class RequestTarget:
    method: str
    path: str
    params: dict[str, Any] | None = None
    json_body: dict[str, Any] | None = None
    headers: dict[str, str] | None = None
    expected_statuses: tuple[int, ...] = (200,)

    @property
    def name(self) -> str:
        return f"{self.method} {self.path}"


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    targets: list[RequestTarget]
    weights: list[int]

    def pick(self) -> RequestTarget:
        return random.choices(self.targets, weights=self.weights, k=1)[0]


@dataclass
class RouteStats:
    count: int = 0
    ok: int = 0
    errors: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    statuses: Counter[int] = field(default_factory=Counter)


@dataclass
class RunStats:
    total: int = 0
    ok: int = 0
    errors: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    statuses: Counter[int] = field(default_factory=Counter)
    routes: dict[str, RouteStats] = field(default_factory=lambda: defaultdict(RouteStats))
    error_types: Counter[str] = field(default_factory=Counter)

    def record(self, target: RequestTarget, status_code: int | None, elapsed_ms: float | None, error: str | None) -> None:
        route = self.routes[target.name]
        route.count += 1
        self.total += 1
        if elapsed_ms is not None:
            self.latencies_ms.append(elapsed_ms)
            route.latencies_ms.append(elapsed_ms)
        if status_code is not None:
            self.statuses[status_code] += 1
            route.statuses[status_code] += 1
        if error is None and status_code in target.expected_statuses:
            self.ok += 1
            route.ok += 1
        else:
            self.errors += 1
            route.errors += 1
            if error:
                self.error_types[error] += 1


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    rank = (len(ordered) - 1) * (pct / 100.0)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def build_scenarios() -> dict[str, Scenario]:
    smoke = Scenario(
        name="smoke",
        description="Very light, read-only routes that do not depend on the database.",
        targets=[
            RequestTarget("GET", "/"),
            RequestTarget("GET", "/health"),
            RequestTarget("GET", "/api/v1/public/bot-protection"),
        ],
        weights=[2, 4, 1],
    )

    public_catalog = Scenario(
        name="public_catalog",
        description="Public browse traffic that exercises list endpoints and DB reads.",
        targets=[
            RequestTarget("GET", "/public/api/v1/domains"),
            RequestTarget("GET", "/public/api/v1/ventures"),
            RequestTarget("GET", "/public/api/v1/softwares"),
            RequestTarget("GET", "/public/api/v1/communities"),
        ],
        weights=[3, 3, 2, 2],
    )

    marketplace_browse = Scenario(
        name="marketplace_browse",
        description="Marketplace discovery traffic with pagination and search.",
        targets=[
            RequestTarget("GET", "/api/v1/domain/all", params={"page": 1, "page_size": 20}),
            RequestTarget("GET", "/api/v1/auction/active", params={"page": 1, "page_size": 20}),
            RequestTarget("GET", "/api/v1/domain/search", params={"mode": "premium", "q": "tech", "page": 1, "page_size": 10}),
            RequestTarget("GET", "/api/v1/domain/storefront/config"),
            RequestTarget("GET", "/api/v1/auction/domain/00000000-0000-0000-0000-000000000000/list", params={"page": 1, "page_size": 10}, expected_statuses=(200, 404)),
        ],
        weights=[3, 3, 2, 1, 1],
    )

    authenticated_read = Scenario(
        name="authenticated_read",
        description="User dashboard reads that require auth.",
        targets=[
            RequestTarget("GET", "/api/v1/domain/my", params={"page": 1, "page_size": 20}),
            RequestTarget("GET", "/api/v1/venture/my"),
            RequestTarget("GET", "/api/v1/auction/admin/all"),
            RequestTarget("GET", "/api/v1/coventure/my"),
        ],
        weights=[3, 3, 1, 1],
    )

    ai_generate = Scenario(
        name="ai_generate",
        description="Opt-in AI generation traffic. Keep concurrency low and separate.",
        targets=[
            RequestTarget(
                "POST",
                "/api/v1/ai-domains/generate",
                json_body={"idea": "A platform for small businesses to manage leads"},
                expected_statuses=(200, 400, 429, 503),
            ),
        ],
        weights=[1],
    )

    return {
        smoke.name: smoke,
        public_catalog.name: public_catalog,
        marketplace_browse.name: marketplace_browse,
        authenticated_read.name: authenticated_read,
        ai_generate.name: ai_generate,
    }


async def request_once(
    client: httpx.AsyncClient,
    target: RequestTarget,
    default_headers: dict[str, str],
    timeout_seconds: float,
    stats: RunStats,
) -> None:
    started = time.perf_counter()
    try:
        response = await client.request(
            target.method,
            target.path,
            params=target.params,
            json=target.json_body,
            headers={**default_headers, **(target.headers or {})},
            timeout=timeout_seconds,
        )
        await response.aread()
        elapsed_ms = (time.perf_counter() - started) * 1000
        stats.record(target, response.status_code, elapsed_ms, None)
    except httpx.TimeoutException:
        stats.record(target, None, None, "timeout")
    except httpx.HTTPError as exc:
        stats.record(target, None, None, exc.__class__.__name__)
    except Exception as exc:  # pragma: no cover - defensive
        stats.record(target, None, None, exc.__class__.__name__)


async def worker(
    client: httpx.AsyncClient,
    scenario: Scenario,
    stop_event: asyncio.Event,
    default_headers: dict[str, str],
    timeout_seconds: float,
    stats: RunStats,
) -> None:
    while not stop_event.is_set():
        target = scenario.pick()
        await request_once(client, target, default_headers, timeout_seconds, stats)


async def run_scenario(
    scenario: Scenario,
    *,
    base_url: str | None,
    in_process: bool,
    concurrency: int,
    duration_seconds: int,
    ramp_seconds: int,
    timeout_seconds: float,
    default_headers: dict[str, str],
) -> RunStats:
    stats = RunStats()
    stop_event = asyncio.Event()

    transport = None
    app = None
    if in_process:
        from app.main import app as fastapi_app

        app = fastapi_app
        transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        base_url=base_url or "http://127.0.0.1:8000",
        transport=transport,
    ) as client:
        tasks: list[asyncio.Task[None]] = []

        async def start_worker_later(delay: float) -> None:
            if delay > 0:
                await asyncio.sleep(delay)
            if not stop_event.is_set():
                tasks.append(
                    asyncio.create_task(
                        worker(
                            client,
                            scenario,
                            stop_event,
                            default_headers,
                            timeout_seconds,
                            stats,
                        )
                    )
                )

        if concurrency <= 0:
            raise ValueError("concurrency must be greater than zero")

        ramp_interval = (ramp_seconds / concurrency) if ramp_seconds > 0 else 0
        starter_tasks = [
            asyncio.create_task(start_worker_later(i * ramp_interval))
            for i in range(concurrency)
        ]

        try:
            await asyncio.sleep(duration_seconds)
        finally:
            stop_event.set()
            await asyncio.gather(*starter_tasks, return_exceptions=True)
            await asyncio.gather(*tasks, return_exceptions=True)

    return stats


def print_summary(scenario: Scenario, stats: RunStats, duration_seconds: int, concurrency: int) -> None:
    total_latency = stats.latencies_ms
    total_requests = stats.total
    rps = total_requests / max(duration_seconds, 1)
    success_rate = (stats.ok / total_requests * 100) if total_requests else 0.0
    error_rate = (stats.errors / total_requests * 100) if total_requests else 0.0
    p50 = percentile(total_latency, 50)
    p95 = percentile(total_latency, 95)
    p99 = percentile(total_latency, 99)

    print("\n=== Load Test Summary ===")
    print(f"scenario: {scenario.name}")
    print(f"description: {scenario.description}")
    print(f"duration_seconds: {duration_seconds}")
    print(f"concurrency: {concurrency}")
    print(f"requests_total: {total_requests}")
    print(f"requests_per_second: {rps:.2f}")
    print(f"success_rate: {success_rate:.2f}%")
    print(f"error_rate: {error_rate:.2f}%")
    print(f"p50_ms: {p50:.2f}" if p50 is not None else "p50_ms: n/a")
    print(f"p95_ms: {p95:.2f}" if p95 is not None else "p95_ms: n/a")
    print(f"p99_ms: {p99:.2f}" if p99 is not None else "p99_ms: n/a")

    print("\nStatus codes:")
    for status_code, count in sorted(stats.statuses.items()):
        print(f"  {status_code}: {count}")

    if stats.error_types:
        print("\nErrors:")
        for error, count in stats.error_types.most_common():
            print(f"  {error}: {count}")

    print("\nPer-route summary:")
    for route_name, route in sorted(stats.routes.items(), key=lambda item: item[0]):
        route_p95 = percentile(route.latencies_ms, 95)
        print(
            f"  {route_name} | total={route.count} ok={route.ok} errors={route.errors} "
            f"p95_ms={(f'{route_p95:.2f}' if route_p95 is not None else 'n/a')}"
        )


def write_json_report(path: str, scenario: Scenario, stats: RunStats, duration_seconds: int, concurrency: int) -> None:
    report = {
        "scenario": scenario.name,
        "description": scenario.description,
        "duration_seconds": duration_seconds,
        "concurrency": concurrency,
        "requests_total": stats.total,
        "requests_ok": stats.ok,
        "requests_errors": stats.errors,
        "requests_per_second": stats.total / max(duration_seconds, 1),
        "success_rate": (stats.ok / stats.total * 100) if stats.total else 0.0,
        "error_rate": (stats.errors / stats.total * 100) if stats.total else 0.0,
        "latency_ms": {
            "p50": percentile(stats.latencies_ms, 50),
            "p95": percentile(stats.latencies_ms, 95),
            "p99": percentile(stats.latencies_ms, 99),
        },
        "status_codes": dict(stats.statuses),
        "errors": dict(stats.error_types),
        "routes": {
            route_name: {
                "total": route.count,
                "ok": route.ok,
                "errors": route.errors,
                "p95_ms": percentile(route.latencies_ms, 95),
                "status_codes": dict(route.statuses),
            }
            for route_name, route in stats.routes.items()
        },
    }
    Path(path).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


def build_default_headers(args: argparse.Namespace) -> dict[str, str]:
    headers: dict[str, str] = {}
    if args.auth_bearer_token:
        headers["Authorization"] = f"Bearer {args.auth_bearer_token.strip()}"
    if args.cookie:
        headers["Cookie"] = args.cookie.strip()
    if args.guest_session:
        headers["X-Guest-Session"] = args.guest_session.strip()
    if args.user_agent:
        headers["User-Agent"] = args.user_agent.strip()
    return headers


def parse_args() -> argparse.Namespace:
    scenario_names = sorted(build_scenarios().keys())
    parser = argparse.ArgumentParser(description="Backend load test runner")
    parser.add_argument(
        "--scenario",
        action="append",
        default=None,
        choices=scenario_names,
        help="Scenario to run. Can be passed multiple times.",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="HTTP base URL for the API.")
    parser.add_argument("--in-process", action="store_true", help="Run against the FastAPI app in-process.")
    parser.add_argument("--concurrency", type=int, default=5, help="Number of concurrent workers.")
    parser.add_argument("--duration", type=int, default=30, help="Test duration in seconds.")
    parser.add_argument("--ramp-seconds", type=int, default=5, help="Seconds to ramp workers up.")
    parser.add_argument("--timeout", type=float, default=10.0, help="Per-request timeout in seconds.")
    parser.add_argument("--json-out", default="", help="Optional path to write a JSON report.")
    parser.add_argument("--auth-bearer-token", default="", help="Optional bearer token for authenticated routes.")
    parser.add_argument("--cookie", default="", help="Optional Cookie header value.")
    parser.add_argument("--guest-session", default="", help="Optional X-Guest-Session header value.")
    parser.add_argument("--user-agent", default="CoBrother load test runner", help="User-Agent header.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    scenarios = build_scenarios()
    selected_scenarios = args.scenario or ["smoke"]
    default_headers = build_default_headers(args)

    if args.in_process and args.base_url != "http://127.0.0.1:8000":
        print("Note: --in-process ignores --base-url and uses the local FastAPI app.")

    if len(selected_scenarios) == 1 and selected_scenarios[0] == "authenticated_read" and not (
        args.auth_bearer_token or args.cookie
    ):
        print("authenticated_read requires --auth-bearer-token or --cookie")
        return 2

    if len(selected_scenarios) == 1 and selected_scenarios[0] == "ai_generate" and not args.in_process:
        print("ai_generate is opt-in and should be run only in a controlled environment.")

    last_stats: RunStats | None = None
    any_errors = False
    for scenario_name in selected_scenarios:
        scenario = scenarios[scenario_name]
        print(f"\nRunning scenario: {scenario.name}")
        print(f"  {scenario.description}")
        stats = asyncio.run(
            run_scenario(
                scenario,
                base_url=args.base_url,
                in_process=args.in_process,
                concurrency=args.concurrency,
                duration_seconds=args.duration,
                ramp_seconds=args.ramp_seconds,
                timeout_seconds=args.timeout,
                default_headers=default_headers,
            )
        )
        print_summary(scenario, stats, args.duration, args.concurrency)
        last_stats = stats
        any_errors = any_errors or stats.errors > 0
        if args.json_out:
            write_json_report(args.json_out, scenario, stats, args.duration, args.concurrency)

    if last_stats is None:
        return 1
    return 0 if not any_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
