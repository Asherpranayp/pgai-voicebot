# Bug Report — Pretty Good AI Voice Agent

Generated from 10 test calls against Pivot Point Orthopedics' phone agent. Each finding below was independently verified against the recording, not just the auto-transcript.

## 1. "Transfer" silently drops the call instead of connecting anywhere
**Severity:** High — reproduced in 3 separate calls
**Calls:**
- `transcripts/CA2b9dd396aa06ac2f94c587306a16d226.txt` (reschedule_appointment) at 03:25
- `transcripts/CA3d9d56af32bf7735911c39d605f40a64.txt` (medication_refill) at 01:27
- `transcripts/CA51c0d6d7e883b670e72c8b649ea72d67.txt` (refill_wrong_medication) at 01:43

**Details:** Whenever the agent says it's transferring the caller (to reschedule, to check on a refill, or to "patient support"), the call actually connects to a dead/test line and ends with no human and no resolution. This happened consistently across three unrelated scenarios, so it isn't a one-off — it looks like the transfer target is misconfigured or simply not wired up. This is the single most impactful bug found: any patient whose issue needs escalation gets silently disconnected.

## 2. Sent appointment confirmation to a phone number the patient never gave, then failed to correct it
**Severity:** High
**Call:** `transcripts/CA006537267a3a9dffe4a4b56e61c3e285.txt` (simple_scheduling) at 02:25 and 02:46
**Details:** The agent confirmed it would text appointment details to a number ending in 5133 — a number the patient never provided during the call. When the patient corrected it, the agent repeated the same wrong number back instead of updating it. This is a real privacy/reliability issue: confirmation details could go to a stranger, and the correction was never actually applied.

## 3. Contradicted its own earlier appointment details mid-call
**Severity:** High
**Call:** `transcripts/CA2b9dd396aa06ac2f94c587306a16d226.txt` (reschedule_appointment) at 01:31
**Details:** The agent stated the existing appointment was at 10:30 a.m., directly contradicting the 2 p.m. time the patient had just given moments earlier — and never resolved the discrepancy before the call ended (in the same call as bug #1's failed transfer). A scheduling agent that can't hold a single appointment time consistent within one call is a significant reliability problem.

## 4. Doesn't ask clarifying questions for a vague refill request — just refuses
**Severity:** Medium
**Call:** `transcripts/CA51c0d6d7e883b670e72c8b649ea72d67.txt` (refill_wrong_medication) at 01:11
**Details:** When the patient described their medication vaguely ("the white pill for my shoulder") instead of by name, the agent didn't ask any follow-up questions (dosage, when prescribed, what it treats) — it just stated no medications could be refilled. A better agent would try to narrow down the medication before giving up, since patients often don't know exact drug names.

## 5. Doesn't retain information the patient already gave in the same call
**Severity:** Medium — reproduced twice in one call
**Call:** `transcripts/CA8b1b30c5be03d428b93901aa49d28537.txt` (insurance_question) at 01:09, 01:15, 01:25
**Details:** The agent misheard/misrecorded the patient's name twice ("Asher Pauly", then "Asher Pernai-Pauley") despite the patient spelling it out, and separately re-asked for the insurance plan name twice after the patient had already clearly stated "Blue Cross Blue Shield PPO." Both are the same underlying failure — not retaining/confirming what was just said — and together make the agent feel like it isn't really listening.

## 6. Avoids giving a ballpark self-pay cost estimate even when pushed
**Severity:** Medium
**Call:** `transcripts/CA8b1b30c5be03d428b93901aa49d28537.txt` (insurance_question) at 02:08
**Details:** When asked for a rough out-of-pocket cost if insurance isn't accepted, the agent initially deflected instead of giving even an approximate range. Patients calling to decide whether a visit is affordable need at least a ballpark number to make that decision.

## 7. Provider name garbled/mispronounced inconsistently within a single call
**Severity:** Medium — reproduced across multiple calls
**Call:** `transcripts/CA310fe693703487513ee7932f284e4a93.txt` (weekend_request_edge_case)
**Details:** The same doctor's name came out differently multiple times in one call (e.g. "Zygmunt Lukoski" / "Zbigniew Lukoski" / "Zignu Lukosky"). This pattern of inconsistent name rendering for both patients and providers showed up in more than one call and undermines confidence that appointment confirmations reference the correct provider.

## 8. Positive finding: correctly caught a weekend request against office hours
**Severity:** N/A (working as intended)
**Call:** `transcripts/CA310fe693703487513ee7932f284e4a93.txt` (weekend_request_edge_case)
**Details:** When asked for a Sunday appointment, the agent correctly recognized the clinic is closed on Sundays rather than just booking the slot as requested, and offered weekday alternatives instead. Worth noting as evidence the agent isn't universally compliant/agreeable — it does have some real validation logic.

## 9. Switched providers without clearly confirming the change back to the patient
**Severity:** Medium
**Call:** `transcripts/CA8d6d1c82d35c3099878b53be51f84338.txt` (interruption_edge_case) at 00:42
**Details:** The patient asked for Dr. Kim specifically; when Dr. Kim had no openings, the agent moved on to booking with Dr. Kelly Noble instead — but never explicitly said "since Dr. Kim isn't available, I'm booking you with Dr. Kelly Noble instead," it just proceeded and confirmed the new provider as if it were the original request. A patient half-listening (as this scenario intentionally simulated) could easily walk away not realizing their provider changed.
