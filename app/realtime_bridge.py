"""
The core of the bot: bridges audio between a live Twilio phone call (Media
Streams, mu-law 8kHz) and OpenAI's Realtime API, which both generates the
simulated patient's speech AND transcribes the agent's speech.

Why this shape, in short (see ARCHITECTURE.md for the full reasoning):
- Twilio's Media Streams protocol sends/receives base64-encoded mu-law audio
  over a plain WebSocket. OpenAI Realtime supports mu-law natively
  (`g711_ulaw`), so audio is relayed byte-for-byte with zero transcoding.
- The agent's speech is treated as the Realtime session's "user" input; the
  model's spoken replies (our simulated patient) are the "assistant" output.
  Server-side voice activity detection (VAD) decides when a turn ends and
  triggers a response automatically, which is what gives natural turn-taking
  and lets the caller be interrupted (barge-in) like a real phone call.
- Both sides of the conversation are transcribed as they happen
  (Whisper for the agent's audio, the Realtime model's own transcript for its
  own speech) and written out incrementally to a CallTranscript.
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


async def run_bridge(twilio_ws: WebSocket, scenario_id: str):
    scenario = get_scenario(scenario_id)

    await twilio_ws.accept()

    stream_sid = None
    call_sid = None
    transcript: CallTranscript | None = None

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "OpenAI-Beta": "realtime=v1",
    }

    async with websockets.connect(OPENAI_WS_URL, additional_headers=headers, max_size=None) as openai_ws:
        await openai_ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "modalities": ["audio", "text"],
                "instructions": scenario.system_prompt,
                "voice": OPENAI_VOICE,
                "input_audio_format": "g711_ulaw",
                "output_audio_format": "g711_ulaw",
                "input_audio_transcription": {"model": "whisper-1"},
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 500,
                },
            },
        }))

        async def twilio_to_openai():
            nonlocal stream_sid, call_sid, transcript
            try:
                async for raw in twilio_ws.iter_text():
                    msg = json.loads(raw)
                    event = msg.get("event")

                    if event == "start":
                        stream_sid = msg["start"]["streamSid"]
                        call_sid = msg["start"]["callSid"]
                        transcript = CallTranscript(call_id=call_sid, scenario_id=scenario_id)
                        log.info("Call started: %s (scenario=%s)", call_sid, scenario_id)

                    elif event == "media":
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

                    if etype == "response.audio.delta" and stream_sid:
                        await twilio_ws.send_text(json.dumps({
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {"payload": event["delta"]},
                        }))

                    elif etype == "response.audio_transcript.delta":
                        patient_partial += event.get("delta", "")

                    elif etype == "response.audio_transcript.done":
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

            except websockets.exceptions.ConnectionClosed:
                log.info("OpenAI websocket closed")
            finally:
                if transcript:
                    json_path, txt_path = transcript.save()
                    log.info("Transcript saved: %s", txt_path)

        await asyncio.gather(twilio_to_openai(), openai_to_twilio())
