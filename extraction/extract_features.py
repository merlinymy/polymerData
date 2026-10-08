"""Extract the features you name from one paper: a PDF and a list of feature
names in, a table out, with one row per data point the paper reports, a
first column naming the sample it belongs to, and one column per feature.

    .venv/bin/python extract_features.py paper.pdf features.txt              # CSV to the terminal
    .venv/bin/python extract_features.py paper.pdf features.txt -o out.csv
    .venv/bin/python extract_features.py paper.pdf features.txt --send-pdf   # skip MinerU

features.txt holds one feature name per line, for example

    Polymer
    Anion
    Tg (°C)
    Conductivity at 25C (S/cm)

Put a unit in a feature's name to get its numbers in that unit; without one
they come in whatever unit the paper uses. A sample has several data points
when the paper gives a feature at several conditions (its conductivity at
several temperatures, say), otherwise one. A blank cell means the paper
doesn't give that value for that data point.

How it works: MinerU turns the PDF into text and figure images (the
pipeline's parse step, written to <DATA_DIR>/parsed/<paper id>/), and the model
reads both through util/claudeAPIMock.py's ask_llm(), for now Claude via
Claude Code. A PDF that was parsed before is not parsed again, so only the
first run of a paper waits for MinerU. Instead of a PDF you can pass a folder
the parse step already made.

With --send-pdf the PDF itself goes to the model and MinerU isn't used:
Claude reads the pages, tables and plots on its own. That needs a model that
reads PDFs (Claude does; most local models don't).

Not wired into pipeline/ yet. It can be started from any folder. It logs
each parse and model call (log_setup.py), to stderr when run as a script so
the CSV on stdout stays clean.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]  # repo root for `util`, extraction/ for `pipeline`

from pipeline.paper_id import paper_id_from_path  # noqa: E402
from pipeline.parsing.figure_links import prompt_anchor, rewrite_to_prompt_anchors  # noqa: E402
from pipeline.parsing.manifest_schema import ParseManifest  # noqa: E402
from pipeline.parsing.parse_paper import parse_paper_auto  # noqa: E402
from util.claudeAPIMock import ask_llm  # noqa: E402

from job_progress import ASKING, COLLECTING, PARSING  # noqa: E402
from log_setup import configure_logging  # noqa: E402

log = logging.getLogger("extraction.pipeline")

load_dotenv(HERE / ".env")
# Where the parsed papers (parsed/) and the server's finished jobs (extractions/) are kept:
# DATA_DIR from the environment or extraction/.env, relative to the repo root unless
# absolute. setup.sh asks for it; unset, it's extraction/output/.
DATA_DIR = HERE.parent / Path(os.environ.get("DATA_DIR") or "extraction/output").expanduser()
OUTPUT_ROOT = DATA_DIR / "parsed"

# Called with a job_progress step id as each step starts.
OnStep = Callable[[str], None]

_TASK = (
    "Return each sample the paper reports, named as the paper names it (or by its composition if the paper "
    "gives it no name), with its values for each feature, taken from the text, the tables or the figures. "
    "Give a sample one data point, or several if the paper gives a feature at several conditions (for "
    "example at several temperatures). Give numbers as plain numbers, in the unit a feature's name gives if "
    "it gives one. Leave out a feature the paper doesn't give."
)
# For MinerU's text and figure crops.
SYSTEM = (
    "You extract data from a scientific paper. You get the paper's text (converted from PDF, tables "
    "included), its figures, and a list of features. Each figure comes after the text, labelled with the "
    "[FIGURE ...] line that marks its place in the text. " + _TASK
)
# For the PDF itself (--send-pdf).
SYSTEM_PDF = "You extract data from a scientific paper. You get the paper as a PDF and a list of features. " + _TASK


def feature_list(features: list[str]) -> str:
    return "Features:\n" + "\n".join(f"- {feature}" for feature in features)


def build_prompt(paper_dir: Path, features: list[str]) -> tuple[str, list[tuple[Path, str]]]:
    """The message text and the labelled figure images for one parsed paper."""
    manifest = ParseManifest.model_validate_json((paper_dir / "manifest.json").read_text())
    paper_text = rewrite_to_prompt_anchors(
        (paper_dir / manifest.content_md_path).read_text(encoding="utf-8"), manifest.figures
    )
    images = [
        (paper_dir / fig.image_path, f"{prompt_anchor(fig, i)} {fig.caption or '(caption not found)'}")
        for i, fig in enumerate(manifest.figures, 1)
    ]
    return f"{feature_list(features)}\n\nPaper:\n\n{paper_text}", images


def _ask(prompt: str, **kwargs) -> str:
    """ask_llm(), logged: what was sent, how long the reply took, or why it failed."""
    log.info(
        "LLM call: model %s, prompt %d chars, %d image(s), %d PDF(s)",
        kwargs.get("model") or "(Claude Code's default)",
        len(prompt),
        len(kwargs.get("images", ())),
        len(kwargs.get("documents", ())),
    )
    start = time.monotonic()
    try:
        reply = ask_llm(prompt, **kwargs)
    except Exception as e:
        log.error("LLM call failed after %.1f s: %s", time.monotonic() - start, e)
        raise
    log.info("LLM reply after %.1f s: %d chars", time.monotonic() - start, len(reply))
    return reply


def extract_features(
    paper: Path,
    features: list[str],
    model: str | None = None,
    send_pdf: bool = False,
    on_step: OnStep | None = None,
) -> dict[str, list[dict]]:
    """Each sample's name mapped to its data points, each a dict of every feature, in the order given;
    None where the paper doesn't give it. Samples the model gives the same name are merged.

    send_pdf=True sends the PDF itself instead of MinerU's text and figures.
    on_step is called with each job_progress step as it starts: PARSING (only
    when MinerU runs), ASKING, then COLLECTING.
    """
    step = on_step or (lambda _: None)
    value = {"type": ["string", "number", "null"]}
    point = {"type": "object", "properties": {feature: value for feature in features}, "additionalProperties": False}
    schema = {
        "type": "object",
        "properties": {
            "samples": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"sample": {"type": "string"}, "points": {"type": "array", "items": point}},
                    "required": ["sample", "points"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["samples"],
        "additionalProperties": False,
    }
    if send_pdf:
        if paper.suffix.lower() != ".pdf":
            raise ValueError(f"{paper}: --send-pdf needs the paper's PDF, not a parsed folder")
        step(ASKING)
        reply = _ask(feature_list(features), system=SYSTEM_PDF, model=model, json_schema=schema, documents=[paper])
    else:
        text, images = build_prompt(paper if paper.is_dir() else parse(paper, on_step=step), features)
        step(ASKING)
        reply = _ask(text, system=SYSTEM, model=model, json_schema=schema, images=images)
    step(COLLECTING)
    samples: dict[str, list[dict]] = {}
    for reported in json.loads(reply)["samples"]:
        points = samples.setdefault(reported["sample"], [])
        points += ({feature: p.get(feature) for feature in features} for p in reported["points"])
    log.info("Extracted %d sample(s), %d data point(s)", len(samples), sum(len(p) for p in samples.values()))
    return samples


def parse(pdf: Path, on_step: OnStep | None = None) -> Path:
    """OUTPUT_ROOT/<paper id>/ for this PDF, running the parse step first if it
    isn't there yet -- and only then calling on_step(PARSING)."""
    try:
        paper_id = paper_id_from_path(pdf)
        named = None
    except ValueError:
        # The parse step takes a paper's id from the front of its file name
        # (papers/0a011d54-tominaga2012.pdf). Any other PDF gets one from its
        # contents and is parsed under that name.
        paper_id = hashlib.sha256(pdf.read_bytes()).hexdigest()[:8]
        named = f"{paper_id}-{pdf.stem}.pdf"
    paper_dir = OUTPUT_ROOT / paper_id
    if (paper_dir / "manifest.json").exists():
        log.info("Reusing the saved parse in %s", paper_dir)
        return paper_dir
    if on_step:
        on_step(PARSING)
    log.info("Parsing with MinerU into %s", paper_dir)
    start = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        source = pdf
        if named:
            source = Path(tmp) / named
            shutil.copyfile(pdf, source)
        manifest = parse_paper_auto(source, dest_dir=paper_dir)
    log.info(
        "MinerU parse done in %.1f s: %d figure(s), %d table(s)",
        time.monotonic() - start,
        len(manifest.figures),
        manifest.num_tables,
    )
    return paper_dir


def write_csv(samples: dict[str, list[dict]], features: list[str], out: TextIO) -> None:
    writer = csv.DictWriter(out, fieldnames=["sample", *features])
    writer.writeheader()
    writer.writerows({"sample": name, **point} for name, points in samples.items() for point in points)


def main() -> None:
    ap = argparse.ArgumentParser(prog="extract_features.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("paper", type=Path, help="the paper's PDF, or a folder the parse step already made")
    ap.add_argument("features", type=Path, help="text file with one feature name per line")
    ap.add_argument("-o", "--output", type=Path, help="CSV file to write (default: print it)")
    ap.add_argument("--model", help="e.g. claude-sonnet-5 (default: your Claude Code default model)")
    ap.add_argument("--send-pdf", action="store_true", help="send the PDF itself instead of MinerU's text and figures")
    args = ap.parse_args()

    configure_logging(stream=sys.stderr)  # stdout carries the CSV
    paper, output = args.paper.resolve(), args.output.resolve() if args.output else None
    lines = args.features.read_text(encoding="utf-8").splitlines()
    features = [line.strip() for line in lines if line.strip()]
    os.chdir(HERE)  # the parse step's settings.yaml path is relative to extraction/
    samples = extract_features(paper, features, model=args.model, send_pdf=args.send_pdf)
    if output is None:
        write_csv(samples, features, sys.stdout)
        return
    with open(output, "w", newline="", encoding="utf-8") as f:
        write_csv(samples, features, f)
    rows = sum(len(points) for points in samples.values())
    print(f"{rows} rows from {len(samples)} samples -> {output}", file=sys.stderr)


if __name__ == "__main__":
    main()
