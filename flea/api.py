import httpx


ITEMS_QUERY = """
query {
  items {
    id
    name
    shortName
    basePrice
    lastLowPrice
    avg24hPrice
    changeLast48hPercent
    sellFor {
      vendor { name }
      priceRUB
    }
  }
}
"""


class TarkovDevClient:
    def __init__(self, url: str = "https://api.tarkov.dev/graphql", timeout: float = 30.0):
        self.url = url
        self._client = httpx.Client(timeout=timeout)

    def query(self, query: str, variables: dict | None = None) -> dict:
        resp = self._client.post(
            self.url,
            json={"query": query, "variables": variables or {}},
        )
        resp.raise_for_status()
        payload = resp.json()
        if "errors" in payload:
            raise RuntimeError(f"tarkov.dev errors: {payload['errors']}")
        return payload["data"]

    def ping(self) -> str:
        data = self.query("{ status { generalStatus { name } } }")
        return data["status"]["generalStatus"]["name"]

    def fetch_items(self) -> list[dict]:
        data = self.query(ITEMS_QUERY)
        return data["items"]

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "TarkovDevClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
