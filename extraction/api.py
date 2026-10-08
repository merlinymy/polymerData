"""HTTP API for extract_features.py, so the frontend can get data out of a paper.

    .venv/bin/python api.py        # http://127.0.0.1:8000, try it at http://127.0.0.1:8000/docs

POST /extract with a form holding `pdf` (the paper) and `features` (feature
names separated by commas) starts a job and answers {"job": "<id>"} at once.
GET /extract/<id> then answers {"status": "running"} until the job ends with
{"status": "done", "samples": {...}} or {"status": "failed", "error": "..."}.
Every answer also gives the PDF's file name (`file`), the feature names
(`features`), and when the job started (`started`, Unix time in seconds).
A running job's answer also has `progress`: the step it's on (`step`, an id
from job_progress.py), what to call that step (`name`), a sentence about it
(`description`), and how far along the job is (`percent`, 0-100).

A PDF parsed before takes about 1.5 minutes, a new one about 5, since MinerU
parses it first. Jobs run one at a time, in the order they came in, so
"running" includes waiting for earlier jobs -- the "queued" step, whose
description says how many are ahead. A finished job is also saved to
<DATA_DIR>/extractions/<id>.json, so its id keeps answering after a restart. A job
still running when the server stops is lost: its id answers 404.

What the server does goes to stdout and logs/extraction.log, each line tagged
with its job and step; LOG_LEVEL sets how much (see log_setup.py).
POST /discover with JSON {"keywords": "...", "seeds": [DOI or title, ...],
"features": [...]} (seeds and features optional) starts a search for papers
likely to report that data (discover.py) and answers {"job": "<id>"}.
GET /discover/<id> answers {"status": "running", "progress": {...}} until
{"status": "done", "papers": [...]} (best first) or {"status": "failed",
"error": "..."}. A search takes 5 minutes. Searches run one at a time, apart
from extractions, since each spends OpenAlex's daily budget.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
import uuid
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

import job_progress
from discover import discover
from extract_features import DATA_DIR, HERE, extract_features
from job_progress import QUEUED
from log_setup import LOG_FILE, configure_logging, job_context, resolve_level, set_step

os.chdir(HERE)  # the parse step's settings.yaml path is relative to extraction/

log = logging.getLogger("extraction.api")

RESULTS = DATA_DIR / "extractions"  # <job id>.json for each finished job


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # At startup rather than import, so `python api.py` and `uvicorn api:app`
    # both get it, and importing this module (tests) writes no log file.
    configure_logging()
    log.info("Ready: finished jobs saved to %s, logs written to %s", RESULTS, LOG_FILE)
    yield


app = FastAPI(title="Polymer data extraction", lifespan=lifespan)
# Lets pages served from this computer (the Vite dev server, on any port) read the answers.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)

jobs: dict[str, dict] = {}
worker = ThreadPoolExecutor(max_workers=1)  # one at a time, so two jobs never parse the same new PDF at once


def _jobs_ahead(job: str) -> int:
    """Running jobs that came in before `job`: the worker finishes them first."""
    mine = jobs[job]["started"]
    return sum(
        1 for other, info in list(jobs.items()) if other != job and info["status"] == "running" and info["started"] < mine
    )


def run(job: str, pdf: bytes, features: list[str]) -> None:
    with job_context(job):
        log.info("Started after %.1f s in the queue", time.time() - jobs[job]["started"])
        began = time.monotonic()
        current: dict = {"step": None, "since": began}

        def on_step(step: str) -> None:
            now = time.monotonic()
            if current["step"]:
                log.info("Step %s done in %.1f s", current["step"], now - current["since"])
            current.update(step=step, since=now)
            set_step(step)
            jobs[job] = {**jobs[job], "progress": job_progress.progress(step)}
            log.info("Step started: %s", job_progress.STEPS[step].name)

        try:
            with tempfile.TemporaryDirectory() as tmp:
                # No "<id>-" prefix in the name, so the parse step names the paper by
                # its contents and a PDF uploaded again reuses its earlier parse.
                path = Path(tmp) / "paper.pdf"
                path.write_bytes(pdf)
                outcome = {"status": "done", "samples": extract_features(path, features, on_step=on_step)}
            if current["step"]:
                log.info("Step %s done in %.1f s", current["step"], time.monotonic() - current["since"])
            log.info("Done in %.1f s", time.monotonic() - began)
        except Exception as e:
            log.exception("Failed after %.1f s: %s", time.monotonic() - began, e)
            outcome = {"status": "failed", "error": str(e)}
        # A finished job has no step to report, so its progress isn't kept or saved.
        jobs[job] = {**{key: value for key, value in jobs[job].items() if key != "progress"}, **outcome}
        _save(job)


def _save(job: str) -> None:
    """Write a finished job to RESULTS, so its id keeps answering after a restart."""
    try:
        RESULTS.mkdir(parents=True, exist_ok=True)
        saving = RESULTS / f"{job}.json.tmp"  # renamed once complete, so a crash never leaves half a file
        saving.write_text(json.dumps(jobs[job], ensure_ascii=False, indent=1), encoding="utf-8")
        saving.replace(RESULTS / f"{job}.json")
    except OSError:
        log.exception("Couldn't save the result to %s; it answers only until the server stops", RESULTS)
    else:
        log.debug("Saved to %s", RESULTS / f"{job}.json")


@app.post("/extract", status_code=202)
def start(pdf: UploadFile = File(...), features: str = Form(...)) -> dict:
    names = [name.strip() for name in features.split(",") if name.strip()]
    data = pdf.file.read()
    # The file name and features are the uploader's, so they're logged with %r:
    # quoted and escaped, never able to fake a line of their own.
    if not data.startswith(b"%PDF-"):
        log.warning("Refused %r: not a PDF", pdf.filename)
        raise HTTPException(400, "The uploaded file isn't a PDF.")
    if not names:
        log.warning("Refused %r: no feature names", pdf.filename)
        raise HTTPException(400, "Give at least one feature name.")
    job = uuid.uuid4().hex
    jobs[job] = {
        "status": "running",
        "file": pdf.filename or "paper.pdf",
        "features": names,
        "started": time.time(),
        "progress": job_progress.progress(QUEUED),
    }
    log.info(
        "Submitted %r (%d bytes) for %d feature(s) %r, %d job(s) ahead",
        jobs[job]["file"],
        len(data),
        len(names),
        names,
        _jobs_ahead(job),
        extra={"job": job, "step": QUEUED},
    )
    worker.submit(run, job, data, names)
    return {"job": job}


@app.get("/extract/{job}")
def status(job: str) -> dict:
    if job in jobs:
        answer = jobs[job]
        if answer["status"] == "running" and answer.get("progress", {}).get("step") == QUEUED:
            # How many jobs are ahead drops as they finish, so it's counted afresh each time.
            answer = {**answer, "progress": job_progress.progress(QUEUED, ahead=_jobs_ahead(job))}
        log.debug("Status: %s", answer["status"], extra={"job": job})
        return answer
    saved = RESULTS / f"{job}.json"
    if re.fullmatch(r"[0-9a-f]{32}", job) and saved.exists():  # only ids this server makes, never a path
        log.debug("Status: from %s", saved, extra={"job": job})
        return json.loads(saved.read_text(encoding="utf-8"))
    log.info("No such job: %r", job[:64])
    raise HTTPException(404, "No such job. A job still running when the server stopped is lost.")


searches: dict[str, dict] = {}
searcher = ThreadPoolExecutor(max_workers=1)
MAX_SEEDS = 20  # each title costs an OpenAlex search (10 credits) of the search's 1,000


class DiscoverRequest(BaseModel):
    keywords: str
    seeds: list[str] = []
    features: list[str] = []


def run_search(job: str, request: DiscoverRequest) -> None:
    def progress(counts: dict) -> None:
        searches[job] = {"status": "running", "progress": counts}

    try:
        papers = discover(request.keywords, request.seeds, request.features, progress=progress)
        searches[job] = {"status": "done", "papers": papers}
    except Exception as e:
        traceback.print_exc()
        searches[job] = {"status": "failed", "error": str(e)}


@app.post("/discover", status_code=202)
def start_search(request: DiscoverRequest) -> dict:
    request.keywords = request.keywords.strip()
    request.seeds = [s.strip() for s in request.seeds if s.strip()]
    request.features = [f.strip() for f in request.features if f.strip()]
    if not request.keywords:
        raise HTTPException(400, "Give some keywords.")
    if len(request.seeds) > MAX_SEEDS:
        raise HTTPException(400, f"Give at most {MAX_SEEDS} papers you already have.")
    job = uuid.uuid4().hex
    searches[job] = {"status": "running", "progress": None}
    searcher.submit(run_search, job, request)
    return {"job": job}


@app.get("/discover/{job}")
def search_status(job: str) -> dict:
    if job not in searches:
        raise HTTPException(404, "No such search. The server forgets its searches when it restarts.")
    return searches[job]


if __name__ == "__main__":
    level, _ = resolve_level(os.environ.get("LOG_LEVEL"))
    # uvicorn's own lines (startup, one per request) follow LOG_LEVEL too.
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level=logging.getLevelName(level).lower())
