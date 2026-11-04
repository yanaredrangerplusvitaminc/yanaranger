---
name: client-email-review
description: Review a draft client email or message against Ranger's client communication standards before it is sent. Use when someone pastes a draft to a client and asks to check it, review it, or make sure it follows our standards, especially when the message is about an issue, a delay or something not working. Reviews only; it does not write the email.
---

# Client email review

The writer drafts the message. This skill checks it against Ranger's client communication standards and returns specific flags with the reason for each. It does not rewrite the whole message or add new content.

## The standards

1. **Lead with what we're doing.** The opening shows we are on it: we noticed, we are monitoring, we are investigating, here is what's next. It does not open on the problem.
2. **No apologies.** No "sorry" in any form. In the worst cases, "we regret the delay" or "we regret the inconvenience", once at most.
3. **Neutral problem statement.** Describe the issue as a technical issue that exists. Don't name it as our fault, theirs, or the system's ("our mistake", "Ranger failed", "your documents").
4. **No naming emotions for the client.** Don't write "frustrating", "annoying", "disappointing", "stressful", "we know this has been hard". Once we name the feeling, it is the word they remember. Show care through action: "we're monitoring this closely", "this is our priority".
5. **Only promise what we control.** State what we know, what we're doing, and when they will hear from us next. Don't promise a fix date we can't keep. "We will update you by Thursday" is fine without a known fix.
6. **Calm, confident register.** No exclamation marks, no hype, no filler ("just circling back", "per my last email"). Short sentences.
7. **Written for this client.** It should read as a message to these people about their situation, not a generic template.

## How to review

1. Read the whole draft once for intent. Keep the facts the writer wants to convey. The standards change the form, never the substance.
2. Check each standard in order. For every issue, quote the exact phrase.
3. For each flag, suggest the smallest fix that keeps the writer's wording as close as possible.
4. Give the reason for every flag in one short clause, so the writer knows why, not just what.
5. If the draft passes a standard, don't mention it.

## Output format

Start with one line: **Ready to send**, or **N things to adjust**.

Then one numbered item per flag:

```
1. [Standard name]
   Phrase: "..."
   Suggest: "..."
   Why: ...
```

End with nothing else. No rewritten full email unless the writer asks for one.

## Word swaps

| Instead of | Use |
|---|---|
| We're very sorry | Drop it, or "We regret the delay" in the worst cases only |
| It has been frustrating for you | Drop it; say "We're monitoring this closely" |
| You've been running into a problem | We noticed a technical issue with... |
| Our mistake / Ranger failed to | A technical issue with... |
| We will fix it by [date] (not certain) | We will update you by [day] |
| We really appreciate your patience! | Thank you for your patience (no exclamation mark) |

## Example

Draft:
> We've noticed that you've been running into a problem where the system can't fetch certain information. We can see it has been frustrating, and we're very sorry for the extra effort. We'll get back to you as soon as possible!

Review:
> **4 things to adjust**
>
> 1. Lead with what we're doing
>    Phrase: "We've noticed that you've been running into a problem"
>    Suggest: "As part of monitoring your account closely, we noticed a technical issue with"
>    Why: it opens on our attention, not on their pain.
>
> 2. No naming emotions
>    Phrase: "We can see it has been frustrating"
>    Suggest: drop it
>    Why: naming the feeling makes it the word they remember.
>
> 3. No apologies
>    Phrase: "we're very sorry for the extra effort"
>    Suggest: drop it, or "We regret the delay" if the impact has been serious
>    Why: an apology frames the issue as our failure before we know the cause.
>
> 4. Only promise what we control / calm register
>    Phrase: "as soon as possible!"
>    Suggest: "We will update you by [day]."
>    Why: a dated update shows control even without a fix date; the exclamation mark reads as nervous.
