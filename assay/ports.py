"""Ports: the only seams the engine knows about. Adapters live in assay.adapters.

Keeping these as Protocols (not base classes) means any object with the right shape
plugs in, including test doubles, and the engine never imports a vendor SDK.
"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from .domain import Candidate, Criterion, Enrichment, Field, Hit, Page, SetSpec, Verdict


@runtime_checkable
class SearchBackend(Protocol):
    name: str

    async def search(self, query: str, limit: int) -> list[Hit]: ...


@runtime_checkable
class Fetcher(Protocol):
    async def fetch(self, url: str) -> Page | None: ...


@runtime_checkable
class Judge(Protocol):
    name: str

    async def judge(self, spec: SetSpec, candidate: Candidate, criterion: Criterion, passages: list[tuple[Page, str]],
                    now: datetime) -> Verdict: ...

    async def enrich(self, spec: SetSpec, candidate: Candidate, enrichment: Enrichment,
                     passages: list[tuple[Page, str]]) -> Field: ...


class Notifier(Protocol):
    def send(self, title: str, body: str) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...
