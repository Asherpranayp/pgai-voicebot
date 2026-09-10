# Pretty Good AI — Voice Bot Tester

An automated "patient" that calls Pretty Good AI's demo clinic line (Pivot Point
Orthopedics), holds a natural voice conversation with their AI phone agent across a
range of scenarios, records/transcribes the call, and flags quality issues.

See `ARCHITECTURE.md` for how it works and why it's built this way.

## Setup

Requirements: Python 3.10+, a Twilio account with a Voice-capable number, an OpenAI
account with Realtime API access, and [ngrok](https://ngrok.com) (or any tool that
gives you a public HTTPS URL tunneling to your machine).

```bash
git clone <this-repo>
cd pgai-voicebot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: fill in TWILIO_*, OPENAI_API_KEY, and PUBLIC_BASE_URL (see below)
```

### Getting a public URL for Twilio

Twilio needs to reach your machine to open the media stream. In one terminal:

```bash
ngrok http 8000
```

Copy the `https://xxxx.ngrok-free.app` URL it prints into `PUBLIC_BASE_URL` in `.env`.
(Free ngrok URLs change every restart — update `.env` again if you restart ngrok.)

## Running a call

One command starts the server; a second places a call.

**Terminal 1** — start the bridge server (leave this running):

```bash
python -m uvicorn app.server:app --port 8000
```

**Terminal 2** — place a call for a given scenario:

```bash
python -m app.place_call --list          # see all scenario ids
python -m app.place_call simple_scheduling
```

The bot places the call, holds the conversation, and once it ends you'll find:

- `recordings/<CallSid>.mp3` — the full call audio
- `transcripts/<CallSid>.txt` / `.json` — a timestamped transcript of both sides

To run all scenarios back-to-back (waiting for each call to finish before starting
the next isn't automated — Twilio calls take 1-3 minutes each and you'll want to
listen/verify as you go), just call `place_call.py` again with the next scenario id
once a call completes.

## Generating the bug report

After you've run some calls:

```bash
python -m bug_analysis.analyze
```

This reads every transcript in `transcripts/`, runs an LLM pass looking for concrete
issues (wrong information, unhandled edge cases, ignored requests, etc.), and writes
`bug_report/bug_report.md`. Treat this as a first draft — skim it against the actual
transcripts/recordings and add anything the automated pass missed or drop anything
that's a nitpick, since the challenge explicitly favors a few well-described real bugs
over a long list of noise.

## Project layout

```
app/
  config.py           env var loading
  scenarios.py         the patient personas / test scenarios
  server.py             FastAPI app Twilio talks to (TwiML + media stream + callbacks)
  realtime_bridge.py   audio bridge between Twilio and OpenAI Realtime
  transcript_store.py  accumulates + saves a call's transcript
  place_call.py        CLI to place one outbound call
bug_analysis/
  analyze.py            offline LLM pass over transcripts -> bug_report.md
recordings/             call audio (.mp3), one per call
transcripts/            call transcripts (.txt + .json), one per call
bug_report/             bug_report.md
```

## Environment variables

See `.env.example` for the full list with comments. Nothing in `.env` is committed
(it's gitignored) — `.env.example` documents what's required without real secrets.
