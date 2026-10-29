"""Jev (TypeSafe System One) existence judgments for catalogue dedupe."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from typesafe_sdk import Choice, TypeSafeClient


class JevError(Exception):
    def __init__(self, detail: str, status_code: int = 503):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


def unit_interval(value: Any, default: float = 0.0) -> float:
    """Clamp a probability/confidence into [0, 1]; invalid/NaN/inf → default for NaN, clamp for inf.

    Reject bools: float(True)==1.0 / float(False)==0.0 would invent floor-passing confidence.
    """
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return max(0.0, min(1.0, number))


# Back-compat for callers that imported the private name.
_unit_interval = unit_interval


def confidence_floor() -> float:
    return unit_interval(os.getenv('JEV_CONFIDENCE_FLOOR', '0.7'), 0.7)


def keyfile_path() -> Path:
    return Path.home() / '.typesafe' / 'key'


def api_key() -> str:
    env = (os.getenv('TYPESAFE_API_KEY') or '').strip()
    if env:
        return env
    path = keyfile_path()
    try:
        if path.is_file():
            return path.read_text().strip()
    except OSError:
        return ''
    return ''


def _match_row(item: dict[str, Any]) -> dict[str, Any]:
    data = item.get('data') if isinstance(item.get('data'), dict) else {}
    return {
        'id': item.get('id'),
        'title': item.get('title'),
        'provider': item.get('provider'),
        'start_date': str(item.get('start_date') or ''),
        'city': item.get('city'),
        'mode': item.get('mode'),
        'source_url': data.get('source_url') if data else item.get('source_url'),
    }


def decide_existence(candidate: dict[str, Any], matches: list[dict[str, Any]], client: Any | None = None) -> dict[str, Any]:
    """Return {decision, confidence, probabilities, matched_session_id?, warning?}."""
    if not matches:
        return {
            'decision': 'new',
            'confidence': 1.0,
            'probabilities': {'new': 1.0, 'exists': 0.0, 'uncertain': 0.0},
            'matched_session_id': None,
            'warning': None,
        }

    key = api_key()
    if not key:
        return {
            'decision': 'uncertain',
            'confidence': 0.0,
            'probabilities': {'new': 0.0, 'exists': 0.0, 'uncertain': 1.0},
            'matched_session_id': matches[0].get('id'),
            'warning': 'TYPESAFE_API_KEY is not configured. Near matches stay uncertain for operator review.',
        }

    state = {
        'candidate': {
            'title': candidate.get('title'),
            'provider': candidate.get('provider'),
            'start_date': str(candidate.get('start_date') or ''),
            'city': candidate.get('city'),
            'mode': candidate.get('mode'),
            'source_url': candidate.get('source_url'),
        },
        'matches': [_match_row(item) for item in matches[:5]],
    }
    questions = {
        'existence': Choice(
            instructions=(
                'Decide whether the candidate Malaysia CPD training is the same event as one of the '
                'catalogue matches, a new distinct event, or too uncertain to decide. Prefer exists when '
                'title, provider and date clearly align; prefer new when they clearly differ; choose '
                'uncertain when evidence is weak.'
            ),
            criteria={
                'exists': 'The candidate is the same training session as one of the matches.',
                'new': 'The candidate is a distinct training session not present in the matches.',
                'uncertain': 'There is not enough evidence to decide confidently.',
            },
        )
    }
    if len(state['matches']) > 1:
        match_criteria = {
            str(item['id']): (
                f"Same event as match `{item.get('id')}`: {item.get('title')} by {item.get('provider')} "
                f"on {item.get('start_date')} in {item.get('city')}"
            )
            for item in state['matches']
            if item.get('id')
        }
        match_criteria['none'] = 'None of the listed matches is the same event.'
        questions['matched'] = Choice(
            instructions=(
                'If the candidate is the same training as one catalogue match, choose that match id. '
                'Choose none if it is a new event or too uncertain.'
            ),
            criteria=match_criteria,
        )
    owns_client = client is None
    try:
        client = client or TypeSafeClient(api_key=key)
        response = client.system_one(state=state, questions=questions, model='jev-latest')
        answer = response.choices['existence']
        choice = answer.choice
        probabilities = dict(answer.probabilities or {})
        raw_confidence = answer.confidence if answer.confidence is not None else probabilities.get(choice, 0)
        confidence = _unit_interval(raw_confidence, 0.0)
        if choice not in ('exists', 'new', 'uncertain'):
            raise JevError('TypeSafe returned an invalid existence judgment.', 502)
        floor = confidence_floor()
        decision = choice if confidence >= floor or choice == 'uncertain' else 'uncertain'
        warning = None if decision == choice else 'Jev confidence below floor; treating as uncertain.'
        matched = None
        if decision == 'exists':
            match_ids = {str(item.get('id')) for item in matches if item.get('id')}
            picked = getattr(getattr(response, 'choices', {}).get('matched'), 'choice', None)
            if len(matches) == 1:
                matched = matches[0].get('id')
            elif picked and str(picked) != 'none' and str(picked) in match_ids:
                matched = picked
            else:
                # Multi-match exists without a valid pick must not default to matches[0].
                decision = 'uncertain'
                matched = None
                warning = 'Jev exists without a valid match id; treating as uncertain.'
        return {
            'decision': decision,
            'confidence': confidence,
            'probabilities': {
                'exists': _unit_interval(probabilities.get('exists', 0), 0.0),
                'new': _unit_interval(probabilities.get('new', 0), 0.0),
                'uncertain': _unit_interval(probabilities.get('uncertain', 0), 0.0),
            },
            'matched_session_id': matched,
            'warning': warning,
        }
    except JevError:
        raise
    except Exception as exc:
        status = getattr(exc, 'status_code', None) or getattr(getattr(exc, 'response', None), 'status_code', None)
        if status in (401, 403):
            raise JevError('TypeSafe rejected the server API key.', 503) from exc
        if status == 429:
            raise JevError('TypeSafe rate limit reached. Try again later.', 429) from exc
        if status == 422:
            raise JevError('TypeSafe rejected the existence question.', 502) from exc
        raise JevError('TypeSafe request failed.', 502) from exc
    finally:
        if owns_client and client is not None:
            close = getattr(client, 'close', None)
            if callable(close):
                close()
