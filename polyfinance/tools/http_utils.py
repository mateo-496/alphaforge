import requests

def get_json(url: str, api_key: str = "", params: dict | None = None) -> dict | list:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["X-API-Key"] = api_key
    response = requests.get(url, headers=headers, params=params, timeout=20)
    response.raise_for_status()
    return response.json()
