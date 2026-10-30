"""Run with python -m scraper.worker; communicates with backend over scoped HTTP."""
import json
import os
from pathlib import Path
import threading
import time
import httpx
from scraper.tavily import discover, ProviderError
from scraper.firehose import discover as firehose_discover, configured as firehose_configured, FirehoseError
from scraper.extraction import (
    configuration,
    extract_training,
    heuristic_extract,
    group_candidates_by_week,
    ExtractionError,
)
from scraper.health import start as start_health
from scraper.week_store import WeekPartitionStore, is_near_duplicate
from shared.contracts import public_web_url, week_key_for_date, week_window


def job_result_limit(job):
    """Bound Search size 1–5. Reject JSON booleans so True/False cannot invent spend size 1/0→1."""
    raw = job.get('max_results', 5)
    if isinstance(raw, bool):
        raise ExtractionError('Job max_results must be an integer from 1 to 5.')
    try:
        return max(1, min(int(raw if raw is not None and raw != '' else 5), 5))
    except (TypeError, ValueError):
        raise ExtractionError('Job max_results must be an integer from 1 to 5.')


def merge_sources(primary, extra, limit=5):
    # Skip non-dict rows (parity with public_sources) so junk Firehose/Tavily entries cannot crash fill.
    merged = [item for item in (primary or []) if isinstance(item, dict)][:limit]
    seen = {item.get('url') for item in merged if item.get('url')}
    for item in extra or []:
        if len(merged) >= limit:
            break
        if not isinstance(item, dict):
            continue
        url = item.get('url')
        if not url or url in seen:
            continue
        merged.append(item)
        seen.add(url)
    return merged


def stamp_retrieved_at(sources, retrieved_at):
    """Copy provider-level retrieval ISO onto sources that omit it."""
    if not retrieved_at:
        return sources
    stamp = str(retrieved_at)[:80]
    for source in sources or []:
        if isinstance(source, dict) and not source.get('retrieved_at'):
            source['retrieved_at'] = stamp
    return sources


def public_sources(sources):
    items = []
    for source in sources or []:
        if not isinstance(source, dict):
            continue
        if len(items) >= 5:
            break
        safe = public_web_url(source.get('url'))
        retrieved = source.get('retrieved_at')
        items.append({
            'url': safe[:2000] if safe else None,
            'title': str(source.get('title') or 'Untitled source')[:300],
            'snippet': str(source.get('snippet') or '')[:2000],
            'extraction_status': str(source.get('extraction_status') or 'failed')[:40],
            'verification_status': str(source.get('verification_status') or 'unverified')[:40],
            'retrieved_at': str(retrieved)[:80] if retrieved else None,
        })
    return items


def api_message(response, fallback):
    """Read SDD `{error.message}` envelopes; keep FastAPI `detail` as a fallback."""
    headers = getattr(response, 'headers', None) or {}
    ctype = headers.get('content-type') if hasattr(headers, 'get') else ''
    if not str(ctype).startswith('application/json'):
        return fallback
    try:
        payload = response.json()
    except (ValueError, TypeError):
        return fallback
    if not isinstance(payload, dict):
        return fallback
    error = payload.get('error')
    if isinstance(error, dict) and error.get('message'):
        return str(error['message'])[:200]
    detail = payload.get('detail')
    if isinstance(detail, str) and detail.strip():
        return detail.strip()[:200]
    return fallback


def _with_judgment(training, judgment):
    """Attach Jev judgment for job-complete fallback without mutating the original payload."""
    if isinstance(training, dict):
        payload = dict(training)
    else:
        payload = dict(training)
    if judgment:
        payload['_judgment'] = judgment
    return payload


def catalogue_pipeline(client, job_id, candidates):
    """Lookup → Jev decide → save new/exists/uncertain via backend connect APIs.

    Returns (saved_count, warnings, unsaved_payloads). Unsaved rows keep `_judgment`
    so job-complete can still hold uncertain / exists refresh evidence.
    """
    warnings = []
    saved = 0
    unsaved = []
    for training in candidates:
        lookup = client.post('/internal/v1/catalogue/lookup', json={'candidate': training})
        if lookup.status_code >= 400:
            warnings.append(api_message(lookup, 'Catalogue lookup failed for one candidate.'))
            unsaved.append(_with_judgment(training, None))
            continue
        data = lookup.json()
        if data.get('exact'):
            judgment = {
                'decision': 'exists',
                'confidence': 1.0,
                'probabilities': {'exists': 1.0, 'new': 0.0, 'uncertain': 0.0},
                'matched_session_id': data['exact']['id'],
            }
        else:
            decide = client.post(
                '/internal/v1/catalogue/decide',
                json={'candidate': training, 'matches': data.get('matches') or []},
            )
            if decide.status_code >= 400:
                warnings.append(api_message(decide, 'Catalogue decide failed.'))
                # Fall back to uncertain hold via save path only if we can craft judgment
                judgment = {
                    'decision': 'uncertain',
                    'confidence': 0.0,
                    'probabilities': {'exists': 0.0, 'new': 0.0, 'uncertain': 1.0},
                    'warning': 'Decide endpoint unavailable; held for review.',
                }
            else:
                judgment = decide.json()
        save = client.post(
            '/internal/v1/catalogue/save',
            json={'candidate': training, 'judgment': judgment, 'job_id': job_id},
        )
        if save.status_code >= 400:
            warnings.append(api_message(save, 'Catalogue save failed.'))
            unsaved.append(_with_judgment(training, judgment))
            continue
        saved += 1
    return saved, warnings, unsaved


def keep_lease(heartbeat, interval=30):
    stop = threading.Event()

    def loop():
        while not stop.wait(interval):
            try:
                heartbeat()
            except Exception:
                break

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    return stop


def run_job(job, heartbeat, client=None, *, review_only=False):
    # Material warnings drive partial/failed. Soft Firehose fill warnings stay on the job but do not
    # alone mark a successful Tavily extract as partial (matches empty-search soft-warn honesty).
    warnings, soft_warnings, candidates, sources = [], [], [], []
    tavily_credits = None
    model_usage = {}
    # Always index the run at the week_key first (job-supplied window or the current KL scrape week).
    scrape_week = job.get('week_key') or week_key_for_date(None)
    try:
        configuration()
    except ExtractionError as exc:
        return {
            'lease_token': job['lease_token'],
            'candidates': [],
            'sources': [],
            'warnings': [str(exc) + ' Tavily Search was not called until the open-weight model is ready.'],
            'status': 'failed',
            'usage': {'tavily_credits': None, 'model_tokens': None, 'catalogue_saved': 0},
            'week_key': scrape_week,
            'candidates_by_week': {},
        }
    try:
        try:
            limit = job_result_limit(job)
        except ExtractionError as exc:
            return {
                'lease_token': job['lease_token'],
                'candidates': [],
                'sources': [],
                'warnings': [str(exc) + ' Tavily Search was not called.'],
                'status': 'failed',
                'usage': {'tavily_credits': None, 'model_tokens': None, 'catalogue_saved': 0},
                'week_key': scrape_week,
                'candidates_by_week': {},
            }
        result = discover(job['query'], limit)
        warnings.extend(result['warnings'])
        sources = stamp_retrieved_at(result['sources'], result.get('retrieved_at'))
        tavily_credits = (result.get('usage') or {}).get('tavily_credits')
        if firehose_configured() and len(sources) < limit:
            try:
                extra = firehose_discover(job['query'], limit - len(sources))
                soft_warnings.extend(extra.get('warnings') or [])
                filled = stamp_retrieved_at(extra.get('sources') or [], extra.get('retrieved_at'))
                sources = merge_sources(sources, filled, limit)
            except FirehoseError as exc:
                soft_warnings.append(str(exc))
        if not sources:
            # Empty Search (+ optional Firehose fill) is succeeded even when Firehose only warned.
            # Soft provider warnings without sources are not a partial extract.
            return {
                'lease_token': job['lease_token'],
                'candidates': [],
                'sources': public_sources(sources),
                'warnings': soft_warnings + warnings,
                'status': 'succeeded',
                'usage': {'tavily_credits': tavily_credits, 'model_tokens': None, 'catalogue_saved': 0},
                'week_key': scrape_week,
                'candidates_by_week': {},
            }
        held = []
        try:
            for source in sources:
                if not isinstance(source, dict):
                    continue
                heartbeat()
                raw = (source.get('raw_content') or '').strip()
                snippet = (source.get('snippet') or '').strip()
                if not raw and not snippet:
                    title = str(source.get('title') or 'Untitled source')[:80]
                    warnings.append('Source had no extractable text (' + title + ').')
                    continue
                snippet_only = (not raw) or str(source.get('extraction_status') or '') == 'failed'
                hold_for_review = snippet_only
                try:
                    if not snippet_only:
                        try:
                            page_candidates = extract_training(source, usage=model_usage)
                            warnings.extend(model_usage.pop('extraction_warnings', []))
                        except ExtractionError as exc:
                            warnings.append(str(exc))
                            page_candidates = heuristic_extract(source)
                            warnings.append('Heuristic candidate held for review.' if page_candidates else 'Heuristic fallback found no supported course; nothing queued for review.')
                            hold_for_review = True
                    else:
                        page_candidates = heuristic_extract(source)
                except ExtractionError as exc:
                    warnings.append(str(exc))
                    continue
                if hold_for_review:
                    held.extend(page_candidates)
                    if page_candidates and snippet_only:
                        warnings.append('Snippet-only source kept for review; not auto-published.')
                else:
                    candidates.extend(page_candidates)
        except ExtractionError as exc:
            warnings.append(str(exc))
        saved = 0
        unsaved = []
        if client is not None and candidates and not review_only:
            try:
                connect = client.get('/internal/v1/catalogue/connect')
                if connect.status_code == 200:
                    saved, save_warnings, unsaved = catalogue_pipeline(client, job['id'], candidates)
                    warnings.extend(save_warnings)
                else:
                    warnings.append(
                        api_message(connect, 'Catalogue connect unavailable; candidates were not saved through the API.')
                    )
                    unsaved = list(candidates)
            except httpx.HTTPError:
                warnings.append('Catalogue connect failed; candidates were not saved through the API.')
                unsaved = list(candidates)
        elif candidates:
            # No connect client: keep extract rows on the job for operator review.
            unsaved = list(candidates)
        # Snippet-only rows stay on the job for operator review. Unsaved full-extract rows keep
        # their Jev `_judgment` so complete can hold uncertain / exists refresh evidence.
        complete_candidates = list(held)
        if unsaved:
            complete_candidates.extend(unsaved)
            if saved:
                warnings.append(
                    str(len(unsaved))
                    + ' of '
                    + str(len(candidates))
                    + ' catalogue saves failed; unsaved kept on job.'
                )
            elif candidates and not review_only:
                warnings.append('Falling back to job-complete candidate insert without Jev decide/save.')
        return {
            'lease_token': job['lease_token'],
            'candidates': complete_candidates,
            'extractions': model_usage.get('extractions', []),
            'sources': public_sources(sources),
            'warnings': soft_warnings + warnings,
            'status': 'partial' if warnings else 'succeeded',
            'usage': {
                'tavily_credits': tavily_credits,
                'model_tokens': model_usage.get('model_tokens'),
                'catalogue_saved': saved,
            },
            # Week-key-first enrichment: the scrape week plus candidates bucketed by event week.
            'week_key': scrape_week,
            'candidates_by_week': group_candidates_by_week(complete_candidates),
        }
    except (ProviderError, ExtractionError) as exc:
        return {
            'lease_token': job['lease_token'], 'candidates': [], 'sources': public_sources(sources),
            'warnings': soft_warnings + [str(exc)], 'status': 'failed',
            'extractions': model_usage.get('extractions', []),
            # Keep any reported Tavily/model usage from the attempt; never invent spend.
            'usage': {
                'tavily_credits': tavily_credits,
                'model_tokens': model_usage.get('model_tokens'),
                'catalogue_saved': 0,
            },
            'week_key': scrape_week,
            'candidates_by_week': {},
        }


def load_scrape_topics(path=None):
    """Read config/scrape_topics.json; only dict rows with a non-empty query are returned."""
    if path is None:
        path = Path(__file__).resolve().parents[1] / 'config' / 'scrape_topics.json'
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [topic for topic in data if isinstance(topic, dict) and str(topic.get('query') or '').strip()]


def fetch_existing_events(client, window_start):
    """Load catalogue fingerprints for week-key-first dedupe (empty list on any failure)."""
    if client is None:
        return []
    try:
        response = client.get('/internal/v1/ingestion/catalogue/existing-events', params={'from_date': window_start})
    except httpx.HTTPError:
        return []
    if getattr(response, 'status_code', 500) != 200:
        return []
    try:
        data = response.json()
    except (ValueError, TypeError):
        return []
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []


def push_week_batch(client, payload):
    """POST a week-partitioned batch to /internal/v1/ingestion/batches/push.

    Returns (response_json_or_None, warning_or_None). Never raises so a transient push failure
    keeps the candidates safe in the week store for the next run.
    """
    try:
        response = client.post('/internal/v1/ingestion/batches/push', json=payload)
    except httpx.HTTPError:
        return None, 'Ingestion batch push failed; candidates kept in the week store.'
    if getattr(response, 'status_code', 500) >= 400:
        return None, api_message(response, 'Ingestion batch push failed.')
    try:
        return response.json(), None
    except (ValueError, TypeError):
        return {}, None


def run_weekly_batch(topics=None, client=None, week_key=None, store=None, operator_id='scraper-worker', heartbeat=None):
    """Week-key-first batch pipeline against the refactored ingestion API.

    Always starts at ``week_key`` first, syncs known catalogue fingerprints from
    ``/internal/v1/ingestion/catalogue/existing-events``, iterates topics (skipping ones already
    completed this week), extracts + validates candidates, filters near-duplicates, and pushes new
    week-partitioned events to ``/internal/v1/ingestion/batches/push`` with ``week_key`` and
    ``source_key`` on every event. Tavily is never called until the open-weight model is ready.
    """
    week_key = week_key or week_key_for_date(None)
    window_start, window_end = week_window(week_key)
    store = store if store is not None else WeekPartitionStore()
    topics = topics if topics is not None else load_scrape_topics()
    result = {
        'week_key': week_key,
        'window_start': window_start,
        'window_end': window_end,
        'weeks': {},
        'candidates_by_week': {},
        'warnings': [],
        'pushed': 0,
        'accepted': 0,
        'rejected': 0,
        'usage': {'tavily_credits': None, 'model_tokens': 0, 'batches_pushed': 0},
        'status': 'succeeded',
    }
    try:
        configuration()
    except ExtractionError as exc:
        result['status'] = 'not_ready'
        result['warnings'].append(str(exc) + ' Tavily Search was not called until the open-weight model is ready.')
        result['weeks'] = {week_key: store.week(week_key)}
        return result

    existing_events = fetch_existing_events(client, window_start)
    model_usage = {}
    new_events = []
    tavily_credits = []
    for topic in topics:
        query = str(topic.get('query') or '').strip()
        if not query or store.topic_seen(week_key, query):
            continue
        try:
            limit = job_result_limit(topic)
        except ExtractionError as exc:
            result['warnings'].append(str(exc))
            continue
        try:
            discovered = discover(query, limit)
        except ProviderError as exc:
            result['warnings'].append(str(exc))
            store.mark_topic_seen(week_key, query, status='failed', topic_id=topic.get('topic_id'))
            continue
        sources = [item for item in (discovered.get('sources') or []) if isinstance(item, dict)]
        credits = (discovered.get('usage') or {}).get('tavily_credits')
        if credits is not None:
            tavily_credits.append(credits)
        if firehose_configured() and len(sources) < limit:
            try:
                extra = firehose_discover(query, limit - len(sources), week_key=week_key)
                sources = merge_sources(sources, extra.get('sources') or [], limit)
            except FirehoseError as exc:
                result['warnings'].append(str(exc))
        topic_urls = []
        for source in sources:
            url = source.get('url')
            if not url or store.url_seen(week_key, url):
                continue
            store.put_source(week_key, source)
            topic_urls.append(url)
            raw = (source.get('raw_content') or '').strip()
            if not raw:
                continue
            try:
                page_candidates = extract_training(source, usage=model_usage)
            except ExtractionError as exc:
                result['warnings'].append(str(exc))
                page_candidates = []
            for candidate in page_candidates:
                duplicate = is_near_duplicate(candidate, existing_events)
                if duplicate:
                    store.record_usage(week_key, rejected=1)
                    continue
                store.put_candidate(week_key, candidate)
                # Guard against re-adding the same identity later in the same run.
                existing_events.append(candidate)
                new_events.append(candidate)
            if heartbeat:
                heartbeat()
        store.mark_topic_seen(week_key, query, status='succeeded', source_urls=topic_urls, topic_id=topic.get('topic_id'))

    model_tokens = model_usage.get('model_tokens')
    result['usage']['tavily_credits'] = sum(tavily_credits) if tavily_credits else None
    result['usage']['model_tokens'] = model_tokens or 0
    store.record_usage(
        week_key,
        tavily_credits=sum(tavily_credits) if tavily_credits else None,
        model_tokens=model_tokens,
    )

    payload = store.export_batch_payload(week_key, operator_id)
    if client is not None and payload['events']:
        data, warning = push_week_batch(client, payload)
        if warning:
            result['warnings'].append(warning)
        if data is not None:
            result['pushed'] += 1
            result['usage']['batches_pushed'] += 1
            accepted = int(data.get('accepted') or 0) if isinstance(data, dict) else 0
            rejected = int(data.get('rejected') or 0) if isinstance(data, dict) else 0
            result['accepted'] += accepted
            result['rejected'] += rejected
            store.record_usage(week_key, batches_pushed=1, accepted=accepted, rejected=rejected)

    result['candidates_by_week'] = group_candidates_by_week(new_events)
    result['weeks'] = {week_key: store.week(week_key)}
    if result['warnings'] and result['status'] == 'succeeded':
        result['status'] = 'partial'
    store.persist()
    return result


def main():
    base = os.getenv('BACKEND_INTERNAL_URL', 'http://127.0.0.1:8000').rstrip('/')
    # Strip so compose/.env padding matches backend security.worker() expected token.
    token = (os.getenv('SCRAPER_SERVICE_TOKEN') or '').strip()
    if not token:
        raise SystemExit('Set SCRAPER_SERVICE_TOKEN before starting the scraper.')
    start_health()
    store = WeekPartitionStore()
    weekly_mode = (os.getenv('SCRAPER_WEEKLY_BATCH') or '').strip().lower() == 'true'
    with httpx.Client(base_url=base, headers={'Authorization': 'Bearer ' + token}, timeout=20) as client:
        while True:
            Path(__import__('tempfile').gettempdir(), 'carecredits-worker').touch()
            if weekly_mode:
                run_weekly_mode(client, store)
                continue
            try:
                response = client.post('/internal/v1/jobs/claim')
                # Auto-negotiate: the refactored main backend removed /internal/v1/jobs/* and exposes
                # /internal/v1/ingestion/* instead. On 404 switch to the week-key-first batch loop.
                if response.status_code == 404:
                    print('Legacy /jobs/claim is gone (404); switching to week-key-first batch mode.', flush=True)
                    weekly_mode = True
                    continue
                response.raise_for_status()
                if response.status_code == 204:
                    reason = (response.headers.get('x-care-claim-reason') or 'empty').strip().lower()
                    if reason == 'not_ready':
                        print('Claim idle (not_ready): paid scrape not ready; waiting.', flush=True)
                    elif reason == 'lost_lease':
                        print('Claim idle (lost_lease): queued job lost the lease race; waiting.', flush=True)
                    else:
                        print('Claim idle (empty): no queued jobs; waiting.', flush=True)
                    time.sleep(3)
                    continue
                job = response.json()
                started = time.monotonic()

                def heartbeat():
                    if time.monotonic() - started > 270:
                        raise ExtractionError('Job deadline reached; retry explicitly if needed.')
                    client.post(
                        '/internal/v1/jobs/' + job['id'] + '/heartbeat',
                        json={'lease_token': job['lease_token']},
                    ).raise_for_status()

                lease = keep_lease(heartbeat)
                try:
                    payload = run_job(job, heartbeat, client)
                finally:
                    lease.set()
                client.post('/internal/v1/jobs/' + job['id'] + '/complete', json=payload).raise_for_status()
                print('Ingestion job ' + job['id'] + ': ' + payload['status'], flush=True)
            except (httpx.HTTPError, ValueError):
                print('Backend request unavailable; job lease will determine recovery.', flush=True)
                time.sleep(5)


def run_weekly_mode(client, store, sleep_seconds=900):
    """One week-key-first batch cycle for the refactored ingestion backend, then idle."""
    week_key = week_key_for_date(None)
    try:
        outcome = run_weekly_batch(client=client, week_key=week_key, store=store)
        print(
            'Weekly batch ' + week_key + ': ' + outcome['status']
            + ' pushed=' + str(outcome['pushed']) + ' accepted=' + str(outcome['accepted']),
            flush=True,
        )
    except (httpx.HTTPError, ValueError) as exc:
        print('Weekly batch unavailable: ' + str(exc)[:120], flush=True)
    time.sleep(sleep_seconds)


if __name__ == '__main__':
    main()
