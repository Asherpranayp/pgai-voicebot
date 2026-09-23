# Bug Report: Pivot Point Orthopedics AI Agent

Tested with 12 automated voice calls to +1-805-439-8008 (September 22-23, 2026), all placed
from +1-920-551-5133 by the LiveKit pipeline bot in this repo. Each call has a recording
(`recordings/<call>.mp3`) and a transcript (`transcripts/<call>.txt`). Timestamps below are
`[mm:ss]` from the transcript and line up with the MP3 to within about a second.

Findings are about the agent's *behavior* (what it did, booked, or said it would do), and each
cites the recording so it can be heard directly. Our own speech-to-text occasionally mishears
names (for example, the agent clearly says "Pivot Point" in the audio of one call where our
transcript reads "Tivitt Point"), so name spellings in transcripts are **not** reported as bugs.

## Summary

| # | Bug | Severity | Reproduced |
|---|-----|----------|------------|
| 1 | "Transfer to a person" plays a test-line goodbye and hangs up | High | 3 of 3 transfers |
| 2 | Correct date of birth rejected, then accepted anyway "for demo purposes", and private data disclosed | High | 3 of 11 identity checks |
| 3 | Books appointments when the clinic is closed (Wednesday mornings) | High | 3 calls |
| 4 | Confirmed appointments disappear; existing appointments are never checked | Medium-High | 5 calls |
| 5 | Availability contradicts itself: an urgent patient is told "nothing for 2+ weeks", another gets "several openings tomorrow" 7 minutes later | Medium | 2 calls |
| 6 | Clinic location changes between calls (Nashville vs. "only one location, in Austin") | Medium | 2 calls |
| 7 | Refill requests hit a dead end with no fallback | Medium | 2 calls |
| 8 | Avoids a direct "are you open Sunday?" question | Low | 1 call |
| 9 | Minor: speaks over the caller, drops middle name on read-back, doesn't ask where the pain is | Low | several |

---

## 1. "Transfer to a person" plays a test-line goodbye and hangs up
**Severity:** High. It's the only escalation path the agent offers, and it fails every time.

**Calls:**
- `pgai-reschedule_appointment-1790133443` at 02:43-02:48
- `pgai-medication_refill-1790135801` at 01:20-01:37
- `pgai-refill_wrong_medication-1790136109` at 01:31-01:43

**What happened:** When the agent can't solve the problem, it offers to connect the caller to
"someone at the clinic" or "our patient support team". The patient accepts, the agent says
"Transferring you now. Thank you.", and the call immediately plays *"Hello. You've reached the
Pretty Good AI test line. Goodbye."* and disconnects. In the third call the transfer message was
cut off mid-sentence: *"Please stay on the line while You've reached the Pretty Good AI test
line. Goodbye."* Each time the patient's issue was unresolved (no reschedule slot, no refill),
and they're left saying "Wait, I think I got disconnected."

**Expected:** Transfer to a real queue or voicemail, or, if no human is available, say so and
offer a callback or message *before* ending the call. It should never play an internal test
message to a patient.

## 2. Correct date of birth rejected, then accepted anyway "for demo purposes", and private data disclosed
**Severity:** High. Identity verification in a healthcare context is both unreliable and bypassable.

**Calls:**
- `pgai-refill_wrong_medication-1790136109` at 01:02
- `pgai-insurance_question-1790137575` at 00:54, 01:05, 01:21
- `pgai-vague_unclear_request-1790138778` at 00:56

**What happened:** The patient gives the date of birth on the test account (February 16, 1995,
confirmed correct). In 3 calls the agent replied *"The birthday doesn't match our records. But
for demo purposes, I'll accept it."* The same DOB was accepted without comment in the other 8
calls that asked for it, so the check is inconsistent. Worse, after the failed check the agent
carried on with full access. In the insurance call it read back *"Blue Cross Blue Shield PPO, with member ID
ending in two one seven eight"* (01:21), right after saying the DOB didn't match. When the
patient repeated the correct DOB and asked the agent to confirm it (01:05), the agent ignored
the question.

**Expected:** A correct DOB should always verify. A failed check should block access to chart,
insurance and appointment details (retry, or escalate to staff). "For demo purposes" is
internal behavior that patients should never hear.

## 3. Books appointments when the clinic is closed (Wednesday mornings)
**Severity:** High. Patients would show up to a closed clinic. This is the same class of bug as
"booking a Sunday".

**Calls:**
- Hours stated: `pgai-office_hours_location-1790136859` at 00:45 ("Wednesday from 12PM to 7PM")
  and 01:12 (*"On Wednesdays, the clinic opens at 12PM, so we don't have morning appointments
  that day."*)
- `pgai-simple_scheduling-1790135314` at 01:21-01:38: books **Wednesday Sept 23, 9 AM**
- `pgai-interruption_edge_case-1790138325` at 01:49-02:50: offers "morning slots before 10AM"
  on Wednesday and books **Wednesday 8 AM**
- `pgai-vague_unclear_request-1790138778` at 02:22: offers **Wednesday Sept 23, 9 AM** as the
  earliest slot

**What happened:** The agent knows the rule when asked about it directly, but its booking flow
ignores it and offers or confirms Wednesday morning slots three hours before opening.

**Expected:** Only offer slots inside the clinic's stated hours. If the patient asks for a
closed time, say the clinic is closed and offer the nearest open slot.

## 4. Confirmed appointments disappear; existing appointments are never checked
**Severity:** Medium-High. A patient told "your appointment is set" may have no appointment.

**Calls, in order:**
1. `pgai-simple_scheduling-1790132741` at 01:45: *"Your appointment is set for Thursday,
   September 24 at 10:30AM with doctor Judy Hauser."*
2. `pgai-reschedule_appointment-1790133443` at 01:30, about 12 minutes later: *"The only
   appointment I see on file is for tomorrow, Wednesday, September 23."* The Thursday booking is gone.
3. `pgai-cancel_appointment-1790134572` at 01:54: *"There is no appointment listed for
   September 24."*
4. `pgai-simple_scheduling-1790135314` (01:38) books Wed 9 AM. Later,
   `pgai-interruption_edge_case-1790138325` (02:50) books Wed 8 AM without mentioning it, and
   `pgai-vague_unclear_request-1790138778` (02:22) offers the already-booked Wed 9 AM slot as
   open, then books a third appointment (Thu 2 PM, 03:32).
5. `pgai-frustrated_confused_patient-1790139247`, 8 minutes later: the agent reports only the
   Thu 2 PM appointment on file. The Wed 9 AM and Wed 8 AM appointments it confirmed earlier the
   same day are gone, and it never mentions them.

**What happened:** Bookings confirmed on one call are missing on the next. When new bookings are
made, the agent never mentions or reconciles the patient's existing appointments, and it offers
the patient's own booked slot as available.

**Expected:** Confirmed bookings persist. Before booking, check existing appointments for the
patient and ask whether this is an additional visit or a change.

## 5. Availability contradicts itself between calls minutes apart
**Severity:** Medium. An urgent patient was sent away with no appointment.

**Calls:**
- `pgai-weekend_request_edge_case-1790137888` at 01:47, 02:36: the patient with **urgent** knee
  pain is told *"There are no open appointments available through next Tuesday"*, then *"still no
  open appointments through the week after next"*. They get only a promised callback.
- `pgai-interruption_edge_case-1790138325` at 01:49, about 7 minutes later: another **urgent**
  knee-pain request gets *"We have several openings tomorrow, Wednesday"*.
- `pgai-vague_unclear_request-1790138778` at 02:46-03:05: several openings on Thursday
  (9 AM, 2 PM, 2:30 PM, 3 PM).

**Expected:** Consistent availability. An urgent patient should be offered the same next-day
slots other callers are getting.

## 6. Clinic location changes between calls
**Severity:** Medium. Patients could go to the wrong city.

**Calls:**
- `pgai-reschedule_appointment-1790133443` at 01:16: the appointment is "at Nashville, 220
  Athens Way".
- `pgai-office_hours_location-1790136859` at 01:39: *"1234 Recovery Way, Suite 200, Austin,
  Texas 78701. We only have this one location in Austin. There isn't a Nashville office."*

**Notes:** "1234 Recovery Way" also looks like placeholder data, and neither city matches the
clinic's 805 (California) phone number.

**Expected:** One consistent, real address, and appointment locations that exist.

## 7. Refill requests hit a dead end with no fallback
**Severity:** Medium. A patient who is almost out of medication leaves with nothing.

**Calls:**
- `pgai-medication_refill-1790135801` at 00:59-01:20
- `pgai-refill_wrong_medication-1790136109` at 01:10-01:31

**What happened:** The agent says *"I don't see any medications on your chart that I can refill"*
and its only offer is the broken transfer (bug #1). It never asks for the medication name,
dose, prescriber or pharmacy, even when the patient describes it vaguely ("the white pill for my
shoulder"), and it never offers to send a refill request to the provider.

**Expected:** Collect medication, dose and pharmacy, and create a refill request or message for
the care team. Tell the patient when to expect a response.

## 8. Avoids a direct "are you open Sunday?" question
**Severity:** Low. The agent correctly didn't book Sunday, but the answer is evasive.

**Call:** `pgai-weekend_request_edge_case-1790137888` at 01:54-02:11

**What happened:** The patient asks *"Are you saying the office isn't open then?"* The agent
replies *"I don't have any available appointments for this Sunday 10AM"*, which suggests Sunday
is just booked up, and never says the clinic is closed on weekends.

**Expected:** "We're closed on weekends; our hours are…", then offer the nearest weekday slot.

## 9. Minor issues
- **Talks over the caller / fragmented turns:** `pgai-weekend_request_edge_case-1790137888` at
  02:23-02:36. The agent says "One moment", starts "There are still no…" over the patient, and
  the patient has to ask it to repeat.
- **Drops the middle name on read-back:** `pgai-interruption_edge_case-1790138325` at 02:50.
  "I have your name as Asher Palle", and the patient corrects it.
- **Won't spell a provider's name for a confused patient:**
  `pgai-frustrated_confused_patient-1790139247`. An elderly-style patient asks the agent to spell
  the doctor's name. The agent says *"I'm not able to spell the provider's name"* and repeats it
  several different ways. That's a problem for accessibility and for patients who need to find
  the right doctor.
- **No basic triage for a vague complaint:** `pgai-vague_unclear_request-1790138778` at 01:31.
  An orthopedic clinic books a "general office visit" for "issues with pain" without asking
  where the pain is.

---

## What the agent handled well
- **Didn't book the requested Sunday slot** (`weekend_request_edge_case`, 02:11).
- **Handled interruptions gracefully.** The patient cut in twice ("Wait, actually…") and the
  agent adapted each time (`interruption_edge_case`, 01:10, 01:56).
- **Correctly rejected a made-up appointment.** The reschedule scenario claims a Thursday 2 PM
  appointment; the agent said none exists and offered the real one (`reschedule_appointment`,
  01:39).
- **Stayed patient with a confused caller.** It repeated dates and names politely when asked
  several times (`frustrated_confused_patient`).
- **Answered insurance and parking questions clearly** and offered a billing callback for self-pay
  pricing it didn't know (`insurance_question` 01:39-02:25, `office_hours_location` 01:53).

## Calls in this submission

| Call | Scenario | Length | Key findings |
|------|----------|--------|--------------|
| `pgai-simple_scheduling-1790132741` | New-patient scheduling | 2:21 | #4 (booking later disappears) |
| `pgai-simple_scheduling-1790135314` | New-patient scheduling | 2:38 | #3, #4 |
| `pgai-reschedule_appointment-1790133443` | Reschedule | 2:51 | #1, #4, #6 |
| `pgai-cancel_appointment-1790134572` | Cancel | 2:22 | #4 |
| `pgai-medication_refill-1790135801` | Refill | 1:45 | #1, #7 |
| `pgai-refill_wrong_medication-1790136109` | Refill, vague medication | 1:45 | #1, #2, #7 |
| `pgai-office_hours_location-1790136859` | Hours, location, parking | 2:08 | #3, #6 |
| `pgai-insurance_question-1790137575` | Insurance | 2:38 | #2 |
| `pgai-weekend_request_edge_case-1790137888` | Edge: Sunday request | 3:21 | #5, #8, #9 |
| `pgai-interruption_edge_case-1790138325` | Edge: interrupting the agent | 3:24 | #3, #4, #5, #9 |
| `pgai-vague_unclear_request-1790138778` | Edge: vague request | 4:02 | #2, #3, #4, #9 |
| `pgai-frustrated_confused_patient-1790139247` | Edge: confused elderly patient | ~3:30 | #4, #9 |
