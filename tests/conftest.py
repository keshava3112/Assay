from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from assay.adapters.backends import Corpus, CorpusBackend
from assay.adapters.fetch import CorpusFetcher
from assay.adapters.judges import RuleJudge
from assay.config import parse_spec
from assay.engine import Engine

DEMO = Path(__file__).resolve().parents[1] / "assay" / "examples" / "demo"
AUG = datetime(2026, 8, 18, 9)
OCT = datetime(2026, 10, 19, 9)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(scope="session")
def raw_spec() -> dict:
    return yaml.safe_load((DEMO / "set.yaml").read_text())


@pytest.fixture(scope="session")
def spec(raw_spec):
    return parse_spec(raw_spec)


@pytest.fixture(scope="session")
def leads(raw_spec):
    return tuple(raw_spec["lead_sources"])


def make_engine(snapshot: str, leads, when: datetime, judge=None) -> Engine:
    corpus = Corpus(DEMO / snapshot)
    return Engine([CorpusBackend(corpus)], CorpusFetcher(corpus), judge or RuleJudge(), lead_sources=leads,
                  clock=lambda: when)


@pytest.fixture(scope="session")
def aug_run(spec, leads):
    return run(make_engine("aug", leads, AUG).run(spec))


@pytest.fixture(scope="session")
def oct_run(spec, leads):
    return run(make_engine("oct", leads, OCT).run(spec))
