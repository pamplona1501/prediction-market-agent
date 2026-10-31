"""Small, secret-safe retry helper for read-only provider GET requests."""

from __future__ import annotations

import random
import time

import requests


class SafeReadError(RuntimeError):
    """Provider request error without response body or authentication details."""


def read_only_get(
    session: requests.Session,
    url: str,
    *,
    headers: dict[str, str],
    params: dict[str, object],
    timeout_seconds: float,
    provider_name: str,
    max_attempts: int = 3,
) -> requests.Response:
    """Retry transient transport/5xx failures with capped exponential backoff and jitter."""
    for attempt in range(max_attempts):
        try:
            response = session.get(url, headers=headers, params=params, timeout=timeout_seconds)
        except requests.RequestException:
            if attempt + 1 == max_attempts:
                raise SafeReadError(f"{provider_name} could not be reached. Check connectivity and try again.") from None
            time.sleep(min(2 ** (attempt + 1) + random.uniform(0, 0.5), 8))
            continue

        if response.status_code == 429:
            raise SafeReadError(f"{provider_name} rate limit reached. Wait before refreshing.")
        if 500 <= response.status_code < 600 and attempt + 1 < max_attempts:
            time.sleep(min(2 ** (attempt + 1) + random.uniform(0, 0.5), 8))
            continue
        if not response.ok:
            raise SafeReadError(f"{provider_name} returned HTTP {response.status_code}.")
        return response
    raise SafeReadError(f"{provider_name} request failed. Try again later.")
