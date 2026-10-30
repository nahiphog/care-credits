"""Bounded Tavily discovery. Returned sources are not verified CPD events."""
import json
import os
import re
from urllib.parse import urljoin, urlsplit
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


def matching_detail_link(source, query):
    """One same-site course link, selected by query overlap; never crawl recursively."""
    detail = re.compile(r'/(?:courses?|events?|webinars?|workshops?)/[^/]+', re.I)
    if detail.search(urlsplit(source['url']).path):
        return None
    words = set(re.findall(r'[a-z0-9]{4,}', query.casefold())) - {
        'https', 'http', 'course', 'courses', 'medical', 'malaysia', 'online', 'training', 'www'}
    matches = {}
    content = (source.get('raw_content') or '')[:50000]
    links = re.findall(r'\[([^\]\n]{1,500})\]\(([^\s)]+)\)', content)
    links += [(href, href) for href in re.findall(r'https?://[^\s<>"\])]+', content)]
    for label, href in links:
        try:
            url = source_url(urljoin(source['url'], href))
        except ValueError:
            continue
        if not url or urlsplit(url).hostname != urlsplit(source['url']).hostname or not detail.search(urlsplit(url).path):
            continue
        score = len(words & set(re.findall(r'[a-z0-9]{4,}', (label + ' ' + urlsplit(url).path).casefold())))
        if score >= 2:
            matches[url] = max(matches.get(url, (0, url, label)), (score, url, label))
    if not matches:
        return None
    # Ambiguous equal matches should not silently select a different course.
    matches = sorted(matches.values(), reverse=True)
    if len(matches) > 1 and matches[0][0] == matches[1][0] and matches[0][1] != matches[1][1]:
        return None
    return matches[0][1:]


def discover(query, max_results=5):
    key = os.getenv("TAVILY_API_KEY", "").strip()
    if not key:
        raise ProviderError(503, "Tavily is not configured. Run python scripts/setup_integrations.py locally.")
    direct = source_url(query.strip()) if query.strip().startswith(('https://', 'http://')) else None
    if query.strip().startswith(('https://', 'http://')) and not direct:
        raise ProviderError(422, 'Supply a public course URL without credentials or a private address.')
    search = {'results': [{'url': direct, 'title': 'Course source'}]} if direct else tavily_post("search", {
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
                "urls": list(sources), "extract_depth": "basic", "format": "markdown",
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
    # At most one additional extraction per job, and still one model source in
    # single-source mode. A failed detail fetch preserves the directory evidence.
    for original, source in list(sources.items()):
        target = matching_detail_link(source, query)
        if not target:
            continue
        url, label = target
        try:
            detail = tavily_post('extract', {'urls': [url], 'extract_depth': 'basic', 'format': 'markdown'}, key)
            credits.append(reported_credits(detail))
            page = next((item for item in detail['results'] if isinstance(item, dict)
                         and source_url(item.get('url')) == url and isinstance(item.get('raw_content'), str)
                         and item['raw_content'].strip()), None)
            if page:
                del sources[original]
                sources[url] = {**source, 'url': url, 'title': label, 'snippet': '',
                                'raw_content': page['raw_content'], 'extraction_status': 'success'}
            else:
                warnings.append('Matched course detail could not be fetched; directory evidence retained.')
        except ProviderError as error:
            warnings.append(error.detail + ' Matched course detail unavailable; directory evidence retained.')
        break
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
