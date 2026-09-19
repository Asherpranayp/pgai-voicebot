# Architecture

The bot is a [LiveKit Agents](https://docs.livekit.io/agents/) worker running in
**pipeline mode**: speech-to-text, LLM, and text-to-speech are three separate calls
rather than one realtime/speech-to-speech model, per the assessment's hard stack
requirement. A small CLI (`dispatch_call.py`) creates a LiveKit room and explicitly
dispatches a job to the worker, passing which patient scenario to run as job metadata.
The worker joins that room, starts an `AgentSession` (OpenAI Whisper for STT, GPT-4o-mini
for the LLM, OpenAI TTS for speech, Silero VAD for turn detection), and then dials the
real phone number by creating a SIP participant against a LiveKit outbound SIP trunk —
that trunk is itself backed by a Twilio Elastic SIP Trunk pointed at the same Twilio
number used throughout this project, so the call still physically goes out over Twilio's
PSTN connectivity, just orchestrated by LiveKit instead of Twilio's Media Streams. Once
Pretty Good AI's agent answers, it's bridged into the room as a normal SIP participant,
and from there it's just a two-party LiveKit room: our LLM-driven "patient" persona
(from `scenarios.py`) versus their AI agent. Both sides are captured as the call
happens — STT transcriptions of the other party's speech and our own LLM's replies are
logged to a timestamped transcript, and both participants' raw audio tracks are tapped
directly and written to WAV, then mixed into a single MP3 once the call ends so each
deliverable is one file with both sides audible.

The main design decision forced by this challenge was pipeline mode itself: STT, LLM,
and TTS as three independent, swappable stages, rather than the realtime voice-to-voice
models (OpenAI Realtime, etc.) that the assessment explicitly disallows. The tradeoff
this forces is real — a chained pipeline adds a network round-trip per turn
(transcribe, then infer, then synthesize) that a single realtime session avoids, so
extra care went into keeping each stage fast (Whisper and `tts-1` are the low-latency
tier of their respective APIs, and `gpt-4o-mini` was chosen over a larger model
specifically to keep inference quick, since correctness for a scripted patient persona
doesn't need a bigger model) and into turn detection: Silero VAD (bundled with LiveKit
Agents) handles end-of-speech and barge-in detection locally and cheaply, rather than
depending on a cloud model to signal turn boundaries the way Realtime's server-side VAD
does. I chose OpenAI for all three pipeline stages over mixing vendors (e.g. Deepgram
for STT, ElevenLabs for TTS) mainly for setup simplicity and one fewer API key/account
to manage under the time budget — the tradeoff is giving up the lower per-stage latency
some specialized providers offer, which is the main place a from-scratch pipeline could
still be tightened further. For telephony, LiveKit's SIP integration was the natural
choice once pipeline mode was required, since it reuses the same Twilio number and
Twilio-side SIP trunk configuration this project already had, without needing to also
stand up a public webhook server (unlike the Twilio Media Streams approach, LiveKit's
SIP participant model doesn't require exposing an HTTP endpoint to Twilio at all, which
simplified the infrastructure once the Realtime-API-based bridge was ruled out).
