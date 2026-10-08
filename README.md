# polymerData

Monorepo for the polymer electrolyte data project: paper extraction, data
pipelines, and the frontend explorer.

- [`extraction/`](extraction/) — parses uploaded papers (text, tables, figures) with MinerU,
  sends the parsed content to an LLM to extract structured data, and scores
  results against the golden dataset (`extraction/data/_Cleaned_Final_Data_6_2_2020.csv`).
- [`frontend/`](frontend/) — the client-side app that visualizes the polymer-electrolyte
  conductivity dataset (a rebuild of pedatamine.org).
- [`util/`](util/) — helpers shared across the project. `claudeAPIMock.py` is how
  project code makes an LLM call; see below.

To use the app on your own computer, follow [Getting started](#getting-started).
[`frontend/README.md`](frontend/README.md) has more about the app itself.

## Getting started

This is for anyone who wants to use the app on a Mac, without typing any
commands. The app is a set of web pages: plots and tables of the
polymer-electrolyte dataset, plus **Extract**, which pulls the data you name out
of a paper's PDF.

Everything runs on your Mac except Claude, the AI model that reads the papers.
The app reaches Claude through Claude Code, Anthropic's program for using
Claude from your computer, logged in with your own Claude account. So you don't
need an API key (a separate, pay-per-use password for Claude), and nothing is
billed beyond your Claude plan.

### What you need

- **A Mac** with macOS 12 or newer. On Linux, see
  [Setting it up by hand](#setting-it-up-by-hand). Windows isn't supported yet.
- **A paid Claude plan: Pro, Max, Team or Enterprise.** The free plan doesn't
  include Claude Code. Each extraction counts against your plan's usage
  limits, the way a long chat does.
- **About 6 GB of free disk space,** most of it for MinerU, the program that
  turns a PDF into text and figure images before Claude reads it.
- **An internet connection,** for the downloads and for Claude.

You don't install anything beforehand. PolymerData downloads what it needs the
first time you open it.

### 1. Download it

1. On https://github.com/merlinymy/polymerData, choose the green **Code**
   button, then **Download ZIP**.
2. Open the downloaded `polymerData-main.zip` to unzip it, if your browser
   hasn't already. You get a folder called `polymerData-main`.
3. If you like, move that folder somewhere you'll find it again, such as your
   home folder. Keep everything in it together: PolymerData needs the other
   files next to it.

### 2. Open PolymerData the first time

In the `polymerData-main` folder, double-click **PolymerData**.

macOS stops it the first time, because it doesn't come from the App Store or
from a developer registered with Apple:

1. A message says "“PolymerData” Not Opened". Choose **Done**.
2. Open **System Settings**, choose **Privacy & Security**, and scroll down to
   "“PolymerData” was blocked to protect your Mac". Choose **Open Anyway**,
   then **Open Anyway** again, and enter your Mac's password.

   On macOS 14 (Sonoma) or older, Control-click PolymerData instead, choose
   **Open**, then **Open** again.
3. If macOS asks whether PolymerData may access files in your Downloads folder,
   choose **Allow**. PolymerData's own files are there.

macOS remembers your answer, so this happens only once. If PolymerData asks you
to choose the folder it came in, choose `polymerData-main`: the first time,
macOS can run it from a temporary copy that isn't next to its files.

### 3. Let it set itself up, once

PolymerData says it needs to set itself up first. Choose **Set Up**. A page
opens in your browser and ticks off each step. The first time takes 10–30
minutes, mostly downloading Claude Code, MinerU and MinerU's 2 GB of model
files.

It asks you two things along the way:

1. **Where to keep your data.** **Use This Folder** keeps it in a folder called
   `PolymerData Results` in your home folder. **Choose Another…** lets you pick
   one. More in [Where your data is kept](#where-your-data-is-kept).
2. **Your Claude login,** if Claude Code isn't logged in on this Mac yet. Choose
   **Log In**, and your browser opens a Claude page. Log in there with your
   Claude account, then go back to the setup page.

When it's done, the page says "PolymerData is set up" and the app opens in a
new browser tab. If the page says "Setup stopped" instead, it says why. Fix
that, then double-click PolymerData again: it carries on from where it stopped.

### 4. Get data out of a paper

1. Choose **Extract** in the menu.
2. **Choose PDF** and pick the paper.
3. Under **Features**, type the features you want, meaning the properties you
   want from the paper, separated by commas. For example:
   `Temperature (°C), Conductivity (S/cm)`. Put a unit in a feature's name to
   get its numbers in that unit. Without one, they come in whatever unit the
   paper uses.
4. Choose **Extract data**.

The page shows each step as it works. A paper takes about 5 minutes the first
time, most of it MinerU reading the PDF, and 30 seconds to 2 minutes after
that. The results come grouped by sample (each material the paper tests), one
row per data point. A sample has several rows when the paper gives a feature at
several conditions, such as its conductivity at several temperatures. An empty
cell means the paper doesn't give that value. **Download CSV** saves the results
as a spreadsheet file.

The other pages (Explore, Temperature, Correlations, Data, Features) show the
dataset and need nothing else. **Discover**, which finds papers likely to
report the data you want, works better with a free OpenAlex key: see
[Finding papers](#finding-papers-extractiondiscoverpy-issue-7).

### Each time you use it

Double-click **PolymerData**. A few seconds later the app opens in your browser
at http://localhost:5173. PolymerData has no window of its own: it runs in the
background, and it keeps running after you close the browser tab, until you
stop it.

To stop it, double-click PolymerData again and choose **Stop PolymerData**.
**Open** brings the app's page back instead. Restarting or shutting down the
Mac stops it too.

### What you'll notice

- **The app's address is `http://localhost:5173`.** Nothing answers at
  `http://127.0.0.1:5173`, even though both mean your own Mac.
- **If PolymerData isn't running,** Extract says "Couldn't reach the
  extraction server". The other pages don't notice. Double-click PolymerData
  to start it.
- **Results stay after a refresh.** Once an extraction starts, the page's
  address becomes `/extract?job=<id>`. Refreshing it, opening it again later,
  or coming back through the menu shows that extraction, running or finished.
  **New extraction** takes the address back to plain `/extract`. The address
  only works on the Mac that ran the extraction.
- **Download CSV** saves the results as `<PDF name>-extracted.csv`: a
  `sample` column, then one column per feature, one row per data point.
- **Extractions run one at a time.** One you start while another is running
  waits for it, and the page says so.
- **Stopping PolymerData loses any extraction still running;** finished ones
  are saved. When you start it again, the page says "The server lost this
  extraction". **Try again** starts it over, unless the page was reloaded
  since you chose the PDF. A reloaded page no longer has the file, so wherever
  starting over is the fix (this, or an extraction that failed), **Try again**
  isn't offered: choose the PDF again under **Change file or features**.

### Where your data is kept

Your data folder is the one you chose during setup: `PolymerData Results` in
your home folder, unless you chose another. It holds:

- `parsed/`: one folder per paper, with its text as MinerU read it
  (`content.md`) and its figures as images (`figures/`). The same PDF uploaded
  again, under any file name, reuses this instead of being read again.
- `extractions/`: one file per extraction, `<id>.json`, holding the results the
  page showed. `<id>` is the end of the page's address, `/extract?job=<id>`.

To move your data, stop PolymerData and move the folder. Then tell PolymerData
where it went. In `polymerData-main`, open the `extraction` folder and press
Cmd+Shift+. (period) to show hidden files. Open `.env` with TextEdit, find the
`DATA_DIR=` line, and change the location between its single quotes to the
folder's new location, for example
`DATA_DIR='/Users/yourname/Documents/PolymerData Results'`. Leave the quotes as
they are: TextEdit can turn quotes you type into curly ones, which PolymerData
doesn't read as quotes. If PolymerData can't find your earlier data, the app
starts empty: earlier extractions' addresses say "The server lost this
extraction", and papers are read again.

Two things are kept outside the data folder:
- **MinerU keeps its own copy** of every paper it has read, in the hidden
  `.mineru` folder in your home folder. That's why a paper it has seen before
  takes seconds to read, even with an empty data folder.
- **PolymerData's logs,** records of what it did, are in `extraction/logs/`
  and in the hidden `.runtime` folder, both inside `polymerData-main`.

### Updating to a newer version

1. Stop PolymerData: double-click it and choose **Stop PolymerData**.
2. Download the ZIP again and unzip it, as in [step 1](#1-download-it).
3. Double-click the new folder's PolymerData. macOS asks you to allow it again,
   as in [step 2](#2-open-polymerdata-the-first-time).
4. It sets itself up again, faster this time since most things are already
   installed. When it asks where to keep your data, choose the same folder as
   before, so the new version finds your earlier results.

Then you can delete the old folder.

### If something goes wrong

- **Extract says "Couldn't reach the extraction server".** PolymerData isn't
  running, or was stopped. Double-click PolymerData.
- **PolymerData says something is already using its web addresses.** It's
  running from another copy of its folder, such as an older download. Double-
  click that copy, choose **Stop PolymerData**, then open this one again.
- **An extraction fails with a message from Claude,** such as a usage limit.
  The page shows Claude's message. A usage limit resets after a few hours, so
  try again then.
- **PolymerData says it didn't start.** The end of `server.log` and `web.log`,
  in the hidden `.runtime` folder inside `polymerData-main`, says why.
- **Anything else:** `extraction/logs/extraction.log` records what the app was
  doing when it went wrong. Include its last lines when you
  [open an issue](https://github.com/merlinymy/polymerData/issues).

## Setting it up by hand

For developers, for Linux, and for running a step yourself when setup stops on
it. From a terminal in the repo root, `./setup.sh` does all of the steps below
(it's what PolymerData runs on a Mac), and `./start.sh` starts both programs and
opens the page, until Ctrl+C. Or run the steps one by one:

The frontend and the extraction server both run on your own computer, each in
its own terminal. Every page of the frontend except **Extract** works without
the server. Extract sends a paper's PDF to the extraction server
(`extraction/api.py`) and shows the data it sends back.

Run each command block below from the repo root, the folder this README is in.

### Once: install what they need

1. **Node.js**, the LTS (long-term support) version, from https://nodejs.org.
   The frontend needs it.
2. **Claude Code, logged in.** The extraction server uses it to have Claude read
   the paper. Run `curl -fsSL https://claude.ai/install.sh | bash`, then run
   `claude` once and log in. [Making an LLM call](#making-an-llm-call-utilclaudeapimockpy)
   explains why it goes through Claude Code instead of an API key.
3. **MinerU**, the tool that turns a PDF into text and figure images before
   Claude reads it. It runs on your computer and needs about 2 GB of model
   files. Install it with [uv](https://docs.astral.sh/uv/), a tool that
   installs Python programs, each with its own packages:

   ```sh
   uv tool install --python 3.10 "mineru>=4.0,<5"
   uv tool update-shell     # lets terminals find the mineru command
   ```

   **Then open a new terminal,** and run the rest there. uv puts `mineru` in
   `~/.local/bin`, and a terminal only learns that folder's commands when it
   opens. A terminal opened earlier can't find `mineru`, and neither can an
   extraction server started from it. Activating the extraction server's
   virtual environment (step 4) doesn't help, because `mineru` isn't in it. That server works on papers it parsed
   before, but on a new one the page says "The extraction failed" with the
   reason `[Errno 2] No such file or directory: 'mineru'`.

   ```sh
   mineru-kit models download --tier standard           # the model files, about 2 GB
   mineru config set parse_server.local.mode managed    # parse on this computer, not on MinerU's online service
   mineru server restart
   mineru server status --json
   ```

   MinerU is ready when the last command's `supported_tiers`, under
   `parse_server` → `local`, lists `"advanced"`. That's the parsing quality
   the extraction uses. Right after the restart the list can still be empty
   while MinerU loads its models, so run the command again a little later.
4. **The extraction server's Python packages,** in a virtual environment: a
   folder, `extraction/.venv/`, that holds this project's own copy of each
   package.

   ```sh
   cd extraction
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```
5. **The frontend's packages:**

   ```sh
   cd frontend
   npm install
   ```
6. **Where to keep the data,** if not in `extraction/output`: copy
   `extraction/.env.example` to `extraction/.env` and set `DATA_DIR=` in it.
   [Where your data is kept](#where-your-data-is-kept) explains the folder.

### Each time: start both

In one terminal, start the extraction server:

```sh
cd extraction
.venv/bin/python api.py      # listens on http://127.0.0.1:8000
```

In a second terminal, start the frontend:

```sh
cd frontend
npm run dev                  # prints http://localhost:5173
```

Then open http://localhost:5173 and choose **Extract** in the menu. Ctrl+C in a
terminal stops what's running there.

`./start.sh`, from the repo root, does both in one terminal and opens the page.

What you'll see on the page is under [What you'll notice](#what-youll-notice).
When you start them by hand:
- **Nothing answers at `http://127.0.0.1:5173`,** because the frontend's
  development server only listens on `localhost`.
- **Start the extraction server from a terminal opened after MinerU's install**
  (step 3), or it can't run `mineru`.
- **How long an extraction takes,** and what the server's answers look like, is
  under [Extraction API](#extraction-api-extractionapipy) below.

## Making an LLM call (`util/claudeAPIMock.py`)

`ask_llm()` sends a prompt to Claude and returns the reply. For now it doesn't
use a paid API. It runs Claude Code's non-interactive mode (`claude -p`) on your
machine with your Claude Code login, so calls count against your Claude Code
plan's usage limits and nothing is billed to an API key.

**Setup:**
1. Install Claude Code: `curl -fsSL https://claude.ai/install.sh | bash`.
2. Run `claude` once and log in.

`ask_llm()` needs only the `claude` command on your PATH and the Python standard
library.

```python
import json
from util.claudeAPIMock import ask_llm

# Text in, text out
reply = ask_llm("Summarise this abstract in two sentences: ...")

# A system prompt (instructions for the whole reply) and a chosen model
reply = ask_llm(question, system="You are a polymer chemist.", model="claude-opus-5-5")

# JSON out: json_schema describes the shape the reply must have,
# and the reply is that JSON as a string
schema = {"type": "object",
          "properties": {"polymer": {"type": "string"}, "salt": {"type": "string"}},
          "required": ["polymer", "salt"], "additionalProperties": False}
data = json.loads(ask_llm("Which polymer and salt does this paper study? ...", json_schema=schema))

# Images, each optionally with a label shown just before it, such as its caption
reply = ask_llm("How many curves does this plot show?",
                images=[("fig4.png", "Fig. 4. Arrhenius plots for amorphous PEO ...")])

# PDFs, which Claude reads page by page
reply = ask_llm("List the samples this paper reports.", documents=["paper.pdf"])
```

**Importing it:** code run from the repo root imports it as shown. Code run from
inside `extraction/` needs the repo root on its path: `PYTHONPATH=.. python your_script.py`.

**What you'll notice:**
- **Even a one-word reply takes 3–5 seconds,** because every call starts the
  `claude` program.
- **`ANTHROPIC_API_KEY` is removed on purpose** from what `claude` sees. With it
  set, `claude` would bill that key instead of your plan. `extraction/` loads the
  key from `.env`, so it is usually set.
- **Each call is isolated, the way an API call is:**
  - it has no tools, so it can't read files or run commands;
  - it doesn't load CLAUDE.md files;
  - it runs outside the repo.

  It still gets a few lines of Claude Code's own context: the date, your
  platform and your account's email.
- **Leaving out `model`** uses your Claude Code default model.
- **A failed call raises `RuntimeError`** with Claude Code's own message, for
  example `claude` not installed, usage limit reached, or unknown model.

**Switching to a real API later** (the Claude API, OpenAI, or a local model
server) means rewriting the body of `ask_llm()`. Code that calls it doesn't
change.

`extraction/extract_features.py` is built on it. Give it a paper's PDF and a
text file with one feature name per line, and it writes a table with one row
per data point. The first column names the sample (one material the paper
tests) and the other columns hold the features. A sample gets several rows when
the paper gives a feature at several conditions, such as its conductivity at
several temperatures. Run `python extract_features.py paper.pdf features.txt -o out.csv`
from `extraction/`.

## Extraction API (`extraction/api.py`)

A small web server that lets the frontend use `extract_features.py`. The page
sends a PDF and the feature names, and gets the data back grouped by sample.

**Start it** with `.venv/bin/python api.py` from `extraction/`, after the
one-time setup in [Getting started](#getting-started) or
[Setting it up by hand](#setting-it-up-by-hand).

- It listens on http://127.0.0.1:8000, which only this computer can reach. To
  let other computers on the network reach it, run
  `.venv/bin/uvicorn api:app --host 0.0.0.0 --port 8000` instead.
- http://127.0.0.1:8000/docs lists the endpoints and has a form for trying each
  one.

**An extraction runs as a job, because it takes minutes.** The page starts the
job, then keeps asking whether it has finished.

1. `POST /extract` with a form (the format a browser uses to send a file) that
   has two fields:
   - `pdf`: the paper's PDF.
   - `features`: the feature names, separated by commas, for example
     `Temperature (°C), Conductivity (S/cm)`.

   It answers at once with `202` and the job's id: `{"job": "07561dd6..."}`.
2. `GET /extract/<job id>` answers with one of:
   - `{"status": "running"}`: not finished yet, so ask again in about 5 seconds.
   - `{"status": "failed", "error": "..."}`, with the reason.
   - `{"status": "done", "samples": {...}}`, with the data.

   Each answer also has `file`, the PDF's file name as uploaded; `features`,
   the feature names as the server split them; and `started`, when the job
   started, in seconds since 1970 (Unix time). A page opened later at a job's
   address learns them from here, since it no longer has the PDF.

From the frontend:

```js
const form = new FormData();
form.append("pdf", file);               // the File from an <input type="file">
form.append("features", featuresText);  // the text box, as typed
const res = await fetch("http://127.0.0.1:8000/extract", { method: "POST", body: form });
if (!res.ok) throw new Error((await res.json()).detail);  // not a PDF, or no feature names
const { job } = await res.json();

let result;
do {
  await new Promise((resolve) => setTimeout(resolve, 5000));
  result = await (await fetch(`http://127.0.0.1:8000/extract/${job}`)).json();
} while (result.status === "running");
```

From a terminal:

```sh
curl -F pdf=@papers/bdf71b01-linden1988.pdf -F "features=Temperature (°C), Conductivity (S/cm)" http://127.0.0.1:8000/extract
curl http://127.0.0.1:8000/extract/<job id>
```

That paper's answer, shortened (it gave 6 samples with 7 temperatures each):

```json
{
  "status": "done",
  "file": "bdf71b01-linden1988.pdf",
  "features": ["Temperature (°C)", "Conductivity (S/cm)"],
  "started": 1790000000.0,
  "samples": {
    "Amorphous PEO (undoped)": [
      {"Temperature (°C)": 20, "Conductivity (S/cm)": 1e-07},
      {"Temperature (°C)": 25, "Conductivity (S/cm)": 2.82e-07}
    ],
    "Amorphous PEO:LiClO4 - 64:1": [
      {"Temperature (°C)": 20, "Conductivity (S/cm)": 1.78e-07},
      {"Temperature (°C)": 25, "Conductivity (S/cm)": 5.62e-07}
    ]
  }
}
```

- **Each key under `samples` is a sample's name** as the paper gives it, or its
  composition when the paper doesn't name it. Its list has one entry per data
  point.
- **Every data point has every feature,** in the order they were typed. `null`
  means the paper doesn't give that value for that data point.

**What you'll notice:**
- **A PDF the server has seen before takes from about 30 seconds to 2 minutes,**
  which is the Claude call alone. A new PDF adds about 4 minutes while MinerU
  parses it. The parse is kept, so the same PDF uploaded again, under any file
  name, skips that step.
- **Jobs run one at a time, in the order they came in.** `running` also covers
  waiting for earlier jobs, so a job can stay `running` longer than the times
  above.
- **Every finished job is saved** to `extractions/<job id>.json` in the
  [data folder](#where-your-data-is-kept), holding the same answer
  `GET /extract/<job id>` gives, so its id keeps working after a restart.
  Failed jobs are saved too, with their reason. The files stay on the computer
  running the server: the default data folder, `extraction/output/`, isn't in git.
- **A job still running when the server stops is lost.** Its id answers `404`
  after the restart, and so does an id the server never made.
- **Commas separate the feature names,** so a name can't contain a comma.
  Spaces around each name are dropped.
- **The server answers `400`,** with the reason in `detail`, when the file isn't
  a PDF or no feature names are left.
- **Only pages opened from a localhost address can read the answers,** meaning
  `http://localhost:<port>` or `http://127.0.0.1:<port>`. That covers the Vite
  dev server on any computer. A browser hides a server's answers from pages at
  other addresses unless the server allows them (the browser rule called CORS),
  and this server allows only those.

## Finding papers (`extraction/discover.py`, issue #7)

`discover.py` finds papers likely to report the data you want, to feed
`extract_features.py`. Give it keywords, and optionally papers you already have
(DOI or title) and feature names. It searches [OpenAlex](https://openalex.org),
has Claude judge each paper from its title, journal, year and abstract, and
follows the references and citing papers of the ones judged likely. A search
takes 5 minutes and returns the papers best first.

```sh
python discover.py "solid polymer electrolyte ionic conductivity" --feature Tg -o found.json
```

**It needs an OpenAlex key.** OpenAlex charges each request against a daily
budget. Without a key, everyone on your network's IP address shares 1,000
credits a day, less than one search. A free key (make an account, then
https://openalex.org/settings/api) gives 10,000, about 10 searches. Put it in
`extraction/.env` as `OPENALEX_API_KEY=...`.

The extraction API serves it too, for the Discover page:

1. `POST /discover` with JSON `{"keywords": "...", "seeds": ["10.1021/...", "a title"], "features": ["Tg"]}`.
   `seeds` and `features` may be left out. It answers `202` and `{"job": "..."}`,
   or `400` when the keywords are blank or there are more than 20 seeds.
2. `GET /discover/<job id>` answers `{"status": "running", "progress": {"candidates", "judged", "likely", "seconds", "credits"}}`
   (`progress` is `null` at first), then `{"status": "done", "papers": [...]}` or
   `{"status": "failed", "error": "..."}`. Each paper has `title`, `authors`,
   `year`, `journal`, `doi`, `pdf` (an open-access PDF, or `null`), `score`
   (2 probably reports the data, 3 clearly), `reason`, `description` (from the
   abstract, or `null`) and `openalex`.

**What you'll notice:**
- **Most papers have no description.** OpenAlex has no abstracts for most
  Elsevier papers, which is most of this field, and Semantic Scholar and
  Crossref had none it lacked. Those papers are judged from their title alone.
- **Few have an open-access PDF,** so you usually get the PDF yourself before
  extracting.
- **The list is long,** often thousands of papers. Measured on the 63 papers
  behind the golden dataset, a keywords-only search listed 75% of them, but only
  11 in its top 100 (`extraction/experiments/discovery/`).
- **Searches run one at a time,** apart from extractions.
