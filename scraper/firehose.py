"""Firehose management-key adapter. Uses fhm_ keys only inside the scraper."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from scraper.tavily import source_url
from shared.contracts import week_key_for_date


# Cache the resolved tap token per (management-key, week_key) so repeated weekly discover() calls
# do not re-issue GET /v1/taps + GET /v1/rules round-trips before every stream pull.
_TAP_CACHE: dict[tuple[str, str], str] = {}


def _cache_key(key: str, week_key: str) -> tuple[str, str]:
    return (hashlib.sha256((key or '').encode('utf-8')).hexdigest(), week_key)


def reset_tap_cache() -> None:
    """Clear the per-week tap-token cache (used by tests and on key rotation)."""
    _TAP_CACHE.clear()


BASE = "https://api.firehose.com"
TAP_NAME = "CareCredits CPD"
RULES = (
    {
        "value": '(title:CPD OR title:CME OR title:"family medicine") AND (malaysia OR "kuala lumpur") AND recent:24h',
        "tag": "my-cpd",
    },
    {
        "value": '(conference OR webinar OR course) AND malaysia AND (CPD OR CME) AND recent:24h',
        "tag": "my-events",
    },
)


class FirehoseError(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def management_key() -> str:
    return (os.getenv("FIREHOSE_MGMT_KEY") or os.getenv("FIREHOSE_MANAGEMENT_KEY") or "").strip()


def configured() -> bool:
    key = management_key()
    return key.startswith("fhm_") and len(key) > 8


def firehose_request(method, path, token, payload=None, query=None, timeout=20):
    url = BASE + path
    if query:
        url += "?" + urlencode(query)
    headers = {"Authorization": "Bearer " + token}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
            if not body:
                return {}
            if (response.headers.get("Content-Type") or "").startswith("text/event-stream") or path == "/v1/stream":
                return {"sse": body.decode("utf-8", "replace")}
            parsed = json.loads(body)
            if not isinstance(parsed, (dict, list)):
                raise ValueError("Invalid provider response")
            return parsed
    except HTTPError as error:
        if error.code in (401, 403):
            raise FirehoseError(503, "Firehose rejected the server API key.") from None
        if error.code == 422:
            raise FirehoseError(422, "Firehose rejected the request.") from None
        if error.code == 429:
            raise FirehoseError(429, "Firehose rate or credit limit reached. Try again later.") from None
        raise FirehoseError(502, "Firehose request failed.") from None
    except (TimeoutError, URLError):
        raise FirehoseError(504, "Firehose is unavailable or timed out.") from None
    except (ValueError, UnicodeError):
        raise FirehoseError(502, "Firehose returned an invalid response.") from None


def _tap_list(items):
    if isinstance(items, dict):
        items = items.get("taps") or items.get("items") or items.get("data") or []
    return items if isinstance(items, list) else []


def _tap_token(tap: dict) -> str | None:
    token = tap.get("token")
    if not token and isinstance(tap.get("data"), dict):
        token = tap["data"].get("token")
    return str(token) if token else None


def ensure_tap(key: str) -> str:
    listed = firehose_request("GET", "/v1/taps", key)
    taps = [tap for tap in _tap_list(listed) if isinstance(tap, dict) and _tap_token(tap)]
    for tap in taps:
        if (tap.get("name") or "") == TAP_NAME:
            return _tap_token(tap)
    try:
        created = firehose_request("POST", "/v1/taps", key, {"name": TAP_NAME})
        token = _tap_token(created) if isinstance(created, dict) else None
        if token:
            return token
    except FirehoseError as exc:
        if exc.status_code != 422:
            raise
    # Re-list after create miss/422; only the CareCredits CPD tap is acceptable (never taps[0]).
    listed = firehose_request("GET", "/v1/taps", key)
    taps = [tap for tap in _tap_list(listed) if isinstance(tap, dict) and _tap_token(tap)]
    for tap in taps:
        if (tap.get("name") or "") == TAP_NAME:
            return _tap_token(tap)
    raise FirehoseError(502, "Firehose CareCredits CPD tap was not available.")


def ensure_rules(tap_token: str) -> None:
    existing = firehose_request("GET", "/v1/rules", tap_token)
    rows = existing if isinstance(existing, list) else existing.get("rules") or existing.get("items") or existing.get("data") or []
    tags = {str(row.get("tag") or "") for row in rows if isinstance(row, dict)}
    for rule in RULES:
        if rule["tag"] in tags:
            continue
        firehose_request("POST", "/v1/rules", tap_token, rule)


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    event = "message"
    data_lines = []
    for line in text.splitlines() + [""]:
        if line.startswith("event:"):
            event = line[6:].strip() or "message"
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        elif line == "":
            if data_lines:
                raw = "\n".join(data_lines)
                try:
                    payload = json.loads(raw)
                except ValueError:
                    payload = {}
                if isinstance(payload, dict):
                    events.append((event, payload))
            event = "message"
            data_lines = []
    return events


def _document_text(document: dict) -> str:
    markdown = document.get("markdown")
    if isinstance(markdown, str) and markdown.strip():
        return markdown[:12000]
    chunks = ((document.get("diff") or {}).get("chunks") or [])
    parts = []
    for chunk in chunks:
        if isinstance(chunk, dict) and chunk.get("typ") == "ins" and isinstance(chunk.get("text"), str):
            parts.append(chunk["text"])
    return " ".join(parts)[:12000]


def _relevant(query: str, title: str, text: str) -> bool:
    hay = (title + " " + text).lower()
    tokens = [token.lower() for token in query.split() if len(token) >= 4]
    if not tokens:
        return True
    return any(token in hay for token in tokens)


def sources_from_events(events, query, max_results=5):
    sources = []
    seen = set()
    for event, payload in events:
        if event not in ("update", "message") or "document" not in payload:
            continue
        document = payload.get("document") or {}
        url = source_url(document.get("url"))
        if not url or url in seen:
            continue
        title = str(document.get("title") or "Untitled source")[:300]
        text = _document_text(document)
        # Parity with Tavily: whitespace-only pages are extraction failures, not success.
        ok = bool(text.strip())
        snippet = text[:2000] if ok else ""
        if query and not _relevant(query, title, snippet or text[:2000]):
            continue
        seen.add(url)
        sources.append({
            "url": url,
            "title": title,
            "snippet": snippet,
            "raw_content": text if ok else None,
            "extraction_status": "success" if ok else "failed",
            "verification_status": "unverified",
        })
        if len(sources) >= max_results:
            break
    return sources


def collect_matches(tap_token: str, query: str, max_results=5) -> list[dict]:
    body = firehose_request(
        "GET",
        "/v1/stream",
        tap_token,
        query={"timeout": 8, "since": "24h", "limit": max(1, min(max_results, 5))},
        timeout=15,
    )
    events = parse_sse(body.get("sse") or "")
    return sources_from_events(events, query, max_results)


def discover(query: str, max_results=5, week_key: str | None = None) -> dict:
    """Pull recent Firehose matches for the CareCredits CPD tap."""
    key = management_key()
    if not configured():
        raise FirehoseError(503, "Firehose is not configured. Add FIREHOSE_MGMT_KEY from firehose.com/management-keys.")
    week_key = week_key or week_key_for_date(None)
    cache_key = _cache_key(key, week_key)
    token = _TAP_CACHE.get(cache_key)
    if not token:
        token = ensure_tap(key)
        ensure_rules(token)
        _TAP_CACHE[cache_key] = token
    sources = collect_matches(token, query, max_results)
    retrieved_at = datetime.now(timezone.utc).isoformat()
    # Stamp each source so job-complete can persist scraper ISO after Firehose fill, plus the active
    # scrape week_key for the week-key-first store.
    for item in sources:
        item.setdefault("retrieved_at", retrieved_at)
        item.setdefault("week_key", week_key)
    return {
        "provider": "firehose",
        "query": query,
        "retrieved_at": retrieved_at,
        "week_key": week_key,
        "sources": sources,
        "warnings": [],
    }
