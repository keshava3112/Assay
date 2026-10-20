"""Text: HTML to readable text, normalisation, passage retrieval, date reasoning.

No external parsers. The extractor is deliberately conservative: it drops chrome
(nav, footer, script, style, forms), keeps headings and paragraphs as separate
lines, and records links for one-hop discovery.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

SKIP = {"script", "style", "noscript", "nav", "footer", "form", "svg", "iframe", "template", "head"}
BLOCK = {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "h5", "h6", "br", "tr", "blockquote", "header", "main", "dd", "dt"}


class _Extractor(HTMLParser):
    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base, self.skip, self.lines, self.cur, self.links, self.title, self._in_title = base, 0, [], [], [], "", False

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self.skip += 1
        if tag == "title":
            self._in_title = True
        if tag in BLOCK:
            self._flush()
        if tag == "a":
            href = dict(attrs).get("href")
            if href and not href.startswith(("mailto:", "tel:", "javascript:", "#")):
                self.links.append(urljoin(self.base, href).split("#")[0])

    def handle_endtag(self, tag):
        if tag in SKIP and self.skip:
            self.skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in BLOCK:
            self._flush()

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip:
            self.cur.append(data)

    def _flush(self):
        line = re.sub(r"\s+", " ", "".join(self.cur)).strip()
        if line:
            self.lines.append(line)
        self.cur = []


def html_to_text(html: str, base_url: str = "") -> tuple[str, str, list[str]]:
    p = _Extractor(base_url)
    p.feed(html)
    p.close()
    p._flush()
    seen, links = set(), []
    for link in p.links:
        if link not in seen:
            seen.add(link)
            links.append(link)
    return re.sub(r"\s+", " ", p.title).strip(), "\n".join(p.lines), links


def norm(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = t.translate({0x2019: "'", 0x2018: "'", 0x201C: '"', 0x201D: '"', 0x2013: "-", 0x2014: "-", 0x00A0: " "})
    return re.sub(r"\s+", " ", t).strip().lower()


def contains_verbatim(haystack: str, needle: str) -> bool:
    n = norm(needle)
    return len(n) >= 12 and n in norm(haystack)


SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(])|\n+")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENT.split(text) if len(s.strip()) > 2]


def context_around(text: str, quote: str, width: int = 160) -> str:
    low, q = text.lower(), quote.lower()[:60]
    i = low.find(q)
    if i < 0:
        return quote
    start, end = max(0, i - width), min(len(text), i + len(quote) + width)
    return ("…" if start else "") + text[start:end].replace("\n", " ") + ("…" if end < len(text) else "")


# ------------------------------------------------------------- passages (BM25)
TOKEN = re.compile(r"[a-z0-9]+")
STOP = set("a an the of to for in on at by with and or is are was were be been it its this that from as has have had "
           "we our you your their they them which who what when where how not no".split())


def tokens(text: str) -> list[str]:
    return [t for t in TOKEN.findall(text.lower()) if t not in STOP]


def top_passages(docs: list[tuple[object, str]], query: str, k: int = 6, window: int = 2) -> list[tuple[object, str]]:
    """BM25 over sentence windows from every page. Keeps the judge's context small and on-topic."""
    units: list[tuple[object, str]] = []
    for ref, text in docs:
        sents = sentences(text)
        for i in range(len(sents)):
            units.append((ref, " ".join(sents[i:i + window])))
    if not units:
        return []
    toks = [tokens(u) for _, u in units]
    df = Counter(t for ts in toks for t in set(ts))
    n, avg = len(units), sum(map(len, toks)) / len(units)
    q = set(tokens(query))
    scored = []
    for (ref, unit), ts in zip(units, toks):
        tf = Counter(ts)
        s = sum(math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * len(ts) / avg))
                for t in q if t in tf)
        if s > 0:
            scored.append((s, ref, unit))
    scored.sort(key=lambda x: -x[0])
    out, seen = [], set()
    for _, ref, unit in scored:
        key = norm(unit)[:80]
        if key not in seen:
            seen.add(key)
            out.append((ref, unit))
        if len(out) >= k:
            break
    return out


# ------------------------------------------------------------------- dates
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DATE = re.compile(r"\b(?:(\d{1,2})\s+)?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s+(?:(\d{1,2}),?\s+)?(20\d\d)\b"
                  r"|\b(20\d\d)-(\d{2})(?:-(\d{2}))?\b|\b(?:in|during|since)\s+(20\d\d)\b", re.I)


def dates_in(text: str) -> list[datetime]:
    out = []
    for m in DATE.finditer(text):
        if m.group(2):
            out.append(datetime(int(m.group(4)), MONTHS[m.group(2).lower()[:3]], 1))
        elif m.group(5):
            out.append(datetime(int(m.group(5)), int(m.group(6)), 1))
        elif m.group(8):
            out.append(datetime(int(m.group(8)), 7, 1))  # a bare year: assume mid-year, the honest middle
    return out


def months_between(a: datetime, b: datetime) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


# ---------------------------------------------------------------- identity
SECOND_LEVEL = {"co.in", "co.uk", "com.au", "co.jp", "com.br", "com.sg", "net.in", "org.in", "ac.in", "gov.in"}


def registrable_domain(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in SECOND_LEVEL:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def same_site(a: str, b: str) -> bool:
    return registrable_domain(a) == registrable_domain(b)
