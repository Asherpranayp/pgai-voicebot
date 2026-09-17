"""
The core of the bot: bridges audio between a live Twilio phone call (Media
Streams, mu-law 8kHz) and OpenAI's Realtime API, which both generates the
simulated patient's speech AND transcribes the agent's speech.

Why this shape, in short (see ARCHITECTURE.md for the full reasoning):
- Twilio's Media Streams protocol sends/receives base64-encoded mu-law audio
  over a plain WebSocket. OpenAI Realtime supports mu-law natively
  (`audio/pcmu`, the GA name for G.711 mu-law), so audio is relayed
  byte-for-byte with zero transcoding.
- The agent's speech is treated as the Realtime session's "user" input; the
  model's spoken replies (our simulated patient) are the "assistant" output.
  Server-side voice activity detection (VAD) decides when a turn ends and
  triggers a response automatically, which is what gives natural turn-taking
  and lets the caller be interrupted (barge-in) like a real phone call.
- Both sides of the conversation are transcribed as they happen
  (Whisper for the agent's audio, the Realtime model's own transcript for its
  own speech) and written out incrementally to a CallTranscript.

NOTE on API version: OpenAI's Realtime API went GA in 2026 and the old beta
websocket shape (the `OpenAI-Beta: realtime=v1` header, top-level
`input_audio_format`/`voice`/`turn_detection` fields, and events like
`response.audio.delta`) was retired. This module targets the GA shape:
audio config nested under `session.audio.input` / `session.audio.output`,
and renamed events (`response.output_audio.delta`, etc). Any server event
type we don't explicitly recognize is logged rather than silently ignored,
so if OpenAI renames something else later this module fails loudly in the
logs instead of just going silent.
"""
import asyncio
import base64
import json
import logging

import websockets
from fastapi import WebSocket, WebSocketDisconnect

from app.config import OPENAI_API_KEY, OPENAI_REALTIME_MODEL, OPENAI_VOICE
from app.scenarios import get_scenario
from app.transcript_store import CallTranscript

log = logging.getLogger("realtime_bridge")

OPENAI_WS_URL = f"wss://api.openai.com/v1/realtime?model={OPENAI_REALTIME_MODEL}"

# Server event types we actively handle. Anything else that arrives gets
# logged at INFO so a future API change shows up in the logs immediately
# instead of silently doing nothing.
_HANDLED_EVENTS = {
    "response.output_audio.delta",
    "response.output_audio_transcript.delta",
    "response.output_audio_transcript.done",
    "conversation.item.input_audio_transcription.completed",
    "conversation.item.input_audio_transcription.delta",
    "input_audio_buffer.speech_started",
    "input_audio_buffer.speech_stopped",
    "input_audio_buffer.committed",
    "session.created",
    "session.updated",
    "response.created",
    "response.done",
    "error",
}


async def run_bridge(twilio_ws: WebSocket):
    await twilio_ws.accept()

    stream_sid = None
    call_sid = None
    scenario_id = "simple_scheduling"
    transcript: CallTranscript | None = None

    # The scenario is passed as a <Parameter> inside TwiML's <Stream> element
    # (not a URL query string — Twilio doesn't forward that through to the
    # WebSocket connection itself, see server.py's /twiml route), so it only
    # becomes available once Twilio's "start" event arrives. Since the
    # scenario drives the OpenAI session's system prompt, we have to consume
    # messages here until we see "start" before we can even open the OpenAI
    # connection.
    first_media_msg = None
    try:
        async for raw in twilio_ws.iter_text():
            msg = json.loads(raw)
            if msg.get("event") == "start":
                stream_sid = msg["start"]["streamSid"]
                call_sid = msg["start"]["callSid"]
                scenario_id = msg["start"].get("customParameters", {}).get("scenario", "simple_scheduling")
                break
            elif msg.get("event") == "media":
                # Shouldn't normally arrive before "start", but don't drop it if it does.
                first_media_msg = msg
                break
    except WebSocketDisconnect:
        log.info("Twilio websocket disconnected before call started")
        return

    scenario = get_scenario(scenario_id)
    transcript = CallTranscript(call_id=call_sid, scenario_id=scenario_id)
    log.info("Call started: %s (scenario=%s)", call_sid, scenario_id)

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
    }

    async with websockets.connect(OPENAI_WS_URL, additional_headers=headers, max_size=None) as openai_ws:
        await openai_ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "type": "realtime",
                "instructions": scenario.system_prompt,
                "audio": {
                    "input": {
                        # NOTE: as of the GA API, "format" is an object, not a bare
                        # string (the docs/examples are inconsistent on this, but the
                        # API itself rejects a string with `invalid_type`). pcmu/G.711
                        # mu-law is a fixed-rate 8kHz codec so no "rate" field is given
                        # here — Twilio's Media Streams audio already is mu-law 8kHz.
                        "format": {"type": "audio/pcmu"},
                        "transcription": {"model": "whisper-1"},
                        "turn_detection": {
                            "type": "server_vad",
                            "threshold": 0.5,
                            "prefix_padding_ms": 300,
                            "silence_duration_ms": 500,
                        },
                    },
                    "output": {
                        "format": {"type": "audio/pcmu"},
                        "voice": OPENAI_VOICE,
                    },
                },
            },
        }))

        async def twilio_to_openai():
            try:
                # Replay the one message (if any) we had to peek at above,
                # before the "start"/"media" event loop proper begins.
                if first_media_msg is not None:
                    await openai_ws.send(json.dumps({
                        "type": "input_audio_buffer.append",
                        "audio": first_media_msg["media"]["payload"],
                    }))

                async for raw in twilio_ws.iter_text():
                    msg = json.loads(raw)
                    event = msg.get("event")

                    if event == "media":
                        await openai_ws.send(json.dumps({
                            "type": "input_audio_buffer.append",
                            "audio": msg["media"]["payload"],
                        }))

                    elif event == "stop":
                        log.info("Call stopped: %s", call_sid)
                        break
            except WebSocketDisconnect:
                log.info("Twilio websocket disconnected")
            finally:
                # Signal the other loop to stop too.
                try:
                    await openai_ws.close()
                except Exception:
                    pass

        async def openai_to_twilio():
            nonlocal transcript
            agent_partial = ""
            patient_partial = ""
            try:
                async for raw in openai_ws:
                    event = json.loads(raw)
                    etype = event.get("type")

                    if etype == "response.output_audio.delta" and stream_sid:
                        await twilio_ws.send_text(json.dumps({
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {"payload": event["delta"]},
                        }))

                    elif etype == "response.output_audio_transcript.delta":
                        patient_partial += event.get("delta", "")

                    elif etype == "response.output_audio_transcript.done":
                        if transcript and patient_partial.strip():
                            transcript.add("patient", patient_partial)
                        patient_partial = ""

                    elif etype == "conversation.item.input_audio_transcription.completed":
                        text = event.get("transcript", "")
                        if transcript:
                            transcript.add("agent", text)

                    elif etype == "input_audio_buffer.speech_started":
                        # Agent (or background noise) started talking — if our patient
                        # persona is mid-sentence, cut its audio so Twilio stops playing
                        # it immediately. This is what makes barge-in / interruption work.
                        await twilio_ws.send_text(json.dumps({
                            "event": "clear",
                            "streamSid": stream_sid,
                        }))

                    elif etype == "error":
                        log.error("OpenAI Realtime error: %s", event)

                    elif etype not in _HANDLED_EVENTS:
                        # Not fatal — just something we don't act on. Logged so an API
                        # change (renamed/new event) is visible instead of silent.
                        log.info("Unhandled OpenAI event type: %s", etype)

            except websockets.exceptions.ConnectionClosed as e:
                log.info("OpenAI websocket closed: %s", e)
            except Exception:
                log.exception("Error in openai_to_twilio loop")
            finally:
                if transcript:
                    json_path, txt_path = transcript.save()
                    log.info("Transcript saved: %s", txt_path)

        await asyncio.gather(twilio_to_openai(), openai_to_twilio())
