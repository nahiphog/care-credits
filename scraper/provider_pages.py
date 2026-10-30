"""Bounded public-page adapter for the known CPD Online provider.

This is not an arbitrary-URL fetcher. No credentials, login cookies, JavaScript,
cross-host redirects or authenticated course content are accessed.
"""
from html.parser import HTMLParser
from urllib.parse import urlsplit, urljoin
import httpx


def supported(url):
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == 'https' and parsed.hostname == 'cpdonline.my'
                and parsed.port in (None, 443) and not parsed.username and not parsed.password
                and not parsed.query and (parsed.path.rstrip('/') == '/doctor-cpd-modules'
                or parsed.path.startswith('/courses/')))
    except ValueError:
        return False


class PublicText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0
        self.link = None

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        if not self.hidden and tag == 'a':
            self.link = dict(attrs).get('href')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)
        if tag == 'a':
            self.link = None

    def handle_data(self, data):
        if not self.hidden and data.strip():
            text = data.strip()
            self.parts.append(f'[{text}]({self.link})' if self.link else text)


def fetch_public_page(url, client=None):
    if not supported(url):
        return None
    own = client is None
    client = client or httpx.Client(timeout=10, follow_redirects=False)
    try:
        for _ in range(3):
            with client.stream('GET', url, follow_redirects=False) as response:
                if response.is_redirect:
                    target = urljoin(url, response.headers.get('location', ''))
                    if not supported(target):
                        return None
                    url = target
                    continue
                if response.status_code != 200 or 'text/html' not in response.headers.get('content-type', ''):
                    return None
                chunks = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 250000:
                        return None
                    chunks.append(chunk)
                parser = PublicText()
                parser.feed(b''.join(chunks).decode('utf-8', errors='replace'))
                return '\n'.join(parser.parts)[:50000] or None
        return None
    except (httpx.HTTPError, ValueError):
        return None
    finally:
        if own:
            client.close()
