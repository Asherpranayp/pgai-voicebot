"""
Accumulates a running transcript for one call and writes it to disk once the
call ends. Kept deliberately simple (a list of turns in memory) since a single
call is short and this process only ever handles one call at a time.
"""
import json
import time
from pathlib import Path
from dataclasses import dataclass, field, asdict

TRANSCRIPTS_DIR = Path(__file__).resolve().parent.parent / "transcripts"
TRANSCRIPTS_DIR.mkdir(exist_ok=True)


@dataclass
class Turn:
    role: str          # "agent" (Pretty Good AI) or "patient" (our simulated caller)
    text: str
    t: float           # seconds since call start


@dataclass
class CallTranscript:
    call_id: str
    scenario_id: str
    started_at: float = field(default_factory=time.time)
    turns: list = field(default_factory=list)

    def add(self, role: str, text: str):
        if not text or not text.strip():
            return
        self.turns.append(Turn(role=role, text=text.strip(), t=round(time.time() - self.started_at, 2)))

    def save(self):
        json_path = TRANSCRIPTS_DIR / f"{self.call_id}.json"
        txt_path = TRANSCRIPTS_DIR / f"{self.call_id}.txt"

        json_path.write_text(json.dumps({
            "call_id": self.call_id,
            "scenario_id": self.scenario_id,
            "started_at": self.started_at,
            "turns": [asdict(t) for t in self.turns],
        }, indent=2))

        lines = [f"Call: {self.call_id}  Scenario: {self.scenario_id}\n"]
        for turn in self.turns:
            mins, secs = divmod(int(turn.t), 60)
            speaker = "AGENT  " if turn.role == "agent" else "PATIENT"
            lines.append(f"[{mins:02d}:{secs:02d}] {speaker}: {turn.text}")
        txt_path.write_text("\n".join(lines) + "\n")

        return json_path, txt_path
