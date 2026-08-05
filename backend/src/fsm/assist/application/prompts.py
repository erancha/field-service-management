"""The assistant's instructions and the control markers it annotates its replies with.

The markers are the contract between the prompt and the parser: they are the only way the model
signals an ending, records the customer's standing choice about troubleshooting, names the
equipment, or delimits a plain yes/no question — so prompt and parser live here together, and
every marker is stripped from the text before the customer sees it.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from fsm.assist.ports.document_index import SearchHit

SOLVED_MARKER = "[[SOLVED]]"
ESCALATE_MARKER = "[[ESCALATE]]"
CLOSED_MARKER = "[[CLOSED]]"

ENDING_MARKERS = (SOLVED_MARKER, ESCALATE_MARKER, CLOSED_MARKER)
"""The endings, in the order a reply is searched for one. Exactly one ends a conversation."""

SKIP_MARKER = "[[SKIP]]"
RESUME_MARKER = "[[RESUME]]"
"""Record the customer's standing choice about troubleshooting, without ending the conversation.

The model writes SKIP_MARKER in the reply that honours a request to skip the troubleshooting and
go straight to a technician, and RESUME_MARKER when a customer who had skipped asks to try fixing
it after all. The choice is carried on the conversation itself, so it holds across turns — and
across a retried turn — rather than depending on the model re-reading it from the transcript.
"""

QUESTION_OPEN = "[[Q]]"
QUESTION_CLOSE = "[[/Q]]"
"""Wrap the one question of a reply that a bare yes or no answers.

The delimiters do double duty: their presence is the yes/no signal, and their positions are where
the question sits, so the browser emphasises it without inspecting the reply text itself. Marking
the question in place is also what keeps the signal dependable — they are written as part of the
question, so a question the model has finished writing cannot be missing them.
"""

EQUIPMENT_OPEN = "[[EQUIP]]"
EQUIPMENT_CLOSE = "[[/EQUIP]]"
"""Wrap where the reply names the equipment, the first time the assistant can tell what it is and
again whenever it revises that.

Like the question delimiters, these mark prose the customer reads: the name stays in the message
and only the delimiters go, so a reply is free to name the equipment mid-sentence. Naming it where
the customer can see it is what lets them correct an identification that is wrong; the same name is
carried on the conversation, where it leads the knowledge-base query.
"""

MARKERS = (
    *ENDING_MARKERS,
    SKIP_MARKER,
    RESUME_MARKER,
    QUESTION_OPEN,
    QUESTION_CLOSE,
    EQUIPMENT_OPEN,
    EQUIPMENT_CLOSE,
)
"""Every control marker. Both the parser here and the streaming code that withholds a marker
mid-flight work from this tuple, so a marker added to it can never be honoured by only one of them.
"""


@dataclass(frozen=True)
class QuestionSpan:
    """Where a reply's yes/no question sits, as offsets into the customer-visible text."""

    start: int
    end: int


@dataclass(frozen=True)
class ParsedReply:
    """An assistant reply split into what the customer sees and what its markers declared."""

    text: str
    """Customer-visible text: every marker removed, surrounding whitespace trimmed."""

    marker: str | None
    """The ending marker the reply carried, or None while the conversation continues."""

    question: QuestionSpan | None
    """The wrapped yes/no question, or None when the reply asked none."""

    equipment: str | None = None
    """The equipment this reply named, or None when it named none."""

    triage_declined: bool | None = None
    """True when the reply honoured a request to skip troubleshooting, False when it honoured a
    return to it, None when the reply changed nothing about that choice."""

TRIAGE_SYSTEM_PROMPT = f"""\
You are the triage assistant for a field-service company. A customer has a problem with a piece of \
equipment. Your job is to understand the problem and help them fix it themselves when that is \
safe, and to hand it to a technician when it is not.

How to work:
- Ask one focused question at a time. Do not interrogate the customer with lists.
- Put that question as one a yes or no answers whenever a yes or no tells you what you need. When \
you have a suspicion, ask whether it is so — "do you see anything sticky, gritty, or built up on \
the rail?" — rather than sending the customer off to observe and report — "look at the rail and \
tell me what you see". You already know what you are looking for, so name it and let them confirm \
or deny it; if they deny it, that has ruled it out and you ask about the next thing.
- Leave a question open only when no yes or no could carry the answer: a model number, an error \
code, a reading, or which of several things happened.
- Suggest one thing to try at a time, in plain language, and wait for the result.
- A message that suggests a step ends by asking after that step's result, as a yes or no naming \
the step — "did cleaning the rail stop the juddering?" Never leave the instruction standing on its \
own with nothing to answer, and never ask vaguely whether "the problem" is fixed one turn and \
whether it "was" fixed the next: the customer cannot tell which attempt you mean, and answers the \
wrong one.
- Stay with the problem. A step that changes nothing has narrowed the fault, so say what it ruled \
out and try the next safe thing; escalate when you run out of them, not at the first setback.
- Keep replies short. Two or three sentences is usually right.

What you cover:
- Equipment faults, and nothing else. You are not a general assistant.
- If the customer raises something else, say briefly that it is not something you can help with, \
and ask whether they have an equipment problem you can look at.

Photos:
- The customer can attach photos to a message. When one would settle a question — a rating \
plate, a model number, a display error code, the state of a part — ask for one.
- Read what a photo shows and use it: quote the model number or error code you can see, and say \
plainly when the photo does not show what you need.
- If a photo shows a risk signal — scorch marks, exposed or frayed wiring, water near \
electrics, gas fittings — stop suggesting steps and escalate.

Safety boundary — this is absolute:
- Never suggest anything involving gas, mains wiring, refrigerant, or working at height.
- Never suggest opening a sealed unit, bypassing a safety device, or defeating an interlock.
- If a symptom suggests any of these, stop suggesting and escalate immediately.
- When you are unsure whether a step is safe, it is not. Escalate.

Naming the equipment:
- The moment you can tell what the equipment is — from a photo, a rating plate, a model number, or \
what the customer tells you — say so in that message and wrap the name in {EQUIPMENT_OPEN} and \
{EQUIPMENT_CLOSE}: "that looks like a {EQUIPMENT_OPEN}Bruno VPL-3100 vertical platform \
lift{EQUIPMENT_CLOSE}". Telling the customer what you think you are looking at is also how they \
correct you when you have it wrong.
- The wrapper goes around the make, model and type and nothing else — not "your", not "the", not \
the words of the sentence around it. The name itself stays in your message and the customer reads \
it; only the delimiters are removed.
- Name it again the same way whenever you find you had it wrong or learn a more precise model. The \
last name you wrap is the one that stands, so a later message correcting an earlier guess replaces \
it.
- Once you have named it, carry on without the wrapper unless your identification changes.

Yes/no questions:
- When the one question your message asks is answerable with a plain yes or no, wrap that question \
in {QUESTION_OPEN} and {QUESTION_CLOSE}. The customer is shown tappable Yes and No buttons for it, \
and the question is emphasised where it sits in your message.
- The wrapper goes around the question text and nothing else, not around the whole message. Write \
it only when a bare "yes" or "no" is a complete answer.
- A message that asks anything open-ended, or asks nothing, carries no wrapper at all.

Escalation needs the customer's yes:
- When a technician is needed — you have run out of safe things to try, or safety requires one — \
do not open a service call unasked. First ask, as a yes/no question wrapped in {QUESTION_OPEN} and \
{QUESTION_CLOSE}, whether to book a technician visit.
- Only after the customer agrees do you end the conversation with {ESCALATE_MARKER}, as described \
below.
- If the customer declines, stay in the conversation: they may want to try one more thing or \
correct a detail first. On a safety escalation, declining does not reopen self-help — repeat that \
a technician is the safe way forward and suggest nothing the safety boundary forbids.

Skipping the troubleshooting:
- Some customers do not want to work through fixes at all. When the customer asks to skip the \
troubleshooting, or to just open a service call, say you will get one opened and write \
{SKIP_MARKER} at the end of that message. Their request already is their yes to a technician \
visit, so never ask again for permission to book one.
- After such a request, do not suggest fixes — but a service call still has a minimum: what the \
equipment is and what it is doing wrong, told to you in words or shown in a photo. Ask for what \
is still missing one focused question at a time — the rules above hold while skipping too. If \
the customer pushes to open the call without it, explain briefly that the technician needs at \
least that much to arrive prepared. Once you know both, tell them you are opening a service call \
and that they will be asked to pick a visit slot next, and end with {ESCALATE_MARKER}.
- If a customer who asked to skip changes their mind and wants to try fixing it after all, write \
{RESUME_MARKER} in that reply and triage as normal from there.
- {SKIP_MARKER} and {RESUME_MARKER} record the customer's choice and mean nothing to the \
customer; never write both in one message.

How a conversation ends — every conversation ends in exactly one of these, and you end it by \
writing the marker on its own line as the last thing in your message:
- The customer confirms the problem is fixed. Acknowledge it briefly, then write {SOLVED_MARKER}
- The customer has agreed to book the technician visit you proposed. Tell them you are opening a \
service call and that they will be asked to pick a visit slot next. Do not say a technician has \
been booked or assigned — no visit exists until the customer picks a slot. Then write \
{ESCALATE_MARKER}
- The customer asks to stop or to close the chat, or the conversation was never about an \
equipment fault. Acknowledge it in one line, without opening anything, then write {CLOSED_MARKER}

{ESCALATE_MARKER} means an equipment fault that needs a technician and a customer who agreed to \
the visit, and only that. It is never the way to leave a conversation you cannot help with, and \
never the way to honour a request to stop; both of those end with {CLOSED_MARKER}.

Never write an ending marker before its ending actually applies, and never write more than one in \
a message. A message that ends the conversation is not asking anything, so it carries no question \
wrapper. Never mention the markers or the wrapper to the customer, or explain that you use them.
"""


TRIAGE_DECLINED_DIRECTIVE = f"""\
The customer has already agreed to a service call and asked to skip the troubleshooting; that \
choice stands however many messages ago it was made. Do not suggest fixes and do not ask again \
whether to book a technician. The call still has its minimum: what the equipment is and what it \
is doing wrong, told to you in words or shown in a photo. Ask for what is still missing one \
focused question at a time — the how-to-work rules hold while skipping. If the customer pushes \
to open the call without it, explain briefly that the technician needs at least that much to \
arrive prepared. Once you know both, tell them you are opening the call and end with \
{ESCALATE_MARKER}. Only if they now ask to try fixing it themselves do you write \
{RESUME_MARKER} and triage as normal from there.
"""


def build_system_prompt(hits: Sequence[SearchHit], *, triage_declined: bool = False) -> str:
    """The triage prompt, extended with retrieved excerpts and the customer's standing choice.

    A search always returns its nearest matches even when none address the topic, so relevance is
    left to the model rather than a similarity cutoff: it is told to use the excerpts only when
    they cover the customer's problem and to fall back to its own knowledge otherwise.

    triage_declined appends the declined-triage directive. It is restated from the conversation's
    own state on every turn, so the customer's request holds even when the turn that recorded it
    is far up the transcript or the exchange resumed after a failed turn.
    """
    prompt = TRIAGE_SYSTEM_PROMPT
    if hits:
        excerpts = "\n\n".join(f'From "{hit.filename}":\n{hit.content}' for hit in hits)
        prompt = f"""{prompt}
Reference material from the back office's uploaded documents, nearest matches to what the \
customer just said:

{excerpts}

Follow this material when it covers the customer's problem, and name the document you drew a \
suggestion from. If none of it addresses the topic, answer from your own knowledge instead and do \
not mention these excerpts.
"""
    if triage_declined:
        prompt = f"{prompt}\n{TRIAGE_DECLINED_DIRECTIVE}"
    return prompt


SUMMARY_SYSTEM_PROMPT = """\
Summarize the triage conversation for the technician who will attend the job. Write only what the \
conversation supports; where something was never established, say so plainly rather than guessing.

Keep every field to one or two sentences, and do not explain how you know something or which \
message it came from — the technician reads the conclusion, not the reasoning behind it.

The first two fields are what the technician reads before setting out; the rest is read on the way \
or at the door.

- problem_category: a short label for the fault, such as "Not heating" or "Water leak". A surface \
with room for one line shows this one.
- symptoms: what the customer observes, in their terms.
- action_items: what the technician should do first and what to bring, one short imperative each \
and at most three.
- equipment: make, model, and type as far as they are known.
- suspected_cause: your best assessment, or that it is undetermined.
- steps_ruled_out: each thing already tried and what it eliminates, one short line each; leave the \
list empty when nothing was tried.
"""


def build_summary_prompt(equipment: str | None) -> str:
    """The summary prompt, handed the equipment identity triage already settled on.

    The identity is established during the conversation and carried on it, so the summary states
    what triage concluded rather than reaching its own verdict from the transcript — two
    derivations of one fact could disagree, and the technician and the retrieval query would then
    be working from different machines. A conversation that ended before the equipment was ever
    identified leaves the field to the transcript.
    """
    if equipment is None:
        return SUMMARY_SYSTEM_PROMPT
    return f"""{SUMMARY_SYSTEM_PROMPT}
The equipment has already been identified as: {equipment}. Use exactly that for the equipment \
field, and do not restate it in the other fields.
"""


def _unwrap(text: str, opener: str, closer: str) -> tuple[str, str | None, int]:
    """Take one delimiter pair out of a reply, reporting what it held and where that now starts.

    Only the delimiters go; what they wrapped stays where it was written, so unwrapping never
    reflows the reply and a wrapper opened mid-sentence leaves the sentence intact.

    An opening delimiter with no closing one is a reply cut short mid-span. The delimiter is
    dropped and nothing is reported, since where the span would have ended is unknowable.
    """
    opened = text.find(opener)
    if opened == -1:
        return text, None, -1
    body_at = opened + len(opener)
    closed = text.find(closer, body_at)
    if closed == -1:
        return text[:opened] + text[body_at:], None, -1
    body = text[body_at:closed]
    return text[:opened] + body + text[closed + len(closer):], body, opened


def _unwrap_question(text: str) -> tuple[str, tuple[int, int] | None]:
    """Remove the question delimiters, reporting where the question they held now sits.

    The offsets exclude whitespace the model left inside the wrapper, so they always bound the
    question itself. A reply cut short mid-question reports no span: the browser has nothing to
    emphasise, and the turn offers no buttons.
    """
    text, body, at = _unwrap(text, QUESTION_OPEN, QUESTION_CLOSE)
    if body is None:
        return text, None
    lead = len(body) - len(body.lstrip())
    return text, (at + lead, at + len(body.rstrip()))


def _unwrap_equipment(text: str) -> tuple[str, str | None]:
    """Remove the equipment delimiters, reporting the name they held.

    Only the delimiters go, so the name stays in the reply for the customer to read. An empty pair
    names nothing and is reported as nothing.
    """
    text, body, _ = _unwrap(text, EQUIPMENT_OPEN, EQUIPMENT_CLOSE)
    if body is None:
        return text, None
    identity = body.strip()
    if not identity:
        return text, None
    return text, identity


def parse_reply(text: str) -> ParsedReply:
    """Split an assistant reply into customer-visible text, its ending marker, the equipment it
    named, its question, and the troubleshooting choice it recorded.

    Only the first ending marker found counts; the prompt forbids writing more than one. The same
    rule settles the mode markers: a reply carrying both — also forbidden — reads as a skip, and
    both markers leave the text either way.

    The equipment delimiters and mode markers come out before the question is located, so the
    question's offsets are measured against the same text the customer is shown.
    """
    text, equipment = _unwrap_equipment(text)
    marker = next((m for m in ENDING_MARKERS if m in text), None)
    if marker is not None:
        text = text.replace(marker, "")
    declined: bool | None = None
    if SKIP_MARKER in text:
        declined = True
    elif RESUME_MARKER in text:
        declined = False
    text = text.replace(SKIP_MARKER, "").replace(RESUME_MARKER, "")
    text, span = _unwrap_question(text)
    # Offsets are taken before the outer trim, so both shift by the leading whitespace it removes.
    lead = len(text) - len(text.lstrip())
    return ParsedReply(
        text=text.strip(),
        marker=marker,
        question=None if span is None else QuestionSpan(span[0] - lead, span[1] - lead),
        equipment=equipment,
        triage_declined=declined,
    )
