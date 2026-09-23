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
import inspect
import json
import os
import logging
import time
import wave
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

from livekit import agents, api, rtc
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli
from livekit.plugins import openai, silero

from app.config import (
    AGENT_NAME,
    DEEPGRAM_API_KEY,
    LIVEKIT_API_KEY,
    LIVEKIT_API_SECRET,
    LIVEKIT_URL,
    OPENAI_LLM_MODEL,
    OPENAI_STT_MODEL,
    OPENAI_TTS_MODEL,
    OPENAI_TTS_VOICE,
    PATIENT_NAME,
    SIP_TRUNK_ID,
    TARGET_NUMBER,
)
from app.scenarios import get_scenario
from app.transcript_store import CallTranscript

log = logging.getLogger("agent")

RECORDINGS_DIR = Path(__file__).resolve().parent.parent / "recordings"
RECORDINGS_DIR.mkdir(exist_ok=True)


async def _record_track_to_wav(track: rtc.Track, out_path: Path, stop_event: asyncio.Event, t0: float):
    """Tap raw PCM frames off a track and write them to a mono WAV file until
    stop_event is set. Silence is inserted whenever frames arrive later than
    real time (e.g. our TTS track only carries audio while the bot speaks),
    so both WAVs stay on the same timeline starting at t0 and line up when
    mixed into one MP3."""
    stream = rtc.AudioStream(track, sample_rate=24000, num_channels=1)
    wav_file = None
    written = 0  # samples written so far
    try:
        async for event in stream:
            frame = event.frame
            if wav_file is None:
                wav_file = wave.open(str(out_path), "wb")
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)  # 16-bit PCM
                wav_file.setframerate(frame.sample_rate)
            expected = int((time.time() - t0) * frame.sample_rate) - frame.samples_per_channel
            gap = expected - written
            if gap > frame.sample_rate // 10:  # more than 100 ms behind: pad with silence
                wav_file.writeframes(b"\x00\x00" * gap)
                written += gap
            wav_file.writeframes(frame.data.tobytes())
            written += frame.samples_per_channel
            if stop_event.is_set():
                break
    except Exception:
        log.exception("Error recording track to %s", out_path)
    finally:
        if wav_file is not None:
            wav_file.close()
        await stream.aclose()


def _make_stt():
    """Speech-to-text for the clinic's side of the call.

    Default: OpenAI Whisper (batch). LiveKit has to wait for VAD to decide the
    agent stopped talking, then upload the whole clip, so every reply starts
    with an extra STT round trip. If DEEPGRAM_API_KEY is set we use Deepgram
    Nova-3 streaming instead, which transcribes while the agent is still
    speaking and cuts that wait. Either way we hint the clinic name so it is
    not misheard (Whisper once turned "Pivot Point" into "Tivitt Point")."""
    if DEEPGRAM_API_KEY:
        from livekit.plugins import deepgram
        kwargs = {"model": "nova-3", "language": "en-US"}
        params = inspect.signature(deepgram.STT.__init__).parameters
        if "keyterms" in params:
            kwargs["keyterms"] = ["Pivot Point Orthopedics", PATIENT_NAME]
        log.info("STT: Deepgram nova-3 (streaming)")
        return deepgram.STT(**kwargs)

    kwargs = {"model": OPENAI_STT_MODEL, "language": "en"}
    if "prompt" in inspect.signature(openai.STT.__init__).parameters:
        kwargs["prompt"] = (
            "Phone call with Pivot Point Orthopedics, an orthopedic clinic. "
            f"The patient is {PATIENT_NAME}."
        )
    log.info("STT: OpenAI %s (batch)", OPENAI_STT_MODEL)
    return openai.STT(**kwargs)


def _make_tts():
    """Text-to-speech for our patient's voice.

    Measured on a real call: OpenAI tts-1 took ~1.5 s to the first audio byte,
    the single biggest part of our ~2.6 s reply delay. Deepgram Aura-2 is
    built for phone agents and starts streaming audio in a few hundred ms, so
    it is used whenever a Deepgram key is available. Set TTS_PROVIDER=openai
    to force OpenAI."""
    if DEEPGRAM_API_KEY and os.getenv("TTS_PROVIDER", "deepgram") == "deepgram":
        from livekit.plugins import deepgram
        voice = os.getenv("DEEPGRAM_TTS_MODEL", "aura-2-orion-en")
        log.info("TTS: Deepgram %s (streaming)", voice)
        return deepgram.TTS(model=voice)
    log.info("TTS: OpenAI %s / %s", OPENAI_TTS_MODEL, OPENAI_TTS_VOICE)
    return openai.TTS(model=OPENAI_TTS_MODEL, voice=OPENAI_TTS_VOICE)


def _turn_taking_options() -> dict:
    """Turn-taking tuned for talking to another voice bot over a phone line.

    Heard on a real call: the clinic agent often speaks in two chunks with a
    short pause between them ("That's correct." ... "Your appointment is...").
    With LiveKit's defaults our patient started answering in that pause, got
    cut off when the agent kept talking, and then repeated itself ("Great,
    thank you for-- Great, thank you for confirming"). So we wait a little
    longer before deciding the agent is done, and only let the agent
    interrupt us with real speech (at least 2 words / 0.8 s), not a short
    noise or a trailing syllable. Only passed if this LiveKit version
    supports the option."""
    wanted = {
        "min_endpointing_delay": 0.8,     # default 0.5 s
        "min_interruption_duration": 0.8, # default 0.5 s
        "min_interruption_words": 2,      # default 0
    }
    supported = inspect.signature(AgentSession.__init__).parameters
    return {k: v for k, v in wanted.items() if k in supported}


def prewarm(proc):
    # Load the Silero VAD model once per worker process, before any job is
    # assigned, instead of inside the call entrypoint (loading it there
    # blocks the job right when it should be dialing).
    proc.userdata["vad"] = silero.VAD.load()


def _quiet_cancelled_tts_tasks():
    """The Deepgram TTS plugin (1.0.17) leaves a background task behind each
    time a reply finishes or is interrupted, and asyncio prints a harmless
    "_GatheringFuture exception was never retrieved ... CancelledError"
    traceback for it. It doesn't affect audio; this just keeps the logs
    readable. Every other asyncio error is still reported normally."""
    loop = asyncio.get_running_loop()
    default = loop.get_exception_handler()

    def handler(loop, context):
        if isinstance(context.get("exception"), asyncio.CancelledError) and \
                "never retrieved" in context.get("message", ""):
            return
        if default is None:
            loop.default_exception_handler(context)
        else:
            default(loop, context)

    loop.set_exception_handler(handler)


async def entrypoint(ctx: JobContext):
    _quiet_cancelled_tts_tasks()
    await ctx.connect()

    scenario_id = (ctx.job.metadata or "simple_scheduling").strip() or "simple_scheduling"
    scenario = get_scenario(scenario_id)
    call_id = ctx.room.name
    transcript = CallTranscript(call_id=call_id, scenario_id=scenario_id)
    log.info("Job started: room=%s scenario=%s", call_id, scenario_id)

    stop_recording = asyncio.Event()
    t0 = time.time()  # shared timeline origin for both recordings
    recording_tasks: list[asyncio.Task] = []
    agent_wav = RECORDINGS_DIR / f"{call_id}_agent.wav"
    patient_wav = RECORDINGS_DIR / f"{call_id}_patient.wav"

    finalized = False
    finalize_hooks: list = []  # extra save steps registered later (e.g. latency)

    async def finalize(*_):
        """Stop recording, save the transcript, and mix both sides into one
        MP3. Safe to call more than once."""
        nonlocal finalized
        if finalized:
            return
        finalized = True
        stop_recording.set()
        for t in recording_tasks:
            try:
                await asyncio.wait_for(t, timeout=5)
            except BaseException:
                t.cancel()
        json_path, txt_path = transcript.save()
        log.info("Transcript saved: %s (%d turns)", txt_path, len(transcript.turns))
        for hook in finalize_hooks:
            try:
                hook()
            except Exception:
                log.exception("finalize hook failed")

        wavs = [w for w in (agent_wav, patient_wav) if w.exists()]
        if not wavs:
            log.error("No audio was recorded for room %s", call_id)
            return
        out_mp3 = RECORDINGS_DIR / f"{call_id}.mp3"
        args = ["ffmpeg", "-y"]
        for w in wavs:
            args += ["-i", str(w)]
        if len(wavs) == 2:
            args += ["-filter_complex", "amix=inputs=2:duration=longest:normalize=0"]
        args += ["-c:a", "libmp3lame", "-q:a", "4", str(out_mp3)]
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await proc.wait()
        if proc.returncode == 0 and out_mp3.exists():
            for w in wavs:
                w.unlink(missing_ok=True)
            log.info("Recording saved: %s (%d side(s))", out_mp3, len(wavs))
        else:
            log.error("ffmpeg mixdown failed, keeping raw WAVs for room %s", call_id)

    ctx.add_shutdown_callback(finalize)

    @ctx.room.on("track_subscribed")
    def on_track_subscribed(track: rtc.Track, publication, participant: rtc.RemoteParticipant):
        # The SIP participant (Pretty Good AI's phone agent) publishes an
        # audio track once the call connects; record it as the "agent" side.
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            recording_tasks.append(
                asyncio.create_task(_record_track_to_wav(track, agent_wav, stop_recording, t0))
            )

    @ctx.room.on("local_track_published")
    def on_local_track_published(publication, track: rtc.Track):
        # Our own TTS output track ("patient" side of the call).
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            recording_tasks.append(
                asyncio.create_task(_record_track_to_wav(track, patient_wav, stop_recording, t0))
            )

    # --- Step 1: dial out and wait for the clinic's line to answer. ---
    # We dial BEFORE starting the voice pipeline (LiveKit's recommended
    # outbound pattern). The SIP participant joins the room as soon as the
    # phone starts ringing, so "joined" does not mean "answered":
    # wait_until_answered=True blocks until the call is actually picked up,
    # or raises with the real SIP status code (busy, rejected, no answer...).
    @ctx.room.on("participant_attributes_changed")
    def on_attrs_changed(changed: dict, participant: rtc.Participant):
        if "sip.callStatus" in changed:
            log.info("SIP call status: %s", changed["sip.callStatus"])

    callee_left = asyncio.Event()

    @ctx.room.on("participant_disconnected")
    def on_participant_disconnected(participant: rtc.RemoteParticipant):
        callee_left.set()
        log.info("Participant left room %s: %s (reason: %s)",
                 ctx.room.name, participant.identity, getattr(participant, "disconnect_reason", "?"))

    log.info("Step 1: dialing %s via trunk %s", TARGET_NUMBER, SIP_TRUNK_ID)
    lkapi = api.LiveKitAPI(url=LIVEKIT_URL, api_key=LIVEKIT_API_KEY, api_secret=LIVEKIT_API_SECRET)
    try:
        await asyncio.wait_for(
            lkapi.sip.create_sip_participant(
                api.CreateSIPParticipantRequest(
                    sip_trunk_id=SIP_TRUNK_ID,
                    sip_call_to=TARGET_NUMBER,
                    room_name=ctx.room.name,
                    participant_identity="pivot-point-agent",
                    participant_name="Pivot Point Orthopedics Agent",
                    wait_until_answered=True,
                )
            ),
            timeout=60,
        )
        log.info("Step 1 done: call answered")
    except asyncio.TimeoutError:
        log.error("Step 1 FAILED: call not answered within 60s")
        await lkapi.aclose()
        await finalize()
        return
    except Exception as e:
        # A rejected/busy/unanswered call raises a TwirpError carrying the SIP
        # status code in its metadata; read it defensively across SDK versions.
        meta = getattr(e, "metadata", None) or {}
        log.error("Step 1 FAILED: %s: %s (sip status %s %s)", type(e).__name__,
                  getattr(e, "message", e), meta.get("sip_status_code"), meta.get("sip_status"))
        await lkapi.aclose()
        await finalize()
        return
    await lkapi.aclose()

    # --- Step 2: start the STT -> LLM -> TTS pipeline on the live call. ---
    log.info("Step 2: starting AgentSession")
    session = AgentSession(
        stt=_make_stt(),
        llm=openai.LLM(model=OPENAI_LLM_MODEL),
        tts=_make_tts(),
        vad=ctx.proc.userdata["vad"],
        **_turn_taking_options(),
    )

    # Per-turn latency of OUR side, from LiveKit's built-in metrics:
    # end-of-utterance delay (how long after the agent stopped talking we
    # decided it was our turn), LLM time-to-first-token, and TTS
    # time-to-first-byte. Their sum is roughly how long the clinic waits for
    # our patient to start answering. Saved next to the transcript.
    latency = {"eou_delay": [], "llm_ttft": [], "tts_ttfb": []}

    @session.on("metrics_collected")
    def on_metrics(event):
        m = event.metrics
        name = type(m).__name__
        if name == "EOUMetrics":
            latency["eou_delay"].append(round(getattr(m, "end_of_utterance_delay", 0.0), 3))
        elif name == "LLMMetrics" and getattr(m, "ttft", -1) >= 0:
            latency["llm_ttft"].append(round(m.ttft, 3))
        elif name == "TTSMetrics" and getattr(m, "ttfb", -1) >= 0:
            latency["tts_ttfb"].append(round(m.ttfb, 3))

    def _save_latency():
        avg = {k: round(sum(v) / len(v), 3) if v else None for k, v in latency.items()}
        parts = [a for a in avg.values() if a is not None]
        avg["est_response_delay"] = round(sum(parts), 3) if parts else None
        out = Path(__file__).resolve().parent.parent / "transcripts" / f"{call_id}.latency.json"
        out.write_text(json.dumps({"averages_sec": avg, "per_turn_sec": latency}, indent=2))
        log.info("Latency (avg s): end-of-turn %s + LLM %s + TTS %s = ~%s before each patient reply",
                 avg["eou_delay"], avg["llm_ttft"], avg["tts_ttfb"], avg["est_response_delay"])

    finalize_hooks.append(_save_latency)

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
        log.info("[%s] %s", role, text)

    # The LLM has no idea what today's date is and will invent one (in testing
    # it told the clinic "it's February right now" in September), so give it
    # the real date in the clinic's timezone (805 area code = California).
    today = datetime.now(ZoneInfo("America/Los_Angeles"))
    date_note = (
        f"\n\nToday's date is {today:%A, %B} {today.day}, {today.year}. "
        "Treat any dates the agent offers relative to this date, and never claim "
        "it is a different date or month."
    )
    agent = Agent(instructions=scenario.system_prompt + date_note)
    try:
        await asyncio.wait_for(session.start(agent=agent, room=ctx.room), timeout=30)
    except BaseException as e:  # includes CancelledError, so a hang can't exit silently
        log.error("Step 2 FAILED: session.start() did not complete (%s: %s)", type(e).__name__, e)
        await finalize()
        raise
    log.info("Step 2 done: pipeline running, conversation in progress")

    # Wait for the call to end: the clinic hangs up (normal end of a
    # conversation) or a 5-minute safety cap is reached.
    try:
        await asyncio.wait_for(callee_left.wait(), timeout=300)
        log.info("Call ended (clinic hung up)")
    except asyncio.TimeoutError:
        log.info("Call hit the 5-minute cap, ending it")
    await finalize()
    ctx.shutdown(reason="call finished")


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm, agent_name=AGENT_NAME))
