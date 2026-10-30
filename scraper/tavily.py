"""Bounded Tavily discovery. Returned sources are not verified CPD events."""
import json
import os
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from shared.contracts import canonical_web_url, week_key_for_date



class ProviderError(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def tavily_post(endpoint, payload, key):
    request = Request(
        "https://api.tavily.com/" + endpoint,
        data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            data = json.load(response)
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise ValueError("Invalid provider response")
        return data
    except HTTPError as error:
        # Never expose provider response bodies, request headers, or API keys.
        if error.code in (401, 403):
            raise ProviderError(503, "Tavily rejected the server API key.") from None
        if error.code in (429, 432, 433):
            raise ProviderError(429, "Tavily rate or credit limit reached. Try again later.") from None
        raise ProviderError(502, "Tavily request failed.") from None
    except (TimeoutError, URLError):
        raise ProviderError(504, "Tavily is unavailable or timed out.") from None
    except (ValueError, UnicodeError):
        raise ProviderError(502, "Tavily returned an invalid response.") from None


def reported_credits(payload):
    """Keep provider-reported credit counts; never invent a spend figure."""
    usage = payload.get('usage') if isinstance(payload, dict) else None
    if not isinstance(usage, dict):
        return None
    raw = usage.get('credits')
    # Reject bools: float(True)==1.0 / float(False)==0.0 would invent spend from junk JSON.
    if raw is None or raw == '' or isinstance(raw, bool):
        return None
    try:
        credits = float(raw)
    except (TypeError, ValueError):
        return None
    if credits != credits or credits in (float('inf'), float('-inf')) or credits < 0:
        return None
    return credits


def source_url(value):
    """Reject local/literal IP and non-web links; canonicalize for deduplication.

    Canonicalization strips the fragment AND tracking params (``utm_*``, ``fbclid``, ...) and
    lowercases scheme+host so links differing only by campaign noise collapse to one URL before a
    Tavily ``/extract`` call, saving credits on repeated resources across weekly topics.
    """
    if not isinstance(value, str):
        return None
    return canonical_web_url(value)


def discover(query, max_results=5):
    key = os.getenv("TAVILY_API_KEY", "").strip()
    if not key:
        raise ProviderError(503, "Tavily is not configured. Run python scripts/setup_integrations.py locally.")
    search = tavily_post("search", {
        "query": "Malaysia medical CPD courses conferences webinars " + query,
        "topic": "general", "search_depth": "basic", "max_results": max_results,
        "include_answer": False, "include_raw_content": False,
    }, key)
    credits = [reported_credits(search)]
    sources = {}
    for item in search["results"]:
        if not isinstance(item, dict):
            continue
        url = source_url(item.get("url"))
        if url and url not in sources and len(sources) < max_results:
            sources[url] = {
                "url": url, "title": str(item.get("title") or "Untitled source"),
                "snippet": str(item.get("content") or ""), "raw_content": None,
                "extraction_status": "failed", "verification_status": "unverified",
            }
    warnings = []
    if not sources:
        warnings.append('No source pages matched this search. No model extraction was performed; try a broader query.')
    if sources:
        try:
            extracted = tavily_post("extract", {
                "urls": list(sources), "extract_depth": "basic", "format": "text",
            }, key)
            credits.append(reported_credits(extracted))
            for item in extracted["results"]:
                if not isinstance(item, dict):
                    continue
                url = source_url(item.get("url"))
                content = item.get("raw_content")
                if url in sources and isinstance(content, str) and content.strip():
                    sources[url]["raw_content"] = content
                    sources[url]["extraction_status"] = "success"
            if any(item["extraction_status"] == "failed" for item in sources.values()):
                warnings.append("Some pages could not be extracted; their search snippets are retained.")
        except ProviderError as error:
            warnings.append(error.detail + " Search snippets are retained; extraction is incomplete.")
    known = [value for value in credits if value is not None]
    retrieved_at = datetime.now(timezone.utc).isoformat()
    week_key = week_key_for_date(None)
    # Stamp each source so job-complete can persist scraper ISO (not only complete-time), and the
    # active scrape week_key so the week-key-first store can bucket without re-deriving it.
    for item in sources.values():
        item.setdefault("retrieved_at", retrieved_at)
        item.setdefault("week_key", week_key)
    return {
        "provider": "tavily", "query": query,
        "retrieved_at": retrieved_at,
        "week_key": week_key,
        "sources": list(sources.values()), "warnings": warnings,
        "usage": {"tavily_credits": sum(known) if known else None},
    }
