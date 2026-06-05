import json
import http.client
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


PORT = int(os.getenv("PORT", "80"))
WORKER_URLS = [
    os.getenv("WORKER_1_URL", "http://torob-proxy.erfanclash20178-calm-moon.svc").rstrip("/"),
    os.getenv("WORKER_2_URL", "http://torob-proxy-2.erfanclash20178-calm-moon.svc").rstrip("/"),
    os.getenv("WORKER_3_URL", "http://torob-proxy-3.erfanclash20178-calm-moon.svc").rstrip("/"),
]
WORKER_PROXY_TOKEN = os.getenv("WORKER_PROXY_TOKEN", "change-this-token")
GATEWAY_PROXY_TOKEN = os.getenv("GATEWAY_PROXY_TOKEN", "change-this-token")
CORS_ALLOW_ORIGIN = os.getenv("CORS_ALLOW_ORIGIN", "*")
HEALTH_QUERY = os.getenv("HEALTH_QUERY", "رب گوجه")
BOT_CHALLENGE_COOLDOWN_SECONDS = int(os.getenv("BOT_CHALLENGE_COOLDOWN_SECONDS", "300"))

state_lock = threading.Lock()
worker_state = {
    worker: {"blocked_until": 0.0, "last_error": "", "last_ok": 0.0}
    for worker in WORKER_URLS
}
next_worker_index = 0


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
        parsed = urllib.parse.urlsplit(self.path)

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

        result, failures = self.fetch_valid_search(parsed.query)
        if result:
            self.write_upstream(result, send_body)
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

    def handle_health(self, send_body: bool) -> None:
        query = urllib.parse.urlencode({"query": HEALTH_QUERY})
        result, failures = self.fetch_valid_search(query)
        if result:
            self.write_json(
                200,
                {
                    "ok": True,
                    "worker": result.worker,
                    "validated_query": HEALTH_QUERY,
                    "result_count": get_result_count(result.body),
                },
                send_body,
            )
            return

        self.write_json(
            503,
            {
                "ok": False,
                "validated_query": HEALTH_QUERY,
                "failures": failures,
            },
            send_body,
        )

    def fetch_valid_search(self, query: str) -> tuple[UpstreamResult | None, list[dict]]:
        failures = []

        for worker in ordered_workers():
            result, failure = fetch_worker(worker, query)
            if result and is_valid_torob_json(result):
                mark_worker_ok(worker)
                return result, failures

            if failure is None and result is not None:
                failure = classify_invalid_response(result)
            failures.append({"worker": worker, **(failure or {"reason": "unknown"})})

            if failure and failure.get("reason") == "bot_challenge":
                mark_worker_blocked(worker, failure["reason"])
            elif failure:
                mark_worker_error(worker, failure.get("reason", "failed"))

        return None, failures

    def write_upstream(self, result: UpstreamResult, send_body: bool) -> None:
        self.send_response(result.status)
        for key, value in result.headers.items():
            if key.lower() not in BLOCKED_RESPONSE_HEADERS:
                self.send_header(key, value)
        self.send_header("X-Torob-Worker", result.worker)
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
            available = list(WORKER_URLS)

        start = next_worker_index % len(available)
        next_worker_index += 1
        return available[start:] + available[:start]


def fetch_worker(worker: str, query: str) -> tuple[UpstreamResult | None, dict | None]:
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
        with urllib.request.urlopen(request, timeout=25) as response:
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

    if result.status == 490 or "آیا شما یک ربات هستید" in text or "arcaptcha" in text or "trb_clearance" in text:
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


def mark_worker_blocked(worker: str, reason: str) -> None:
    with state_lock:
        worker_state[worker]["blocked_until"] = time.time() + BOT_CHALLENGE_COOLDOWN_SECONDS
        worker_state[worker]["last_error"] = reason


if __name__ == "__main__":
    print("starting Torob gateway proxy", flush=True)
    print("workers: " + ", ".join(WORKER_URLS), flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), GatewayHandler).serve_forever()
