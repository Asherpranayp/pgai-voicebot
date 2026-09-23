"""
Post-call analysis pass: reads every transcript in transcripts/, asks an LLM
(a plain chat-completions call, not Realtime) to flag concrete bugs or quality
issues in the AGENT's responses, and writes a first-pass draft to bug_report/auto_draft.md.

The draft is only a starting point: LLM review of transcripts is not deterministic
and can't hear the audio, so the final bug_report/bug_report.md is written by hand
after checking each finding against the recording.

This is a separate, offline pass rather than something the patient bot does
live on the call, on purpose: judging response quality benefits from seeing
the whole conversation at once (not turn-by-turn), and keeping it offline
means a bad live judgment never disrupts the phone call itself.

Usage:
    python -m bug_analysis.analyze
"""
import json
from pathlib import Path

from openai import OpenAI

from app.config import OPENAI_API_KEY
from app.scenarios import get_scenario

TRANSCRIPTS_DIR = Path(__file__).resolve().parent.parent / "transcripts"
BUG_REPORT_DIR = Path(__file__).resolve().parent.parent / "bug_report"
BUG_REPORT_DIR.mkdir(exist_ok=True)

client = OpenAI(api_key=OPENAI_API_KEY)

ANALYSIS_PROMPT = """\
You are reviewing a transcript of a phone call between an AI patient (testing a system) and \
an AI phone agent for an orthopedic clinic called Pivot Point Orthopedics. The PATIENT lines \
are the tester; the AGENT lines are the system under test. You only care about problems with \
the AGENT's behavior.

The call's test goal was: {goal}

Look for concrete issues such as:
- Factual or logical errors (e.g. confirming something impossible, like a weekend appointment \
at a clinic that's closed weekends, without checking)
- Failing to ask for or verify information it should have (identity, reason for visit, insurance)
- Ignoring or mishandling what the patient actually said (non-sequiturs, repeating a question \
already answered, contradicting itself)
- Poor handling of interruptions, vague requests, or corrections
- Failing to actually accomplish the patient's stated goal, or ending the call unresolved
- Anything a real patient would find confusing, unhelpful, or untrustworthy

Do NOT report nitpicks about phrasing, tone, or punctuation. Only report things that would \
actually matter to a real patient or the clinic.

For each issue found, respond with one JSON object per issue in a JSON array, each with fields:
  "severity": "High" | "Medium" | "Low"
  "timestamp": the [MM:SS] from the transcript line where it occurs
  "summary": one sentence describing what happened
  "details": 2-4 sentences explaining why it's a problem and what should have happened instead

If there are no real issues, return an empty JSON array: []

Transcript:
{transcript}

Respond with ONLY the JSON array, no other text.
"""


def analyze_one(json_path: Path):
    data = json.loads(json_path.read_text())
    scenario = get_scenario(data["scenario_id"])

    txt_path = json_path.with_suffix(".txt")
    transcript_text = txt_path.read_text() if txt_path.exists() else json.dumps(data["turns"])

    prompt = ANALYSIS_PROMPT.format(goal=scenario.goal, transcript=transcript_text)

    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    content = resp.choices[0].message.content.strip()
    # Be tolerant of accidental markdown code fences.
    content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        issues = json.loads(content)
    except json.JSONDecodeError:
        issues = [{"severity": "Low", "timestamp": "?", "summary": "Analysis output was not valid JSON",
                   "details": content[:500]}]

    return data["call_id"], scenario, issues


def main():
    transcript_files = sorted(TRANSCRIPTS_DIR.glob("*.json"))
    if not transcript_files:
        print("No transcripts found in transcripts/. Place some calls first.")
        return

    all_results = []
    for path in transcript_files:
        call_id, scenario, issues = analyze_one(path)
        all_results.append((call_id, scenario, issues))
        print(f"{call_id} ({scenario.id}): {len(issues)} issue(s) found")

    lines = ["# Bug Report — Pretty Good AI Voice Agent\n"]
    lines.append(f"Generated from {len(all_results)} call(s).\n")

    total_issues = sum(len(issues) for _, _, issues in all_results)
    if total_issues == 0:
        lines.append("No issues were flagged by the automated pass. See individual transcripts "
                      "in transcripts/ for manual review.\n")

    for call_id, scenario, issues in all_results:
        if not issues:
            continue
        lines.append(f"## {scenario.title} (`{scenario.id}`)")
        lines.append(f"Call: `transcripts/{call_id}.txt`  |  Recording: `recordings/{call_id}.mp3`\n")
        for issue in issues:
            lines.append(f"**Bug:** {issue.get('summary', '(no summary)')}")
            lines.append(f"**Severity:** {issue.get('severity', 'Unknown')}")
            lines.append(f"**Call:** transcripts/{call_id}.txt at {issue.get('timestamp', '?')}")
            lines.append(f"**Details:** {issue.get('details', '')}")
            lines.append("")
        lines.append("")

    report_path = BUG_REPORT_DIR / "auto_draft.md"
    report_path.write_text("\n".join(lines))
    print(f"\nWrote {report_path} ({total_issues} total issue(s) across all calls)")


if __name__ == "__main__":
    main()
