# Bug Report: Pivot Point Orthopedics AI Agent

Tested with 12 automated voice calls to +1-805-439-8008 on September 22, 2026, all placed from
+1-920-551-5133 by the LiveKit pipeline bot in this repo (one call per scenario). Each call has a
recording (`recordings/<call>.mp3`) and a transcript (`transcripts/<call>.txt`). Timestamps are
`[mm:ss]` from the transcript and line up with the MP3 to within about a second.

Findings are about the agent's *behavior*: what it did, booked, or said it would do. Our own
speech-to-text sometimes mishears names (provider names come out spelled several different
ways), so name spellings in transcripts are **not** reported as bugs. The agent's earlier calls
with this test patient left appointments on file, so a few findings compare what the agent says
across calls placed minutes apart.

## Summary

| # | Bug | Severity | Reproduced |
|---|-----|----------|------------|
| 1 | "Transfer to a person" plays a test-line goodbye and hangs up | High | 4 of 4 transfers |
| 2 | Correct date of birth rejected, then accepted anyway "for demo purposes", with full access to the chart | High | 3 of 12 calls |
| 3 | Books appointments when the clinic is closed (Wednesday mornings) | High | 2 calls |
| 4 | The agent's list of a patient's appointments changes between calls; double bookings are never flagged | Medium-High | 4 calls |
| 5 | Can't find the patient's record even with correct name and DOB | Medium-High | 1 call |
| 6 | Availability contradicts itself: an urgent patient is told "nothing for 2+ weeks", another gets a next-day slot | Medium | 4 calls |
| 7 | Clinic location changes between calls (Nashville vs. "only one location, in Austin") | Medium | 3 calls |
| 8 | Refill requests hit a dead end with no fallback | Medium | 2 calls |
| 9 | Treats a doctor it has no record of as real and puts the patient on "his" waitlist | Medium | 1 call |
| 10 | Can't answer "do you accept my insurance?" | Low-Medium | 1 call |
| 11 | Minor: drops the patient's middle name and re-asks for spelling; talks over the caller | Low | several |

---

## 1. "Transfer to a person" plays a test-line goodbye and hangs up
**Severity:** High. It's the only escalation path the agent offers, and it fails every time.

**Calls:**
- `pgai-medication_refill-1790141898` at 01:22-01:35
- `pgai-refill_wrong_medication-1790142014` at 01:20-01:37
- `pgai-reschedule_appointment-1790141473` at 04:50-05:00
- `pgai-weekend_request_edge_case-1790142573` at 03:00-03:13

**What happened:** When the agent can't solve the problem, it offers to connect the caller to
"our patient support team" or "someone at the clinic". The patient accepts, the agent says
"Transferring you now. Thank you.", and the call plays *"Hello. You've reached the Pretty Good AI
test line. Goodbye."* and disconnects. In every case the patient's problem was unresolved (no
refill, no reschedule slot, no appointment), and the patient is left saying "Wait, hold on, what?"

**Expected:** Transfer to a real queue or voicemail, or, if no human is available, say so and
offer a callback or message *before* ending the call. Never play an internal test message to a
patient.

## 2. Correct date of birth rejected, then accepted anyway "for demo purposes"
**Severity:** High. Identity verification in a healthcare context is both unreliable and bypassable.

**Calls:**
- `pgai-medication_refill-1790141898` at 00:56, then opens the chart at 01:03
- `pgai-insurance_question-1790142292` at 00:59, then texts a link and opens a billing case (02:09-03:34)
- `pgai-vague_unclear_request-1790143073` at 00:50, then reads out three appointments with dates and doctors (03:25)

**What happened:** The patient gives the date of birth on the test account (February 16, 1995,
confirmed correct). In 3 of 12 calls the agent replied *"The birthday doesn't match our records,
but for demo purposes, I'll accept it."* The same DOB was accepted without comment in the other
9 calls, so the check is inconsistent. After the failed check the agent carries on with full
access: it reviews the medication list, sends a link to the phone number on file, and reads out
the patient's upcoming appointments and doctors.

**Expected:** A correct DOB should always verify. A failed check should block access to chart,
insurance and appointment details (retry, or escalate to staff). "For demo purposes" is internal
behavior that patients should never hear.

## 3. Books appointments when the clinic is closed (Wednesday mornings)
**Severity:** High. Patients would show up to a closed clinic. This is the same class of bug as
booking a Sunday.

**Calls:**
- Hours stated: `pgai-office_hours_location-1790142130` at 00:40 ("Wednesday from 12PM to 7PM")
  and 01:18 (*"We open at 12PM on Wednesdays. So we are not available for early morning
  appointments that day."*)
- `pgai-interruption_edge_case-1790142783` at 02:23-03:27: offers and books **Wednesday Sept 23,
  8:15 AM**. The patient already had Wednesday 8 AM and 9 AM appointments (01:52).
- `pgai-frustrated_confused_patient-1790143385` at 02:38-03:37: offers "morning openings at 9AM,
  9:30AM, and 10AM" and books **Wednesday Sept 30, 9 AM**.

**What happened:** The agent states the rule correctly when asked directly, but its booking flow
ignores it and books Wednesday slots three to four hours before opening.

**Expected:** Only offer slots inside the clinic's stated hours.

## 4. The agent's list of a patient's appointments changes between calls
**Severity:** Medium-High. Patients get wrong information about their own bookings, and
conflicting bookings pile up.

**Calls, in order:**
1. `pgai-reschedule_appointment-1790141473` at 02:07: *"The only appointment I see on file is for
   Thursday, September 24 at 10:30AM."*
2. `pgai-interruption_edge_case-1790142783` at 01:52, about 22 minutes later: *"You have three
   upcoming appointments on file"*: Wed Sept 23 8 AM, Wed Sept 23 9 AM, and Thu Sept 24 2 PM.
   None of these were mentioned in the reschedule call.
3. `pgai-simple_scheduling-1790140870` (02:51-03:15) and `pgai-frustrated_confused_patient-1790143385`
   (01:34-03:37) search for and book new appointments without mentioning any of the existing ones.
   The interruption call even calls one of them *"an acute appointment booked for your knee"*
   (01:28), the same complaint the patient called about in the simple-scheduling call.

**What happened:** Depending on the call, the agent reports one appointment or three for the same
patient. It keeps two appointments on the same morning with two different doctors, and adds more
without flagging the overlap.

**Expected:** Every call should see the same, complete list. Before booking, check the patient's
existing appointments and ask whether this is a new visit or a change.

## 5. Can't find the patient's record even with correct name and DOB
**Severity:** Medium-High. The patient is locked out, and the only way forward is bug #1.

**Call:** `pgai-weekend_request_edge_case-1790142573` at 02:25-02:39

**What happened:** The agent misheard the last name as "Pinay Palle" (01:18) and the exchange got
confused. (Our bot's replies at 01:29-01:51 didn't help: it questioned its own, correct phone
number. That's fixed now.) At 02:25 the patient spelled the full name letter by letter and gave the
correct DOB, and the agent replied *"I'm unable to find your record in our system."* The same
name and DOB found the record in every other call that day. The agent then offered the broken
transfer, and the patient never got to ask about Sunday.

**Expected:** Match the record on name + DOB (or the caller's number, which the agent read back
correctly at 01:46).

## 6. Availability contradicts itself between calls
**Severity:** Medium. An urgent patient was sent away with no appointment.

**Calls:**
- `pgai-simple_scheduling-1790140870` at 02:51 and 03:15: the patient with **urgent** knee pain
  hears *"no open slots available through next Tuesday"*, then *"still no open slots"* after
  that. The call ends with only a promised callback.
- `pgai-interruption_edge_case-1790142783` at 02:23, about 30 minutes later: *"The next opening…
  is Wednesday, September 23, at 08:15AM"*, which is tomorrow.
- `pgai-scheduling_specific_doctor-1790141266` at 01:56: *"I do see several follow-up slots with
  doctor Hauser."*
- `pgai-frustrated_confused_patient-1790143385` at 01:36-02:05: no openings "in the next week",
  then Wed Sept 30.

**Expected:** Consistent availability. An urgent patient should be offered the same near-term
slots other callers get.

## 7. Clinic location changes between calls
**Severity:** Medium. Patients could go to the wrong city.

**Calls:**
- `pgai-reschedule_appointment-1790141473` at 01:40: the appointment is *"at Nashville. Two two
  zero Athens Way."*
- `pgai-interruption_edge_case-1790142783` at 02:26 and 03:27: the new appointment is *"in
  Nashville"*.
- `pgai-office_hours_location-1790142130` at 01:59: *"1234 Recovery Way, Suite 200, Austin, Texas
  78701. We only have this one location in Austin. There is no Nashville office."*

**Notes:** "1234 Recovery Way" also looks like placeholder data, and neither city matches the
clinic's 805 (California) phone number.

## 8. Refill requests hit a dead end with no fallback
**Severity:** Medium. A patient who is almost out of medication leaves with nothing.

**Calls:**
- `pgai-medication_refill-1790141898` at 01:03-01:22
- `pgai-refill_wrong_medication-1790142014` at 00:57-01:20

**What happened:** The agent says *"I don't see any medications on your chart that I can refill"*
and its only offer is the broken transfer (bug #1). It never asks for the medication name, dose,
prescriber or pharmacy, even when the patient describes it vaguely ("the white pill for my
shoulder"), and it never offers to send a refill request to the provider.

**Expected:** Collect medication, dose and pharmacy, and create a refill request or message for the
care team, with an expected response time.

## 9. Treats a doctor it has no record of as real
**Severity:** Medium. The patient waits for an appointment that may never exist.

**Call:** `pgai-scheduling_specific_doctor-1790141266` at 01:56-03:05

**What happened:** The patient asks for "Dr. Whitfield", a name the scenario made up. The providers
the agent names in other calls are Drs. Hauser, Lukowski, Noble and Bricker. The agent never says
it doesn't recognize the name. It answers *"Doctor Whitfield does not have openings in the next
week"*, refers to "his next available appointment", and finally *"I'll make a note to add you to
the wait list for doctor Whitfield"*.

**Expected:** Say the clinic has no provider by that name, and list the providers it does have.

## 10. Can't answer "do you accept my insurance?"
**Severity:** Low-Medium.

**Call:** `pgai-insurance_question-1790142292` at 01:17-02:09

**What happened:** The patient asks whether the clinic accepts Blue Cross Blue Shield PPO. The agent
asks for the member ID, says *"We don't have any insurance on [file]"*, and then *"I can't check
insurance acceptance directly on this call"*. It offers a text link and a billing callback instead.
A yes/no question about a major plan should be answerable on the call.

## 11. Minor issues
- **Drops the middle name and re-asks for spelling:** the agent reads the name back as "Asher Palle"
  and asks the patient to spell it (`simple_scheduling` 00:57, `scheduling_specific_doctor` 00:56,
  `reschedule_appointment` 01:07), even after the patient has just said the full name.
- **Talks over the caller:** `insurance_question` at 01:01 and 01:39, `vague_unclear_request` at
  00:51-00:58, and `simple_scheduling` at 02:24-02:35. The agent starts a new sentence while the
  patient is mid-sentence, and the patient has to ask it to repeat.

---

## What the agent handled well
- **Clear answers on hours, Saturdays and parking** (`office_hours_location`, 00:40-02:13).
- **Correctly rejected a made-up appointment.** The reschedule scenario claims a Thursday 2 PM
  appointment; the agent said it isn't on file and offered to move the real one
  (`reschedule_appointment`, 02:07).
- **Patient with a confused caller.** It repeated dates and names each time it was asked
  (`frustrated_confused_patient`).
- **Handled interruptions.** "Actually, wait…" mid-turn didn't derail it (`interruption_edge_case`, 01:11).
- **Offered a waitlist** when the requested provider had no openings (`scheduling_specific_doctor`, 02:43).

## Calls in this submission

| Call | Scenario | Length | Key findings |
|------|----------|--------|--------------|
| `pgai-simple_scheduling-1790140870` | New-patient scheduling (urgent) | 4:02 | #4, #6, #11 |
| `pgai-scheduling_specific_doctor-1790141266` | Specific (made-up) doctor | 3:17 | #6, #9, #11 |
| `pgai-reschedule_appointment-1790141473` | Reschedule | 5:00 | #1, #4, #7 |
| `pgai-cancel_appointment-1790141784` | Cancel | 1:45 | — (worked) |
| `pgai-medication_refill-1790141898` | Refill | 1:42 | #1, #2, #8 |
| `pgai-refill_wrong_medication-1790142014` | Refill, vague medication | 1:42 | #1, #8 |
| `pgai-office_hours_location-1790142130` | Hours, location, parking | 2:24 | #3, #7 |
| `pgai-insurance_question-1790142292` | Insurance | 3:46 | #2, #10, #11 |
| `pgai-weekend_request_edge_case-1790142573` | Edge: Sunday request | 3:15 | #1, #5 |
| `pgai-interruption_edge_case-1790142783` | Edge: interrupting the agent | 3:56 | #3, #4, #6, #7 |
| `pgai-vague_unclear_request-1790143073` | Edge: vague request | 4:53 | #2, #4, #11 |
| `pgai-frustrated_confused_patient-1790143385` | Edge: confused caller | 4:05 | #3, #4, #6 |
