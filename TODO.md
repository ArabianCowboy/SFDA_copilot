# TODO

Known problems found but deliberately not fixed in the commit that found them,
usually because the fix reaches further than the work in hand. Each entry says
what is wrong, how it was found, and what fixing it would disturb — so the next
person can judge the cost rather than rediscover it.

---

## Arabic readers get no chat history on the non-streaming path

**Where:** `_truncate_chat_history` in `web/api/app.py` (~line 245), against
`MAX_SESSION_CHAT_HISTORY_CHARS = 3_500`.

**What is wrong.** The cap is measured with `json.dumps(truncated_history)`,
which defaults to `ensure_ascii=True` and escapes every non-ASCII character to
`\uXXXX` — six characters where the reader typed one. A single Arabic
question-and-answer pair of ~950 characters measures ~4,700 against a 3,500
budget, so the `while` loop drops the oldest pair, measures again, and keeps
going until the list is empty. The Arabic reader does not get a shortened
history; they get **none**.

Measured directly:

```
actual characters in one pair:            948
json.dumps length (what the cap measures): 4704
json.dumps(..., ensure_ascii=False):       1019
```

**Who it reaches.** Only `/api/chat`, the blocking fallback — the path a browser
without streaming bodies takes. `/api/chat/stream` keeps its history in the
`ConversationStore` and is unaffected. So this is invisible on a current desktop
browser and total on an old one, which is why it went unnoticed.

**How it was found.** Not by a bug report. A cookie-size guard added alongside
the New chat undo work (`test_a_set_aside_history_still_fits_in_the_session_cookie`)
was parametrised over English and Arabic, and the Arabic case could not reach
its own precondition — the history it built came back empty.

**The fix, and why it was not made here.** Measuring with
`ensure_ascii=False` is a one-line change and is almost certainly right: the
budget is meant to bound the session cookie, the cookie is compressed and signed
after this point, and `ensure_ascii` affects neither. But it silently changes how
much history *every* reader is handed on the main chat path — more turns of
context per question, in both languages — which is a behavioural change to the
product's answers, not a bug fix. It wants its own commit, its own before/after
on answer quality, and a decision on whether 3,500 is still the right number once
it means what it says.

**When it is fixed:** add an Arabic case to the blocking-path history tests in
`web/tests/test_new_chat.py` — an Arabic exchange should survive a round trip
through the session at all, which today it does not.

---

## The session cookie can be blown by one history of low-entropy content

**Where:** `MAX_SESSION_CHAT_HISTORY_CHARS = 3_500` in `web/api/app.py`, applied
by `_truncate_chat_history` (and by `_truncate` in
`web/services/conversation_store.py`).

**What is wrong.** The cap counts **JSON characters**, but the thing that has to
fit is the **serialized, signed, compressed session cookie**, and browsers
silently drop a cookie over ~4,093 bytes. Losing the cookie costs the reader
their *session*, not just their history. Prose compresses ~3x so a 3,500-char
history lands around 1KB and nobody notices — but content that compresses badly
does not, and this product invites it: a pasted table of batch numbers,
submission IDs, signed URLs, OCR output, a list of product codes.

Measured with incompressible content, one history produced a **4,544-byte**
cookie and Werkzeug logged `the 'session' cookie is too large`.

**Who it reaches.** `/api/chat` only, the blocking fallback — the streaming path
keeps history server-side.

**What this is NOT.** It is not caused by the New chat undo work. Setting a
history aside was made cookie-neutral by `/api/chat` dropping
`prev_chat_history` whenever it records a turn, so the cookie carries at most
one history at any moment — pinned by
`test_the_cookie_never_carries_two_histories`. This entry is the *pre-existing*
single-history case underneath that.

**The fix.** Bound the serialized session rather than the JSON string: either
measure what the session interface will actually emit and trim until it fits, or
stop keeping blocking-path history in the cookie at all and give `/api/chat` the
same server-side `ConversationStore` the streaming path uses. The second is the
better shape and removes this whole class of problem — `adopt_cookie_history`
already exists for exactly that migration — but it changes where the blocking
path's memory lives, so it wants its own commit.
