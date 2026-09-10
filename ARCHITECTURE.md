# Architecture

The bot places an outbound call through Twilio Programmable Voice to Pretty Good AI's
test line. Once the call connects, Twilio opens a bidirectional Media Streams
WebSocket back to a small FastAPI server, which forwards that raw audio straight into
OpenAI's Realtime API and streams the audio it gets back to Twilio. The Realtime model
is given a system prompt describing a specific patient persona and goal (one of a
fixed set of scenarios — scheduling, rescheduling, refills, info questions, and a
few deliberately awkward edge cases), and its server-side voice-activity detection
decides when the "agent" has finished talking and it's the "patient's" turn to
respond — the same mechanism that lets the bot be interrupted mid-sentence, which
matters for the barge-in scenario. Twilio also records the call end-to-end; a
recording-ready webhook downloads the MP3 once it's available. Both sides of the
conversation are transcribed as the call happens (Whisper for the agent's audio,
the Realtime model's own transcript for its replies) and written to a timestamped
transcript file. A separate, offline script then runs the finished transcripts
through a plain (non-realtime) LLM pass with a rubric asking specifically for
concrete quality issues, rather than nitpicks, and produces a consolidated bug report.

I chose a realtime voice-to-voice bridge (Twilio Media Streams -> OpenAI Realtime)
over a classic STT-then-LLM-then-TTS pipeline because the challenge's evaluation
explicitly gates on "coherent voice conversation" and "natural pacing" before
anything else gets reviewed — a chained pipeline adds a full network round-trip per
turn (transcribe, then infer, then synthesize) that shows up as audible dead air,
and it also throws away Realtime's built-in server-side VAD, which is what makes
interruption handling work without hand-rolled audio-level silence detection. The
tradeoff is losing some of the independent debuggability of a modular pipeline
(you can't easily swap the STT or TTS vendor, and errors inside the Realtime session
are less visible than a discrete pipeline stage failing loudly) and being more
exposed to one vendor's realtime infrastructure and pricing; given the time budget
and that voice quality is the priority-one bar here, that tradeoff was worth it.
Audio format was also a deciding factor in keeping things simple: Twilio's Media
Streams already speak mu-law 8kHz, which OpenAI Realtime accepts natively
(`g711_ulaw`), so audio is relayed with zero transcoding or extra dependencies —
one less thing to get wrong under a tight time budget.
