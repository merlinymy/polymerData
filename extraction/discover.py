"""Find papers that likely report the data you want (issue #7): keywords, and
optionally papers you already have and the features you want, in; a ranked
list of papers out.

    .venv/bin/python discover.py "solid polymer electrolyte lithium conductivity"
    .venv/bin/python discover.py "PEO LiTFSI" --seed 10.1021/ma00103a034 --feature Tg --feature "Conductivity at 25C"
    .venv/bin/python discover.py "PEO LiTFSI" -o found.json --budget 120

How it works: search OpenAlex for the keywords (and a few rewordings of them
the model suggests), then let the model judge each candidate from its title,
journal, year and abstract: does it likely report the data as numbers? From
each paper judged likely, and from each paper you gave, follow its references
and the papers citing it; those become candidates in turn, the ones linked
from the most likely papers judged first. It stops when the time budget
(5 minutes by default) runs out or no candidates are left.

OpenAlex charges each request against a daily budget: a search costs 10
credits, a page of up to 200 papers 1. Without a key, everyone on your IP
address shares 1,000 a day; a free key (openalex.org/settings/api) gives
10,000. Put it in extraction/.env as OPENALEX_API_KEY=... A search spends at
most CREDIT_LIMIT of them, following the most likely papers first.

The judgement is a guess from metadata; whether a paper really holds the data
is what extract_features.py finds out. OpenAlex has no abstract for most
Elsevier papers, which is most of this field, so those are judged from their
title alone and get no description. Semantic Scholar and Crossref were tried
as other sources of abstracts and had none OpenAlex lacked.

The model is reached through util/claudeAPIMock.py's ask_llm(), so a search
counts against your Claude Code plan: one call per 80 candidates judged,
about 70 in 5 minutes, and a few more for the queries and descriptions. A
cap of 40 judging calls was tried: the same top 100, but 57% of the golden
papers listed instead of 75%, so there is none.
"""

from __future__ import annotations

import argparse
import heapq
import itertools
import json
import math
import os
import re
import sys
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path

import requests
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent)]  # repo root, for `util`

from util.claudeAPIMock import ask_llm  # noqa: E402

load_dotenv(HERE / ".env")

OPENALEX = "https://api.openalex.org"
FIELDS = (
    "id,doi,title,publication_year,type,authorships,primary_location,abstract_inverted_index,"
    "best_oa_location,referenced_works,cited_by_count"
)
# Kinds of work that can report measurements; leaves out errata, editorials, datasets and the like.
TYPES = {"article", "letter", "preprint", "review", "book-chapter"}

MODEL = "sonnet"  # haiku took longer per call here and judged nearly every title likely
JUDGE_BATCH = 80  # candidates per judging call, about 20 s each
JUDGE_WORKERS = 8  # calls at once; 8 took no longer than 1
DESCRIBED = 100  # papers at the top of the list that get a description, if they have an abstract
LIKELY = 2  # lowest score (0-3) counted as likely: followed, and returned
SEARCH_RESULTS = 200  # per query
CITING_LIMIT = 400  # papers citing one likely paper that are fetched; reviews have thousands
CREDIT_LIMIT = 1000  # OpenAlex credits one search may spend; a free key has 10,000 a day
FOLLOW_WORKERS = 4  # papers whose neighbours are fetched at once
FINISH_TIME = 30  # seconds kept at the end for the descriptions
CALL_TIME = 25  # seconds a judging call takes; none starts, nor a page whose papers it would judge, too late to finish

JUDGE_SYSTEM = (
    "You help a scientist find papers to extract data from. You get what they are looking for and a "
    "numbered list of papers, each with its title, year, journal, and abstract when there is one. Score "
    "how likely each paper is to report that data as numbers from its own experiments or calculations: "
    "3 clearly does, 2 probably does, 1 might, 0 doesn't (another subject, or a review or theory without "
    "such numbers). Most papers here have no abstract; judge those from the title and journal, and don't "
    "score a paper lower only because its abstract is missing. Give a reason of at most 15 words."
)
QUERY_SYSTEM = (
    "You write search queries for OpenAlex, a database of scientific papers, which matches the words in a "
    "paper's title and abstract. Given what a scientist is looking for, write up to 4 short queries (2-6 "
    "words each) that between them find the papers they want: other names for the same materials, "
    "properties or methods, abbreviations spelled out. Don't repeat the request itself."
)
DESCRIBE_SYSTEM = (
    "You get numbered paper abstracts. For each, write one plain sentence of at most 30 words saying what "
    "the paper studies and what it measures. Use only what the abstract says."
)


@dataclass
class Paper:
    id: str  # OpenAlex id, https://openalex.org/W...
    title: str
    year: int | None
    journal: str | None
    authors: list[str]
    doi: str | None  # https://doi.org/...
    pdf: str | None  # an open-access PDF, when OpenAlex knows one
    abstract: str | None
    references: list[str]
    type: str | None
    cited_by: int = 0
    links: int = 0  # likely papers (or papers you gave) this one cites or is cited by
    search_rank: int | None = None  # best position in the keyword searches
    score: int | None = None  # the model's 0-3, once judged
    reason: str = ""
    description: str | None = None

    def result(self) -> dict:
        return {
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "journal": self.journal,
            "doi": self.doi,
            "pdf": self.pdf,
            "score": self.score,
            "reason": self.reason,
            "description": self.description,
            "openalex": self.id,
        }


def discover(
    keywords: str,
    seeds: Iterable[str] = (),
    features: Iterable[str] = (),
    budget: float = 300,
    progress: Callable[[dict], None] | None = None,
) -> list[dict]:
    """Papers judged likely to report the data, best first, as dicts (see Paper.result).

    seeds: papers you already have, each a DOI (bare or as a doi.org link) or a title. They are followed
        but left out of the results. A title is matched to OpenAlex's closest search result.
    features: the data wanted, e.g. "Tg" or "Conductivity at 25C". Without them, any measurements on
        the subject count.
    budget: seconds the whole search may take.
    progress: called now and then with counts so far (candidates, judged, likely, seconds).
    """
    return Search(keywords, list(seeds), list(features), budget, progress).run()


class OpenAlexBudgetError(RuntimeError):
    """OpenAlex's daily budget for this key, or for this IP address without one, is used up."""


class CreditLimitReached(Exception):
    """This request would take the search past CREDIT_LIMIT, so it isn't sent."""


class SearchStopped(Exception):
    """The search is over; a request still running when it ended gives up instead of going on."""


class Search:
    def __init__(self, keywords, seeds, features, budget, progress):
        self.keywords, self.seeds, self.features = keywords, seeds, features
        self.start = time.monotonic()
        self.deadline = self.start + budget
        self.progress = progress
        self.http = requests.Session()
        if key := os.environ.get("OPENALEX_API_KEY"):
            self.http.params = {"api_key": key}
        self.credits = 0  # OpenAlex credits spent or promised to running requests
        self.credit_lock = threading.Lock()
        self.out_of_credits: str | None = None  # why OpenAlex stopped answering, once it has
        self.to_follow: list[tuple] = []  # (priority, tiebreak, id) of likely papers not followed yet
        self.stopped = threading.Event()
        self.papers: dict[str, Paper] = {}
        self.queue: list[tuple] = []  # (priority, tiebreak, id) of candidates not judged yet
        self.order = itertools.count()
        self.followed: set[str] = set()
        self.seed_ids: set[str] = set()

    # ---- the search -------------------------------------------------------------

    def run(self) -> list[dict]:
        llm = ThreadPoolExecutor(JUDGE_WORKERS)
        web = ThreadPoolExecutor(4)
        try:
            queries = llm.submit(self.queries)
            seeds = [web.submit(self.resolve, s) for s in self.seeds]
            searches = [web.submit(self.search, self.keywords)]
            pending: dict[Future, tuple] = {f: ("search", None) for f in searches}
            pending[queries] = ("queries", None)
            pending |= {f: ("seed", None) for f in seeds}

            while True:
                self.follow_next(web, pending)
                # Keep the model busy with the best candidates left, while there is time for a call to finish.
                while len([k for k, _ in pending.values() if k == "judge"]) < JUDGE_WORKERS and self.queue:
                    if time.monotonic() > self.deadline - FINISH_TIME - CALL_TIME:
                        self.queue.clear()  # no time left to judge the rest
                        break
                    if batch := self.take(JUDGE_BATCH):
                        pending[llm.submit(self.judge, batch)] = ("judge", batch)
                if not pending:
                    break
                remaining = self.deadline - FINISH_TIME - time.monotonic()
                done, _ = wait(pending, timeout=max(remaining, 0), return_when=FIRST_COMPLETED)
                if not done:
                    break  # out of time: drop what is still running
                for future in done:
                    kind, batch = pending.pop(future)
                    try:
                        value = future.result()
                    except OpenAlexBudgetError as e:
                        self.out_of_credits = str(e)
                        continue
                    except CreditLimitReached:
                        print(f"discover: {kind} skipped: the search's {CREDIT_LIMIT} credits are spent", file=sys.stderr)
                        continue
                    except Exception as e:  # one failed call or page costs its candidates, not the search
                        print(f"discover: {kind} failed: {e}", file=sys.stderr)
                        continue
                    if kind == "queries":
                        pending |= {web.submit(self.search, q): ("search", None) for q in value}
                    elif kind == "search":
                        for rank, paper in enumerate(value):
                            self.add(paper, search_rank=rank)
                    elif kind == "seed" and value:
                        self.seed_ids.add(value.id)
                        self.add(value)
                        value.score, value.reason = 3, "You gave this paper."
                        self.follow(value)
                    elif kind == "judge":
                        for paper in batch:
                            if (paper.score or 0) >= LIKELY:
                                self.follow(paper)
                    elif kind == "neighbours":
                        for paper in value:
                            self.add(paper, link=True)
                self.report()

            if self.out_of_credits and not any(pid not in self.seed_ids for pid in self.papers):
                # Only your papers came back (they aren't results): say why, not "nothing found".
                raise OpenAlexBudgetError(self.out_of_credits)
            if self.out_of_credits:
                print(f"discover: stopped following papers early: {self.out_of_credits}", file=sys.stderr)
            found = sorted(
                (p for p in self.papers.values() if (p.score or 0) >= LIKELY and p.id not in self.seed_ids),
                key=lambda p: (-p.score, -p.links, p.search_rank if p.search_rank is not None else 1e9),
            )
            self.describe(found, llm)
            return [p.result() for p in found]
        finally:
            # Wait for calls still running, so the next search never overlaps this one: model calls
            # time out at the deadline, and OpenAlex requests give up at their next page.
            self.stopped.set()
            llm.shutdown(wait=True, cancel_futures=True)
            web.shutdown(wait=True, cancel_futures=True)

    def follow(self, paper: Paper) -> None:
        """Queue a likely paper to have its references and citing papers fetched."""
        if paper.id not in self.followed:
            self.followed.add(paper.id)
            rank = paper.search_rank if paper.search_rank is not None else SEARCH_RESULTS
            heapq.heappush(self.to_follow, ((-paper.score, -paper.links, rank), next(self.order), paper.id))

    def follow_next(self, web: ThreadPoolExecutor, pending: dict) -> None:
        """Fetch the neighbours of the most likely papers queued, while credits and time last."""
        running = sum(kind == "neighbours" for kind, _ in pending.values())
        while self.to_follow and running < FOLLOW_WORKERS and not self.out_of_credits:
            if time.monotonic() > self.deadline - FINISH_TIME - CALL_TIME:
                return  # its candidates would come too late to be judged
            paper = self.papers[heapq.heappop(self.to_follow)[-1]]
            cost = neighbour_cost(paper)
            with self.credit_lock:
                if self.credits + cost > CREDIT_LIMIT:
                    continue  # too dear; a cheaper one further down may still fit
                self.credits += cost
            pending[web.submit(self.neighbours, paper)] = ("neighbours", None)
            running += 1

    def add(self, paper: Paper, search_rank: int | None = None, link: bool = False) -> None:
        """Record a candidate, or another way to reach one already known, and queue it for judging."""
        known = self.papers.setdefault(paper.id, paper)
        if search_rank is not None and (known.search_rank is None or search_rank < known.search_rank):
            known.search_rank = search_rank
        if link:
            known.links += 1
        if known.score is None and known.type in TYPES:
            # Linked from more likely papers first, then higher in a keyword search. A paper queued
            # twice is judged at its better priority; the stale entry is skipped by take().
            rank = known.search_rank if known.search_rank is not None else SEARCH_RESULTS
            heapq.heappush(self.queue, ((-known.links, rank), next(self.order), known.id))

    def take(self, n: int) -> list[Paper]:
        batch: list[Paper] = []
        while self.queue and len(batch) < n:
            *_, pid = heapq.heappop(self.queue)
            paper = self.papers[pid]
            if paper.score is None:
                paper.score = -1  # taken, so a stale queue entry doesn't send it twice
                batch.append(paper)
        return batch

    def report(self) -> None:
        if self.progress:
            judged = [p for p in self.papers.values() if p.score is not None and p.score >= 0]
            self.progress({
                "candidates": len(self.papers),
                "judged": len(judged),
                "likely": sum(p.score >= LIKELY for p in judged if p.id not in self.seed_ids),
                "seconds": round(time.monotonic() - self.start),
                "credits": self.credits,
            })

    # ---- the model --------------------------------------------------------------

    def wanted(self) -> str:
        text = f"Looking for: {self.keywords}"
        if self.features:
            text += "\nData wanted: " + ", ".join(self.features)
        return text

    def queries(self) -> list[str]:
        schema = {
            "type": "object",
            "properties": {"queries": {"type": "array", "items": {"type": "string"}, "maxItems": 4}},
            "required": ["queries"],
            "additionalProperties": False,
        }
        reply = ask_llm(self.wanted(), system=QUERY_SYSTEM, model=MODEL, json_schema=schema, timeout=self.time_left())
        return json.loads(reply)["queries"][:4]

    def judge(self, batch: list[Paper]) -> None:
        lines = []
        for i, p in enumerate(batch):
            line = f"{i}. {p.title} ({p.year or 'year unknown'}; {p.journal or 'journal unknown'})"
            if p.abstract:
                line += f"\n   Abstract: {p.abstract[:600]}"
            lines.append(line)
        schema = {
            "type": "object",
            "properties": {
                "papers": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "n": {"type": "integer"},
                            "score": {"type": "integer", "minimum": 0, "maximum": 3},
                            "reason": {"type": "string"},
                        },
                        "required": ["n", "score", "reason"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["papers"],
            "additionalProperties": False,
        }
        try:
            reply = ask_llm(f"{self.wanted()}\n\nPapers:\n" + "\n".join(lines), system=JUDGE_SYSTEM,
                            model=MODEL, json_schema=schema, timeout=self.time_left())
        except Exception:
            for p in batch:
                p.score = None  # not judged after all
            raise
        for item in json.loads(reply)["papers"]:
            if 0 <= item["n"] < len(batch):
                batch[item["n"]].score, batch[item["n"]].reason = item["score"], item["reason"]
        for p in batch:
            if p.score == -1:  # the model skipped it
                p.score = None

    def describe(self, found: list[Paper], llm: ThreadPoolExecutor) -> None:
        """A sentence for each of the top DESCRIBED papers with an abstract, as the time left allows."""
        todo = [p for p in found[:DESCRIBED] if p.abstract]
        schema = {
            "type": "object",
            "properties": {
                "papers": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"n": {"type": "integer"}, "description": {"type": "string"}},
                        "required": ["n", "description"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["papers"],
            "additionalProperties": False,
        }

        def one(batch: list[Paper]) -> None:
            text = "\n\n".join(f"{i}. {p.abstract[:1500]}" for i, p in enumerate(batch))
            reply = ask_llm(text, system=DESCRIBE_SYSTEM, model=MODEL, json_schema=schema, timeout=self.time_left())
            for item in json.loads(reply)["papers"]:
                if 0 <= item["n"] < len(batch):
                    batch[item["n"]].description = item["description"]

        futures = [llm.submit(one, todo[i : i + 20]) for i in range(0, len(todo), 20)]
        wait(futures, timeout=max(self.deadline - time.monotonic(), 1))

    # ---- OpenAlex ---------------------------------------------------------------

    def time_left(self) -> float:
        """Seconds until the deadline, as a model call's timeout (a few at least, so it can start)."""
        return max(self.deadline - time.monotonic(), 5)

    def get(self, path: str, charge: int = 0, **params) -> dict:
        """GET from OpenAlex. charge: credits this request costs, reserved first and refused past
        CREDIT_LIMIT; neighbours() reserves its pages in follow_next() instead."""
        with self.credit_lock:
            if self.credits + charge > CREDIT_LIMIT:
                raise CreditLimitReached
            self.credits += charge
        for attempt in range(4):
            if self.stopped.is_set():
                raise SearchStopped
            r = self.http.get(f"{OPENALEX}{path}", params=params, timeout=30)
            if r.status_code == 429 and float(r.headers.get("Retry-After", 0)) > 60:
                # Not a burst of requests to wait out: the day's budget is gone until midnight UTC.
                hours = float(r.headers["Retry-After"]) / 3600
                whose = "this API key" if "api_key" in (self.http.params or {}) else "this IP address; no API key set"
                raise OpenAlexBudgetError(f"OpenAlex's daily budget ({whose}) is used up; it renews in {hours:.1f} h")
            if r.status_code not in (429, 500, 502, 503, 504):
                r.raise_for_status()
                return r.json()
            time.sleep(1 + attempt * 2)
        r.raise_for_status()
        return r.json()

    def search(self, query: str) -> list[Paper]:
        data = self.get("/works", charge=10, search=query, filter="type:" + "|".join(sorted(TYPES)),
                        select=FIELDS, **{"per-page": SEARCH_RESULTS})
        return [to_paper(w) for w in data["results"]]

    def resolve(self, seed: str) -> Paper | None:
        seed = seed.strip()
        doi = re.sub(r"^(https?://)?(dx\.)?doi\.org/|^doi:\s*", "", seed, flags=re.I)
        if re.match(r"10\.\d{4,9}/\S+$", doi):
            try:
                return to_paper(self.get(f"/works/doi:{doi}", charge=1, select=FIELDS))
            except requests.HTTPError:
                print(f"discover: no paper in OpenAlex with DOI {doi}", file=sys.stderr)
                return None
        results = self.get("/works", charge=10, search=seed, select=FIELDS, **{"per-page": 1})["results"]
        if not results:
            print(f"discover: no paper in OpenAlex matches {seed!r}", file=sys.stderr)
        return to_paper(results[0]) if results else None

    def neighbours(self, paper: Paper) -> list[Paper]:
        """The papers this one cites, then up to CITING_LIMIT papers citing it."""
        found: list[Paper] = []
        refs = [r.rsplit("/", 1)[-1] for r in paper.references]
        for i in range(0, len(refs), 100):
            ids = "|".join(refs[i : i + 100])
            found += map(to_paper, self.get("/works", filter=f"openalex:{ids}", select=FIELDS, **{"per-page": 100})["results"])
        # Exactly the pages neighbour_cost() paid for: none for an uncited paper, and no more when
        # OpenAlex's count was low.
        cursor = "*"
        for _ in range(citing_pages(paper)):
            data = self.get("/works", filter=f"cites:{paper.id.rsplit('/', 1)[-1]}", select=FIELDS,
                            cursor=cursor, **{"per-page": 200})
            found += map(to_paper, data["results"])
            cursor = data["meta"].get("next_cursor")
            if not data["results"] or not cursor:
                break
        return found


def to_paper(w: dict) -> Paper:
    source = (w.get("primary_location") or {}).get("source") or {}
    oa = w.get("best_oa_location") or {}
    return Paper(
        id=w["id"],
        title=w.get("title") or "(no title)",
        year=w.get("publication_year"),
        journal=source.get("display_name"),
        authors=[a["author"]["display_name"] for a in w.get("authorships") or [] if a.get("author")],
        doi=w.get("doi"),
        pdf=oa.get("pdf_url"),
        abstract=abstract(w.get("abstract_inverted_index")),
        references=w.get("referenced_works") or [],
        type=w.get("type"),
        cited_by=w.get("cited_by_count") or 0,
    )


def citing_pages(paper: Paper) -> int:
    """Pages of 200 citing papers neighbours() fetches, up to CITING_LIMIT papers."""
    return math.ceil(min(paper.cited_by, CITING_LIMIT) / 200)


def neighbour_cost(paper: Paper) -> int:
    """OpenAlex credits neighbours() spends on a paper: a page per 100 references, per 200 citing papers."""
    return math.ceil(len(paper.references) / 100) + citing_pages(paper)


def abstract(index: dict | None) -> str | None:
    """OpenAlex keeps abstracts as {word: [positions]}; put the words back in order."""
    if not index:
        return None
    words = sorted((pos, word) for word, positions in index.items() for pos in positions)
    return " ".join(word for _, word in words)


def main() -> None:
    ap = argparse.ArgumentParser(prog="discover.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("keywords", help="what the papers are about")
    ap.add_argument("--seed", action="append", default=[], help="a paper you have, by DOI or title (repeatable)")
    ap.add_argument("--feature", action="append", default=[], help="a feature you want, e.g. Tg (repeatable)")
    ap.add_argument("--budget", type=float, default=300, help="seconds the search may take (default 300)")
    ap.add_argument("-o", "--output", type=Path, help="JSON file to write (default: print a short list)")
    args = ap.parse_args()

    def progress(counts: dict) -> None:
        print("\r" + "  ".join(f"{k} {v}" for k, v in counts.items()), end="", file=sys.stderr, flush=True)

    found = discover(args.keywords, args.seed, args.feature, args.budget, progress)
    print(file=sys.stderr)
    if args.output:
        args.output.write_text(json.dumps(found, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"{len(found)} papers -> {args.output}", file=sys.stderr)
        return
    for p in found:
        print(f"[{p['score']}] {p['year']}  {p['title']}\n      {p['doi'] or p['openalex']}  {p['reason']}")


if __name__ == "__main__":
    main()
