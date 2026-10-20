"""Notifiers: Slack incoming webhook (SLACK_WEBHOOK_URL) or the console."""
from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger(__name__)


class ConsoleNotifier:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def send(self, title: str, body: str) -> None:
        self.sent.append((title, body))
        print(f"\n{title}\n{body}")


class SlackNotifier:
    def __init__(self, url: str, http: httpx.Client | None = None):
        self.url, self.http = url, http or httpx.Client(timeout=10)

    def send(self, title: str, body: str) -> None:
        try:
            self.http.post(self.url, json={"text": f"*{title}*\n{body}"}).raise_for_status()
        except httpx.HTTPError:
            log.exception("slack notification failed")


def default_notifier():
    url = os.getenv("SLACK_WEBHOOK_URL")
    return SlackNotifier(url) if url else ConsoleNotifier()
