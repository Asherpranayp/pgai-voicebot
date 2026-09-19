# Pretty Good AI — Voice Bot Tester

An automated "patient" that calls Pretty Good AI's demo clinic line (Pivot Point
Orthopedics), holds a natural voice conversation with their AI phone agent across a
range of scenarios, records/transcribes the call, and flags quality issues.

Built with **LiveKit Agents in pipeline mode** (separate STT -> LLM -> TTS stages,
no realtime/speech-to-speech model), per the assessment's stack requirement. See
`ARCHITECTURE.md` for how it works and why it's built this way.

## Setup

Requirements: Python 3.10+, `ffmpeg` on your PATH (for mixing the call recording),
a [LiveKit Cloud](https://cloud.livekit.io) project, a Twilio account with a
Voice-capable number, and an OpenAI API key.

```bash
git clone <this-repo>
cd pgai-voicebot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env — see the two setup steps below for where each value comes from
```

### 1. Twilio Elastic SIP Trunk

LiveKit dials out through a SIP trunk backed by your existing Twilio number:

1. In the Twilio console, go to **Elastic SIP Trunking -> Trunks** and create a trunk.
2. Under **Termination**, set a Termination SIP URI (e.g. `your-name.pstn.twilio.com`)
   — this is `SIP_TRUNK_ADDRESS`.
3. Under **Authentication**, create a **Credential List** with a username/password —
   these are `SIP_TRUNK_USERNAME` / `SIP_TRUNK_PASSWORD`. Twilio never shows a saved
   password again, so note it down immediately.
4. Under **Numbers**, add the Twilio number you're calling from — that's
   `SIP_TRUNK_FROM_NUMBER` (E.164 format, e.g. `+19205515133`).

### 2. LiveKit Cloud project + outbound trunk

1. Create a project at [cloud.livekit.io](https://cloud.livekit.io) and copy
   `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` from **Settings -> Keys**.
2. Fill in `.env` with the LiveKit values plus the four `SIP_TRUNK_*` Twilio values
   from step 1, then run:

```bash
python -m app.create_sip_trunk
```

This prints a trunk id (`ST_xxxxxxxxxxxx`) — copy it into `.env` as `SIP_TRUNK_ID`.
It's a one-time step; only re-run it if you want to recreate the trunk from scratch.

## Running a call

Start the agent worker once (it stays running and waits for dispatched jobs), then
dispatch calls against it:

**Terminal 1** — start the worker (leave this running):

```bash
python -m app.agent start
```

**Terminal 2** — dispatch a call for a given scenario:

```bash
python -m app.dispatch_call --list          # see all scenario ids
python -m app.dispatch_call simple_scheduling
```

The bot places the call, holds the conversation, and once it ends (or after a 4
minute safety cap) you'll find:

- `recordings/<room_name>.mp3` — the full call audio, both sides mixed down
- `transcripts/<room_name>.txt` / `.json` — a timestamped transcript of both sides

Calls run 1-3 minutes each — watch Terminal 1's logs and wait for one to finish
before dispatching the next.

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
  config.py             env var loading
  scenarios.py          the patient personas / test scenarios
  agent.py              LiveKit Agents worker: STT -> LLM -> TTS pipeline, SIP dial-out,
                         transcript capture, dual-track recording + mixdown
  create_sip_trunk.py   one-time script: creates the LiveKit outbound SIP trunk
  dispatch_call.py      CLI to dispatch one outbound call to the running worker
  transcript_store.py   accumulates + saves a call's transcript
bug_analysis/
  analyze.py             offline LLM pass over transcripts -> bug_report.md
recordings/              call audio (.mp3), one per call
transcripts/             call transcripts (.txt + .json), one per call
bug_report/              bug_report.md
```

## Environment variables

See `.env.example` for the full list with comments. Nothing in `.env` is committed
(it's gitignored) — `.env.example` documents what's required without real secrets.
