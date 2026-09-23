# Architecture

The bot is a Python [LiveKit Agents](https://docs.livekit.io/agents/) worker running in
**pipeline mode**: speech-to-text, LLM and text-to-speech are three separate models, as the
challenge requires. For each call, `dispatch_call.py` creates a LiveKit room and dispatches a job
carrying the scenario id. The worker then dials +1-805-439-8008 by adding a SIP participant through
a LiveKit outbound trunk that is backed by a Twilio Elastic SIP Trunk (caller ID +1-920-551-5133).
It waits until the call is actually answered (`wait_until_answered=True`, which also surfaces the
real SIP error codes) and only then starts the `AgentSession`:
**Deepgram Nova-3** streaming STT → **GPT-4o-mini** → **Deepgram Aura-2** streaming TTS, with
**Silero VAD** loaded once per worker process for turn detection. Each scenario is a
patient persona prompt with a goal, the patient's identity, today's real date, and rules about
behavior: stay in character, don't invent facts, only correct things that matter. Both sides are
captured as the call happens. STT output and LLM replies become a timestamped transcript. Each
participant's audio track is tapped to its own WAV, padded with silence so the two stay on one
timeline, and mixed into a single MP3. Saving runs in a shutdown callback, so files are written
even when the clinic hangs up first. Per-turn latency comes from LiveKit's own metrics and is
saved next to each transcript. `python -m app.run_calls` runs the whole thing with one command.
Bug analysis is a separate offline step: `bug_analysis/analyze.py` produces an LLM draft, and the
final `bug_report/bug_report.md` is written by hand after checking the recordings.

**Why these choices.** The main tradeoff in pipeline mode is latency, since every reply chains
three network hops, so I measured it instead of guessing. The first version used OpenAI for
everything (whisper-1 → gpt-4o-mini → tts-1). LiveKit's metrics showed about **2.6 s** before
each patient reply, and ffmpeg `silencedetect` on the recording confirmed 2-5 s gaps. Most of that
was TTS (1.5 s to first audio) plus batch STT, which waits for the speaker to stop before
uploading. Switching STT and TTS to Deepgram's streaming models brought TTS to about 0.18 s and the
total to about **1.3-1.6 s**, which sounds like a normal phone conversation. GPT-4o-mini stayed
because the patient only needs short, in-character replies, and a larger model would add
first-token latency without making the calls noticeably better. Turn-taking was the second thing
tuned from real audio. The clinic agent often pauses in the middle of a turn ("That's
correct." … "Your appointment is…"), and with LiveKit's default 0.5 s endpointing our patient
jumped into those pauses, got cut off, and repeated itself. Raising the endpointing delay to
0.8 s, and requiring at least 2 words / 0.8 s before our bot treats speech as an interruption,
fixed that for a cost of about 0.3 s. For telephony, LiveKit SIP over a Twilio trunk reused the
Twilio number I already had and needs no public webhook server (my first prototype used Twilio
Media Streams plus ngrok). I rejected realtime speech-to-speech models, which the challenge
disallows, and hosted voice platforms, which hide the pipeline I was asked to build. Everything runs
from a Google Colab notebook with GitHub as the single source of truth, so the setup works from any
machine. Several fixes also came from listening to calls rather than reading code: the patient
misspelled its own name and claimed it was February (fixed by putting the exact spelling and the
real date in the prompt), and it "corrected" the agent over a name that our STT had misheard
(fixed by only pushing back on facts that matter).
