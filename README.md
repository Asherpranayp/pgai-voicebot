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
Voice-capable number, an OpenAI API key, and (recommended) a Deepgram API key for
low-latency streaming speech-to-text and text-to-speech. Without the Deepgram key the
bot falls back to OpenAI Whisper and tts-1, which works but adds about a second per reply.

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

## Running calls (one command)

```bash
python -m app.run_calls                                  # every scenario, one after another
python -m app.run_calls simple_scheduling insurance_question   # or just the ones you name
```

This starts the agent worker, places each call, waits for it to finish and for its files to
be saved, then stops the worker. For each call you get:

- `recordings/<call>.mp3`: both sides of the call, mixed into one file
- `transcripts/<call>.txt` / `.json`: a timestamped transcript of both sides
- `transcripts/<call>.latency.json`: our bot's per-turn response latency

`python -m app.dispatch_call --list` lists the scenario ids. To run the worker and
dispatch calls separately instead, use `python -m app.agent start` in one terminal and
`python -m app.dispatch_call <scenario>` in another.

I ran all the calls from a Google Colab notebook, with Colab Secrets in place of `.env`,
using the same modules cell by cell. Nothing in the code depends on Colab.

## Generating the bug report

After you've run some calls:

```bash
python -m bug_analysis.analyze
```

This reads every transcript in `transcripts/`, runs an LLM pass looking for concrete
issues and writes a first draft to `bug_report/auto_draft.md`. The final
`bug_report/bug_report.md` is hand-written from that draft after checking each finding
against the recordings (LLM review isn't deterministic and can't hear the audio).

## Project layout

```
app/
  config.py             env var loading
  scenarios.py          the patient personas / test scenarios
  agent.py              LiveKit Agents worker: STT -> LLM -> TTS pipeline, SIP dial-out,
                         transcript capture, dual-track recording + mixdown
  create_sip_trunk.py   one-time script: creates the LiveKit outbound SIP trunk
  dispatch_call.py      CLI to dispatch one outbound call to the running worker
  run_calls.py          one command: start worker, run scenarios in sequence, stop worker
  transcript_store.py   accumulates + saves a call's transcript
bug_analysis/
  analyze.py             offline LLM pass over transcripts -> auto_draft.md
recordings/              call audio (.mp3), one per call
transcripts/             call transcripts (.txt + .json), one per call
bug_report/              bug_report.md (final, hand-verified)
```

## Environment variables

See `.env.example` for the full list with comments. Nothing in `.env` is committed
(it's gitignored) — `.env.example` documents what's required without real secrets.
