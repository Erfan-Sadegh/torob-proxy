import os
from typing import Iterable

import requests


PROXY_URLS = [
    url.strip().rstrip("/")
    for url in os.getenv("TOROB_PROXY_URLS", "http://localhost:8080").split(",")
    if url.strip()
]
PROXY_TOKEN = os.getenv("TOROB_PROXY_TOKEN", "change-this-token")


def search_torob(query: str, proxy_urls: Iterable[str] = PROXY_URLS) -> dict:
    last_error: Exception | None = None

    for base_url in proxy_urls:
        try:
            response = requests.get(
                f"{base_url}/v4/base-product/search/",
                params={"query": query},
                headers={"X-Proxy-Token": PROXY_TOKEN},
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last_error = exc

    raise RuntimeError("All Torob proxy URLs failed") from last_error


if __name__ == "__main__":
    print(search_torob("گوشی"))
