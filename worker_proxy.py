import json
import os
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


PORT = int(os.getenv("PORT", "80"))
UPSTREAM_SCHEME = os.getenv("TOROB_UPSTREAM_SCHEME", "https")
UPSTREAM_HOST = os.getenv("TOROB_UPSTREAM_HOST", "api.torob.com")
PROXY_TOKEN = os.getenv("PROXY_TOKEN", "change-this-token")
CORS_ALLOW_ORIGIN = os.getenv("CORS_ALLOW_ORIGIN", "*")


class WorkerProxyHandler(BaseHTTPRequestHandler):
    server_version = "torob-worker-proxy/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", CORS_ALLOW_ORIGIN)
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Proxy-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_HEAD(self) -> None:
        self.handle_request(send_body=False)

    def do_GET(self) -> None:
        self.handle_request(send_body=True)

    def handle_request(self, send_body: bool) -> None:
        parsed = urllib.parse.urlsplit(self.path)

        if parsed.path == "/health":
            self.write_text(200, "ok\n", send_body)
            return

        if parsed.path == "/v4/base-product/search":
            self.send_response(308)
            location = "/v4/base-product/search/"
            if parsed.query:
                location += "?" + parsed.query
            self.send_header("Location", location)
            self.end_headers()
            return

        if parsed.path != "/v4/base-product/search/":
            self.write_text(404, "not found\n", send_body)
            return

        if self.headers.get("X-Proxy-Token") != PROXY_TOKEN:
            self.write_text(401, "unauthorized\n", send_body)
            return

        upstream_url = urllib.parse.urlunsplit(
            (UPSTREAM_SCHEME, UPSTREAM_HOST, parsed.path, parsed.query, "")
        )
        request = urllib.request.Request(
            upstream_url,
            headers={
                "Host": UPSTREAM_HOST,
                "Accept": self.headers.get("Accept", "application/json"),
                "User-Agent": self.headers.get("User-Agent", "torob-worker-proxy/1.0"),
            },
            method="GET",
        )

        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                body = response.read() if send_body else b""
                self.send_response(response.status)
                self.copy_response_headers(response.headers)
                self.end_headers()
                if send_body:
                    self.wfile.write(body)
        except urllib.error.HTTPError as exc:
            body = exc.read() if send_body else b""
            self.send_response(exc.code)
            self.copy_response_headers(exc.headers)
            self.end_headers()
            if send_body:
                self.wfile.write(body)
        except Exception as exc:
            print(f"upstream request failed: {exc!r}", flush=True)
            payload = json.dumps({"error": "upstream_failed", "detail": str(exc)}, ensure_ascii=False).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if send_body:
                self.wfile.write(payload)

    def copy_response_headers(self, headers) -> None:
        blocked = {
            "connection",
            "transfer-encoding",
            "content-encoding",
            "content-length",
            "server",
            "date",
        }
        for key, value in headers.items():
            if key.lower() not in blocked:
                self.send_header(key, value)

    def write_text(self, status: int, text: str, send_body: bool) -> None:
        body = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if send_body:
            self.wfile.write(body)


if __name__ == "__main__":
    print(f"starting Torob worker proxy on port {PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), WorkerProxyHandler).serve_forever()
