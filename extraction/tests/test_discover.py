"""Tests for discover.py and its API (issue #17).

    .venv/bin/python -m pytest

OpenAlex and the model are both faked, so the tests spend no OpenAlex credits
and no Claude Code usage. The fake OpenAlex serves a made-up set of papers;
the fake model scores a paper 3 when its title starts with "Likely", else 0.
"""

from __future__ import annotations

import json
import re
import threading
import time

import pytest
import requests
from fastapi.testclient import TestClient

import api
import discover as d

DOI = "10.1021/ma00103a034"


class Response:
    def __init__(self, status: int, body: dict | None = None, headers: dict | None = None):
        self.status_code, self.body, self.headers = status, body, headers or {}

    def json(self) -> dict:
        return self.body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)


class FakeOpenAlex:
    """Stands in for the requests.Session that Search sends to api.openalex.org."""

    def __init__(self):
        self.params = None
        self.works: dict[str, dict] = {}  # id -> work
        self.found: dict[str, list[str]] = {}  # search text -> ids, best first
        self.citing: dict[str, list[str]] = {}  # id -> ids of the papers citing it
        self.requests: list[tuple[str, dict]] = []  # (path, params) of each request, in order
        self.budget: int | None = None  # requests answered before the daily budget is used up
        self.refuse = lambda path, params: False  # or which requests find the daily budget used up
        self.delay = 0.0  # seconds each request takes
        self.lock = threading.Lock()
        self.n = 0

    def add(self, title: str, refs=(), citing=(), cited_by: int | None = None, doi: str | None = None) -> str:
        self.n += 1
        wid = f"https://openalex.org/W{self.n}"
        self.works[wid] = {
            "id": wid,
            "doi": f"https://doi.org/{doi}" if doi else None,
            "title": title,
            "publication_year": 2020,
            "type": "article",
            "referenced_works": list(refs),
            "cited_by_count": len(citing) if cited_by is None else cited_by,
        }
        self.citing[wid] = list(citing)
        return wid

    def many(self, n: int, title: str, **kw) -> list[str]:
        return [self.add(f"{title} {i}", **kw) for i in range(n)]

    def credits(self) -> int:
        """What OpenAlex would charge for the requests sent: 10 a search, 1 anything else."""
        return sum(10 if "search" in params else 1 for _, params in self.requests)

    def get(self, url: str, params: dict, timeout: float) -> Response:
        path = url.removeprefix(d.OPENALEX)
        with self.lock:
            self.requests.append((path, dict(params)))
            used_up = self.budget is not None and len(self.requests) > self.budget
        time.sleep(self.delay)
        if used_up or self.refuse(path, params):
            return Response(429, headers={"Retry-After": "3600"})
        if path.startswith("/works/doi:"):
            doi = "https://doi.org/" + path.removeprefix("/works/doi:")
            work = next((w for w in self.works.values() if w["doi"] == doi), None)
            return Response(200, work) if work else Response(404)
        per_page = params["per-page"]
        if "search" in params:
            return self.page(self.found.get(params["search"], [])[:per_page])
        kind, _, value = params["filter"].partition(":")
        if kind == "openalex":
            return self.page([f"https://openalex.org/{w}" for w in value.split("|")])
        assert kind == "cites", params
        citing = self.citing[f"https://openalex.org/{value}"]
        start = 0 if params["cursor"] == "*" else int(params["cursor"])
        more = start + per_page < len(citing)
        return self.page(citing[start : start + per_page], str(start + per_page) if more else None)

    def page(self, ids: list[str], cursor: str | None = None) -> Response:
        return Response(200, {"results": [self.works[i] for i in ids if i in self.works], "meta": {"next_cursor": cursor}})


class FakeModel:
    """Stands in for ask_llm(). hang: judging calls never answer, so each runs until its timeout."""

    def __init__(self):
        self.queries: list[str] = []
        self.hang = False
        self.calls = 0
        self.running = 0
        self.lock = threading.Lock()

    def __call__(self, prompt: str, system: str, model: str, json_schema: dict, timeout: float) -> str:
        with self.lock:
            self.calls += 1
            self.running += 1
        try:
            if system == d.QUERY_SYSTEM:
                return json.dumps({"queries": self.queries})
            if system == d.JUDGE_SYSTEM:
                if self.hang:
                    time.sleep(timeout)
                    raise TimeoutError("the model took too long")
                papers = re.findall(r"^(\d+)\. (.+?) \(\d{4}", prompt, re.M)
                return json.dumps({"papers": [
                    {"n": int(n), "score": 3 if title.startswith("Likely") else 0, "reason": "fake"}
                    for n, title in papers
                ]})
            raise AssertionError(f"unexpected call: {system[:40]}")
        finally:
            with self.lock:
                self.running -= 1


@pytest.fixture
def openalex(monkeypatch) -> FakeOpenAlex:
    fake = FakeOpenAlex()
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    monkeypatch.setattr(d.requests, "Session", lambda: fake)
    return fake


@pytest.fixture
def model(monkeypatch) -> FakeModel:
    fake = FakeModel()
    monkeypatch.setattr(d, "ask_llm", fake)
    return fake


@pytest.fixture(autouse=True)
def short_margins(monkeypatch):
    # The real margins keep the last 55 s of a search for its last calls; seconds will do here.
    monkeypatch.setattr(d, "FINISH_TIME", 1)
    monkeypatch.setattr(d, "CALL_TIME", 1)


# ---- credits ------------------------------------------------------------------


@pytest.mark.parametrize("limit", [25, 120])
def test_search_spends_at_most_its_credit_limit(openalex, model, monkeypatch, limit):
    monkeypatch.setattr(d, "CREDIT_LIMIT", limit)
    pool = openalex.many(300, "Other")
    # Each likely paper costs 4 credits to follow: 2 pages of references, 2 of citing papers.
    model.queries = ["query 1", "query 2", "query 3", "query 4"]
    for query in ["keywords", *model.queries]:
        openalex.found[query] = openalex.many(30, f"Likely {query}", refs=pool[:150], citing=pool)
    openalex.add("Likely seed", refs=pool[:150], citing=pool, doi=DOI)
    openalex.found["A seed by its title"] = [openalex.add("Likely titled seed", refs=pool[:150], citing=pool)]

    search = d.Search("keywords", [DOI, "A seed by its title"], [], 30, None)
    search.run()

    spent = openalex.credits()
    assert spent <= limit
    assert spent > limit - 4  # it went on until nothing more fitted
    assert search.credits == spent  # the count it keeps is what it really spent


@pytest.mark.parametrize(
    "refs, citing, cited_by, pages, papers",
    [
        (250, 450, None, 3 + 2, 250 + 400),  # 3 pages of references; citing papers capped at CITING_LIMIT
        (0, 0, None, 0, 0),  # nothing to fetch
        (50, 0, None, 1, 50),  # uncited: no page of citing papers
        (50, 300, 150, 1 + 1, 50 + 200),  # OpenAlex counted fewer citing papers than there are: one page
    ],
)
def test_neighbours_fetch_the_pages_neighbour_cost_reserved(openalex, model, refs, citing, cited_by, pages, papers):
    pool = openalex.many(max(refs, citing), "Other")
    wid = openalex.add("Likely", refs=pool[:refs], citing=pool[:citing], cited_by=cited_by)
    paper = d.to_paper(openalex.works[wid])

    found = d.Search("keywords", [], [], 30, None).neighbours(paper)

    assert d.neighbour_cost(paper) == pages
    assert len(openalex.requests) == pages
    assert len(found) == papers


# ---- time ---------------------------------------------------------------------


def test_search_ends_at_its_deadline(openalex, model, monkeypatch):
    # Margins of at least 5 s, as the real ones are: a model call is given 5 s even when less is left.
    monkeypatch.setattr(d, "FINISH_TIME", 2)
    monkeypatch.setattr(d, "CALL_TIME", 3)
    model.hang = True
    openalex.delay = 0.5
    openalex.found["keywords"] = openalex.many(5, "Likely")
    # 20 pages of references, 10 s of requests: more than the search has time for.
    openalex.add("Seed", refs=openalex.many(2000, "Other"), doi=DOI)
    budget = 7

    start = time.monotonic()
    assert d.discover("keywords", [DOI], budget=budget) == []
    took = time.monotonic() - start

    assert budget - 1 < took < budget + 1
    calls, sent = model.calls, len(openalex.requests)
    assert model.running == 0
    time.sleep(1)
    assert (model.calls, len(openalex.requests)) == (calls, sent)  # nothing left running


# ---- OpenAlex's daily budget ----------------------------------------------------


@pytest.mark.parametrize("seeds", [[], [DOI]])
def test_budget_used_up_before_anything_came_back(openalex, model, seeds):
    openalex.add("Likely seed", refs=openalex.many(10, "Likely"), doi=DOI)
    openalex.found["keywords"] = openalex.many(10, "Likely")
    openalex.refuse = lambda path, params: not path.startswith("/works/doi:")  # only seed lookups answered

    with pytest.raises(d.OpenAlexBudgetError, match="daily budget"):
        d.discover("keywords", seeds, budget=30)


def test_budget_used_up_mid_search_stops_following(openalex, model, monkeypatch):
    followed = []
    neighbours = d.Search.neighbours
    monkeypatch.setattr(d.Search, "neighbours", lambda self, paper: followed.append(paper.id) or neighbours(self, paper))
    pool = openalex.many(50, "Other")
    likely = openalex.found["keywords"] = openalex.many(30, "Likely", refs=pool)  # 1 page each to follow
    openalex.budget = 1 + 5  # the search, then 5 papers followed

    found = d.discover("keywords", budget=30)

    assert [p["openalex"] for p in found] == likely  # what was found before is still returned
    refused = len(openalex.requests) - openalex.budget
    assert 1 <= refused <= d.FOLLOW_WORKERS  # only the papers already being followed asked again
    assert len(followed) == 5 + refused


# ---- seeds --------------------------------------------------------------------


@pytest.mark.parametrize("seed", [DOI, f"doi:{DOI}", f"DOI: {DOI}", f"https://doi.org/{DOI}",
                                  f"http://dx.doi.org/{DOI}", f"  {DOI}  "])
def test_seed_by_doi(openalex, seed):
    wid = openalex.add("Seed", doi=DOI)

    paper = d.Search("keywords", [], [], 30, None).resolve(seed)

    assert paper.id == wid
    assert [path for path, _ in openalex.requests] == [f"/works/doi:{DOI}"]


def test_seed_by_title(openalex):
    openalex.found["Ionic conductivity of PEO"] = [openalex.add("Ionic conductivity of PEO-LiTFSI"), openalex.add("Other")]

    paper = d.Search("keywords", [], [], 30, None).resolve("Ionic conductivity of PEO")

    assert paper.title == "Ionic conductivity of PEO-LiTFSI"
    [(_, params)] = openalex.requests
    assert params["per-page"] == 1


@pytest.mark.parametrize("seed", ["10.9999/not-in-openalex", "A title nothing matches"])
def test_seed_not_found(openalex, seed):
    assert d.Search("keywords", [], [], 30, None).resolve(seed) is None


def test_seeds_are_followed_but_not_returned(openalex, model):
    cited = openalex.add("Likely cited by the seed")
    citing = openalex.add("Likely citing the seed")
    openalex.add("Likely seed", refs=[cited], citing=[citing], doi=DOI)
    openalex.found["A seed by its title"] = [openalex.add("Likely titled seed")]

    found = d.discover("keywords", [DOI, "A seed by its title"], budget=30)

    assert sorted(p["openalex"] for p in found) == [cited, citing]


# ---- the API ------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch) -> tuple[TestClient, list]:
    started = []
    monkeypatch.setattr(api.searcher, "submit", lambda fn, job, request: started.append(request))
    return TestClient(api.app), started


@pytest.mark.parametrize("body", [{"keywords": ""}, {"keywords": "   "}, {"keywords": "PEO", "seeds": [DOI] * 21}])
def test_api_refuses_a_bad_search(client, body):
    http, started = client
    assert http.post("/discover", json=body).status_code == 400
    assert started == []


def test_api_starts_a_search(client):
    http, started = client
    r = http.post("/discover", json={"keywords": " PEO ", "seeds": [DOI] * 20 + ["", " "], "features": ["Tg", " "]})

    assert r.status_code == 202
    assert http.get(f"/discover/{r.json()['job']}").json()["status"] == "running"
    [request] = started
    assert (request.keywords, len(request.seeds), request.features) == ("PEO", 20, ["Tg"])
