from __future__ import annotations

import concurrent.futures
import http.client
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


PORT = int(os.getenv("PORT", "80"))
CONFIGURED_WORKERS = os.getenv("WORKER_URLS", "")
if CONFIGURED_WORKERS:
    raw_worker_urls = CONFIGURED_WORKERS.split(",")
else:
    raw_worker_urls = [
        os.getenv("WORKER_1_URL", "https://torob-proxy.darkube.ir"),
        os.getenv("WORKER_2_URL", "https://torob-proxy-2.darkube.ir"),
        os.getenv("WORKER_3_URL", "https://torob-proxy-3.darkube.ir"),
    ]

WORKER_URLS = []
for worker_url in raw_worker_urls:
    worker_url = worker_url.strip().rstrip("/")
    if worker_url and worker_url not in WORKER_URLS:
        WORKER_URLS.append(worker_url)
WORKER_PROXY_TOKEN = os.getenv("WORKER_PROXY_TOKEN", "change-this-token")
GATEWAY_PROXY_TOKEN = os.getenv("GATEWAY_PROXY_TOKEN", "change-this-token")
CORS_ALLOW_ORIGIN = os.getenv("CORS_ALLOW_ORIGIN", "*")
HEALTH_QUERY = os.getenv("HEALTH_QUERY", "\u0631\u0628 \u06af\u0648\u062c\u0647")
BOT_CHALLENGE_COOLDOWN_SECONDS = int(os.getenv("BOT_CHALLENGE_COOLDOWN_SECONDS", "300"))
WORKER_ERROR_COOLDOWN_SECONDS = int(os.getenv("WORKER_ERROR_COOLDOWN_SECONDS", "60"))
HEALTH_CACHE_SECONDS = int(os.getenv("HEALTH_CACHE_SECONDS", "60"))
WORKER_TIMEOUT_SECONDS = int(os.getenv("WORKER_TIMEOUT_SECONDS", "8"))
HEALTH_FAILURE_STATUS = int(os.getenv("HEALTH_FAILURE_STATUS", "200"))
MIN_WORKER_INTERVAL_SECONDS = float(os.getenv("MIN_WORKER_INTERVAL_SECONDS", "1.2"))
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "86400"))
CACHE_MAX_ITEMS = int(os.getenv("CACHE_MAX_ITEMS", "1000"))

state_lock = threading.Lock()
worker_state = {
    worker: {"blocked_until": 0.0, "last_error": "", "last_ok": 0.0, "next_request_at": 0.0}
    for worker in WORKER_URLS
}
next_worker_index = 0
health_cache = {
    "expires_at": 0.0,
    "status": 503,
    "payload": {"ok": False, "reason": "not_checked_yet"},
}
search_cache: dict[str, tuple[float, UpstreamResult]] = {}


class UpstreamResult:
    def __init__(self, worker: str, status: int, headers: dict[str, str], body: bytes):
        self.worker = worker
        self.status = status
        self.headers = headers
        self.body = body


class GatewayHandler(BaseHTTPRequestHandler):
    server_version = "torob-gateway-proxy/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", CORS_ALLOW_ORIGIN)
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Proxy-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Connection", "close")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_HEAD(self) -> None:
        self.route(send_body=False)

    def do_GET(self) -> None:
        self.route(send_body=True)

    def route(self, send_body: bool) -> None:
        try:
            parsed = urllib.parse.urlsplit(self.path)

            if parsed.path == "/live":
                self.write_json(200, {"ok": True, "service": "torob_gateway"}, send_body)
                return

            if parsed.path == "/health":
                self.handle_health(send_body)
                return

            if parsed.path == "/v4/base-product/search":
                location = "/v4/base-product/search/"
                if parsed.query:
                    location += "?" + parsed.query
                self.send_response(308)
                self.send_header("Location", location)
                self.end_headers()
                return

            if parsed.path != "/v4/base-product/search/":
                self.write_json(404, {"error": "not_found"}, send_body)
                return

            if self.headers.get("X-Proxy-Token") != GATEWAY_PROXY_TOKEN:
                self.write_json(401, {"error": "unauthorized"}, send_body)
                return

            cached_result = get_cached_search(parsed.query)
            if cached_result:
                self.write_upstream(cached_result, send_body, cache_status="HIT")
                return

            result, failures = self.fetch_valid_search(parsed.query)
            if result:
                set_cached_search(parsed.query, result)
                self.write_upstream(result, send_body, cache_status="MISS")
                return

            self.write_json(
                503,
                {
                    "error": "torob_unavailable",
                    "reason": "all_workers_failed_or_challenged",
                    "failures": failures,
                },
                send_body,
            )
        except Exception as exc:
            print(f"gateway request failed: {exc!r}", flush=True)
            self.write_json(500, {"error": "gateway_internal_error", "detail": str(exc)}, send_body)

    def handle_health(self, send_body: bool) -> None:
        cached = get_cached_health()
        if cached:
            status, payload = cached
            self.write_json(status, payload, send_body)
            return

        query = urllib.parse.urlencode({"query": HEALTH_QUERY})
        result, failures = self.fetch_valid_search_concurrent(query)
        if result:
            payload = {
                "ok": True,
                "worker": result.worker,
                "validated_query": HEALTH_QUERY,
                "result_count": get_result_count(result.body),
                "cache_seconds": HEALTH_CACHE_SECONDS,
            }
            set_cached_health(200, payload)
            self.write_json(200, payload, send_body)
            return

        payload = {
            "ok": False,
            "validated_query": HEALTH_QUERY,
            "failures": failures,
            "cache_seconds": HEALTH_CACHE_SECONDS,
        }
        print("health check failed: " + json.dumps(payload, ensure_ascii=False), flush=True)
        set_cached_health(HEALTH_FAILURE_STATUS, payload)
        self.write_json(HEALTH_FAILURE_STATUS, payload, send_body)

    def fetch_valid_search(self, query: str) -> tuple[UpstreamResult | None, list[dict]]:
        failures = []
        workers = ordered_workers()
        if not workers:
            return None, blocked_worker_failures()

        for worker in workers:
            result, failure = fetch_worker(worker, query)
            if result and is_valid_torob_json(result):
                mark_worker_ok(worker)
                return result, failures

            if failure is None and result is not None:
                failure = classify_invalid_response(result)
            failures.append({"worker": worker, **(failure or {"reason": "unknown"})})
            mark_failed_worker(worker, failure)

        return None, failures

    def fetch_valid_search_concurrent(self, query: str) -> tuple[UpstreamResult | None, list[dict]]:
        workers = ordered_workers()
        if not workers:
            return None, blocked_worker_failures()

        failures = []
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=len(workers))
        futures = {executor.submit(fetch_worker, worker, query): worker for worker in workers}

        try:
            for future in concurrent.futures.as_completed(futures, timeout=WORKER_TIMEOUT_SECONDS + 2):
                worker = futures[future]
                result, failure = future.result()
                if result and is_valid_torob_json(result):
                    mark_worker_ok(worker)
                    for pending_future, pending_worker in futures.items():
                        if pending_worker != worker and not pending_future.done():
                            mark_worker_error(pending_worker, "health_probe_incomplete")
                    executor.shutdown(wait=False, cancel_futures=True)
                    return result, failures

                if failure is None and result is not None:
                    failure = classify_invalid_response(result)
                failures.append({"worker": worker, **(failure or {"reason": "unknown"})})
                mark_failed_worker(worker, failure)
        except concurrent.futures.TimeoutError:
            pass
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        for future, worker in futures.items():
            if not future.done():
                failure = {
                    "reason": "request_timeout",
                    "detail": f"timed out after {WORKER_TIMEOUT_SECONDS}s",
                }
                failures.append({"worker": worker, **failure})
                mark_failed_worker(worker, failure)

        return None, failures

    def write_upstream(self, result: UpstreamResult, send_body: bool, cache_status: str = "BYPASS") -> None:
        self.send_response(result.status)
        for key, value in result.headers.items():
            if key.lower() not in BLOCKED_RESPONSE_HEADERS:
                self.send_header(key, value)
        self.send_header("X-Torob-Worker", result.worker)
        self.send_header("X-Proxy-Cache", cache_status)
        self.end_headers()
        if send_body:
            self.wfile.write(result.body)

    def write_json(self, status: int, payload: dict, send_body: bool) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if send_body:
            self.wfile.write(body)


BLOCKED_RESPONSE_HEADERS = {
    "connection",
    "transfer-encoding",
    "content-encoding",
    "content-length",
    "server",
    "date",
}


def ordered_workers() -> list[str]:
    global next_worker_index
    now = time.time()

    with state_lock:
        available = [
            worker for worker in WORKER_URLS
            if worker_state[worker]["blocked_until"] <= now
        ]
        if not available:
            return []

        start = next_worker_index % len(available)
        next_worker_index += 1
        return available[start:] + available[:start]


def blocked_worker_failures() -> list[dict]:
    now = time.time()
    with state_lock:
        return [
            {
                "worker": worker,
                "reason": "worker_in_cooldown",
                "last_error": state["last_error"],
                "cooldown_remaining_seconds": max(0, int(state["blocked_until"] - now)),
            }
            for worker, state in worker_state.items()
        ]


def get_cached_health() -> tuple[int, dict] | None:
    now = time.time()
    with state_lock:
        if health_cache["expires_at"] > now:
            return int(health_cache["status"]), dict(health_cache["payload"])
    return None


def set_cached_health(status: int, payload: dict) -> None:
    with state_lock:
        health_cache["status"] = status
        health_cache["payload"] = payload
        health_cache["expires_at"] = time.time() + HEALTH_CACHE_SECONDS


def normalize_query(query: str) -> str:
    pairs = urllib.parse.parse_qsl(query, keep_blank_values=True)
    return urllib.parse.urlencode(sorted(pairs), doseq=True)


def get_cached_search(query: str) -> UpstreamResult | None:
    if CACHE_TTL_SECONDS <= 0:
        return None

    cache_key = normalize_query(query)
    now = time.time()
    with state_lock:
        cached = search_cache.get(cache_key)
        if not cached:
            return None
        expires_at, result = cached
        if expires_at <= now:
            search_cache.pop(cache_key, None)
            return None
        return result


def set_cached_search(query: str, result: UpstreamResult) -> None:
    if CACHE_TTL_SECONDS <= 0:
        return

    cache_key = normalize_query(query)
    with state_lock:
        if len(search_cache) >= CACHE_MAX_ITEMS:
            oldest_key = next(iter(search_cache))
            search_cache.pop(oldest_key, None)
        search_cache[cache_key] = (time.time() + CACHE_TTL_SECONDS, result)


def wait_worker_turn(worker: str) -> None:
    if MIN_WORKER_INTERVAL_SECONDS <= 0:
        return

    with state_lock:
        now = time.time()
        wait_seconds = max(0.0, worker_state[worker]["next_request_at"] - now)
        worker_state[worker]["next_request_at"] = max(now, worker_state[worker]["next_request_at"]) + MIN_WORKER_INTERVAL_SECONDS

    if wait_seconds:
        time.sleep(wait_seconds)


def fetch_worker(worker: str, query: str) -> tuple[UpstreamResult | None, dict | None]:
    wait_worker_turn(worker)

    url = f"{worker}/v4/base-product/search/"
    if query:
        url += "?" + query

    request = urllib.request.Request(
        url,
        headers={
            "X-Proxy-Token": WORKER_PROXY_TOKEN,
            "Accept": "application/json",
            "User-Agent": "torob-gateway-proxy/1.0",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=WORKER_TIMEOUT_SECONDS) as response:
            body = safe_read(response)
            return UpstreamResult(worker, response.status, dict(response.headers.items()), body), None
    except urllib.error.HTTPError as exc:
        body = safe_read(exc)
        result = UpstreamResult(worker, exc.code, dict(exc.headers.items()), body)
        return result, None
    except Exception as exc:
        return None, {"reason": "request_failed", "detail": str(exc)}


def safe_read(response) -> bytes:
    try:
        return response.read()
    except http.client.IncompleteRead as exc:
        return exc.partial


def is_valid_torob_json(result: UpstreamResult) -> bool:
    if result.status != 200:
        return False
    try:
        payload = json.loads(result.body.decode("utf-8"))
    except Exception:
        return False
    return isinstance(payload, dict) and isinstance(payload.get("results"), list)


def classify_invalid_response(result: UpstreamResult) -> dict:
    text = result.body[:4096].decode("utf-8", errors="ignore").lower()
    content_type = result.headers.get("Content-Type", result.headers.get("content-type", ""))

    if (
        result.status == 490
        or "\u0622\u06cc\u0627 \u0634\u0645\u0627 \u06cc\u06a9 \u0631\u0628\u0627\u062a \u0647\u0633\u062a\u06cc\u062f" in text
        or "arcaptcha" in text
        or "trb_clearance" in text
    ):
        return {
            "reason": "bot_challenge",
            "status": result.status,
            "content_type": content_type,
        }

    return {
        "reason": "invalid_torob_response",
        "status": result.status,
        "content_type": content_type,
    }


def get_result_count(body: bytes) -> int | None:
    try:
        payload = json.loads(body.decode("utf-8"))
        results = payload.get("results")
        return len(results) if isinstance(results, list) else None
    except Exception:
        return None


def mark_worker_ok(worker: str) -> None:
    with state_lock:
        worker_state[worker]["blocked_until"] = 0.0
        worker_state[worker]["last_error"] = ""
        worker_state[worker]["last_ok"] = time.time()


def mark_worker_error(worker: str, reason: str) -> None:
    with state_lock:
        worker_state[worker]["last_error"] = reason
        worker_state[worker]["blocked_until"] = time.time() + WORKER_ERROR_COOLDOWN_SECONDS


def mark_worker_blocked(worker: str, reason: str) -> None:
    with state_lock:
        worker_state[worker]["blocked_until"] = time.time() + BOT_CHALLENGE_COOLDOWN_SECONDS
        worker_state[worker]["last_error"] = reason


def mark_failed_worker(worker: str, failure: dict | None) -> None:
    if failure and failure.get("reason") == "bot_challenge":
        mark_worker_blocked(worker, failure["reason"])
    elif failure:
        mark_worker_error(worker, failure.get("reason", "failed"))


if __name__ == "__main__":
    print("starting Torob gateway proxy", flush=True)
    print("workers: " + ", ".join(WORKER_URLS), flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), GatewayHandler).serve_forever()
