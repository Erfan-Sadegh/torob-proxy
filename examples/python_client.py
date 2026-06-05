import os

import requests


PROXY_BASE_URL = os.getenv("TOROB_PROXY_BASE_URL", "http://localhost:8080")
PROXY_TOKEN = os.getenv("TOROB_PROXY_TOKEN", "change-this-token")


def search_torob(query: str) -> dict:
    response = requests.get(
        f"{PROXY_BASE_URL}/v4/base-product/search/",
        params={"query": query},
        headers={"X-Proxy-Token": PROXY_TOKEN},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    print(search_torob("گوشی"))
