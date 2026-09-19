"""
LiveKit Agents worker, running in PIPELINE MODE: separate speech-to-text, LLM,
and text-to-speech stages (no realtime/speech-to-speech model), per the
assessment's hard stack requirement. See ARCHITECTURE.md for the full
reasoning behind each choice below.

Flow for one call:
  1. dispatch_call.py creates a LiveKit room and explicitly dispatches a job
     for this worker, passing the scenario id as job metadata.
  2. This entrypoint joins that room, starts an AgentSession (STT -> LLM ->
     TTS, with VAD-based turn detection), and creates a SIP participant that
     dials the real phone number through our LiveKit outbound SIP trunk
     (which is itself backed by a Twilio Elastic SIP Trunk).
  3. Once Pretty Good AI's agent answers, LiveKit bridges its audio into the
     room as a normal participant. From here on this is just a 2-party
     LiveKit room: our AI "patient" (this agent) and their AI "agent" (the
     SIP participant).
  4. Both sides of the conversation are captured as they happen: STT results
     for the SIP participant's speech become "agent" transcript turns, and
     our own LLM replies become "patient" transcript turns. Raw audio for
     both participants is tapped directly from their LiveKit tracks and
     written to WAV, then mixed down to a single MP3 once the call ends.
"""
import asyncio
import logging
import time
import wave
from pathlib import Path

from livekit import agents, api, rtc
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli
from livekit.plugins import openai, silero

from app.config import (
    AGENT_NAME,
    LIVEKIT_API_KEY,
    LIVEKIT_API_SECRET,
    LIVEKIT_URL,
    OPENAI_LLM_MODEL,
    OPENAI_STT_MODEL,
    OPENAI_TTS_MODEL,
    OPENAI_TTS_VOICE,
    SIP_TRUNK_ID,
    TARGET_NUMBER,
)
from app.scenarios import get_scenario
from app.transcript_store import CallTranscript

log = logging.getLogger("agent")

RECORDINGS_DIR = Path(__file__).resolve().parent.parent / "recordings"
RECORDINGS_DIR.mkdir(exist_ok=True)


async def _record_track_to_wav(track: rtc.Track, out_path: Path, stop_event: asyncio.Event):
    """Tap raw PCM frames off a track (local or remote) and write them to a
    mono WAV file until stop_event is set. Used for both the SIP
    participant's incoming audio and our own agent's synthesized speech, so
    the final call recording has both sides."""
    stream = rtc.AudioStream(track)
    wav_file = None
    try:
        async for event in stream:
            frame = event.frame
            if wav_file is None:
                wav_file = wave.open(str(out_path), "wb")
                wav_file.setnchannels(frame.num_channels)
                wav_file.setsampwidth(2)  # 16-bit PCM
                wav_file.setframerate(frame.sample_rate)
            wav_file.writeframes(frame.data.tobytes())
            if stop_event.is_set():
                break
    except Exception:
        log.exception("Error recording track to %s", out_path)
    finally:
        if wav_file is not None:
            wav_file.close()
        await stream.aclose()


async def entrypoint(ctx: JobContext):
    await ctx.connect()

    scenario_id = (ctx.job.metadata or "simple_scheduling").strip() or "simple_scheduling"
    scenario = get_scenario(scenario_id)
    call_id = ctx.room.name
    transcript = CallTranscript(call_id=call_id, scenario_id=scenario_id)
    log.info("Job started: room=%s scenario=%s", call_id, scenario_id)

    stop_recording = asyncio.Event()
    recording_tasks: list[asyncio.Task] = []
    agent_wav = RECORDINGS_DIR / f"{call_id}_agent.wav"
    patient_wav = RECORDINGS_DIR / f"{call_id}_patient.wav"

    @ctx.room.on("track_subscribed")
    def on_track_subscribed(track: rtc.Track, publication, participant: rtc.RemoteParticipant):
        # The SIP participant (Pretty Good AI's phone agent) publishes an
        # audio track once the call connects; record it as the "agent" side.
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            recording_tasks.append(
                asyncio.create_task(_record_track_to_wav(track, agent_wav, stop_recording))
            )

    @ctx.room.local_participant.on("local_track_published")
    def on_local_track_published(publication, track: rtc.Track):
        # Our own TTS output track ("patient" side of the call).
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            recording_tasks.append(
                asyncio.create_task(_record_track_to_wav(track, patient_wav, stop_recording))
            )

    session = AgentSession(
        stt=openai.STT(model=OPENAI_STT_MODEL),
        llm=openai.LLM(model=OPENAI_LLM_MODEL),
        tts=openai.TTS(model=OPENAI_TTS_MODEL, voice=OPENAI_TTS_VOICE),
        vad=silero.VAD.load(),
    )

    @session.on("conversation_item_added")
    def on_conversation_item_added(event):
        item = event.item
        text = (getattr(item, "text_content", None) or "").strip()
        if not text:
            return
        # "user" = the other party's speech as heard by our STT (Pretty Good
        # AI's agent). "assistant" = our own LLM's generated patient replies.
        role = "agent" if item.role == "user" else "patient"
        transcript.add(role, text)

    agent = Agent(instructions=scenario.system_prompt)
    await session.start(agent=agent, room=ctx.room)

    # Dial the real phone number into this room via our LiveKit outbound SIP
    # trunk (itself backed by the Twilio Elastic SIP Trunk configured for
    # this project). This is the actual "place the call" step.
    lkapi = api.LiveKitAPI(url=LIVEKIT_URL, api_key=LIVEKIT_API_KEY, api_secret=LIVEKIT_API_SECRET)
    try:
        await lkapi.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                sip_trunk_id=SIP_TRUNK_ID,
                sip_call_to=TARGET_NUMBER,
                room_name=ctx.room.name,
                participant_identity="pivot-point-agent",
                participant_name="Pivot Point Orthopedics Agent",
                wait_until_answered=True,
            )
        )
        log.info("SIP call answered for room %s", ctx.room.name)
    except Exception:
        log.exception("Failed to place SIP call for room %s", ctx.room.name)
        await lkapi.aclose()
        transcript.save()
        return
    finally:
        await lkapi.aclose()

    # Let the scenario play out naturally; the patient persona in
    # scenarios.py is instructed to close the call itself once its goal is
    # resolved. As a safety net, cap any single call at 4 minutes.
    started = time.time()
    while time.time() - started < 240:
        if ctx.room.connection_state != rtc.ConnectionState.CONN_CONNECTED:
            break
        await asyncio.sleep(1)

    stop_recording.set()
    for t in recording_tasks:
        try:
            await asyncio.wait_for(t, timeout=5)
        except Exception:
            pass

    json_path, txt_path = transcript.save()
    log.info("Transcript saved: %s", txt_path)

    # Mix the two mono WAVs (agent + patient) down to a single MP3 so the
    # deliverable is one file per call with both sides, per the assignment.
    if agent_wav.exists() and patient_wav.exists():
        out_mp3 = RECORDINGS_DIR / f"{call_id}.mp3"
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-i", str(agent_wav), "-i", str(patient_wav),
            "-filter_complex", "amix=inputs=2:duration=longest:normalize=0",
            "-c:a", "libmp3lame", "-q:a", "4",
            str(out_mp3),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        if out_mp3.exists():
            agent_wav.unlink(missing_ok=True)
            patient_wav.unlink(missing_ok=True)
            log.info("Recording saved: %s", out_mp3)
        else:
            log.error("ffmpeg mixdown failed, keeping raw WAVs for room %s", call_id)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, agent_name=AGENT_NAME))
