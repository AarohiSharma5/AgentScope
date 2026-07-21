# Cold outreach kit

A short, honest playbook for emailing people to look at the AgentScope demo and
give feedback. The goal is **a reply with insight**, not a signup. Keep it short,
make the ask tiny, and ask specific questions.

Before you send: replace `DEMO_URL` with your live demo link and `REPO_URL` with
your GitHub URL.

---

## Who to email

People who feel the pain today:
- engineers shipping LLM/agent features (they debug prompts, tokens, cost, latency)
- teams already using LangChain / LlamaIndex / OpenTelemetry
- folks who've posted/tweeted/asked about "LLM observability", "tracing agents",
  "prompt debugging", or complained about a competitor's price/complexity.

Personalize the first line to *why you picked them* — one specific detail (a repo,
a post, a talk). Generic blasts get ignored.

---

## Email #1 — the first touch

**Subject lines (pick one, keep it lowercase-ish and specific):**
- `quick look? open-source tracing for LLM apps`
- `built a devtools-style tracer for agents — 60-sec demo`
- `feedback on an AI observability tool?`

**Body:**

> Hi {name},
>
> I saw {specific detail — your post on X / your repo Y / your talk on Z}, so you
> probably feel this: when an LLM/agent app misbehaves, it's painful to see *what
> actually happened* — the prompts, retrieved context, tool calls, tokens, cost
> and latency.
>
> I built **AgentScope**, an open-source "Chrome DevTools for AI apps" that
> captures all of that. There's a live demo you can click through in under a
> minute — no signup, nothing to install:
>
> **DEMO_URL**
>
> I'm not selling anything — it's open source (REPO_URL) and I'm trying to learn
> whether it's actually useful. If you have 2 minutes, I'd love your take on:
>
> 1. Do you trace your LLM/agent calls today? With what — and what do you hate about it?
> 2. Looking at the demo, what's the one thing that would make you actually use it?
> 3. What's missing that would be a dealbreaker for your stack?
>
> Even a one-line reply would genuinely help. Thanks!
>
> — {your name}

**Why it works:** specific opener, tiny ask ("2 minutes", "one line"), no-signup
demo, explicitly not selling, and three sharp questions that surface real signal
(current tool + pain, activation trigger, dealbreaker).

---

## Email #2 — follow-up (only if no reply, ~4–5 days later)

> Hi {name}, quick bump in case this slipped by. No worries if it's not relevant —
> just one question if you have a sec: **do you currently trace your LLM calls,
> and if so with what?** That alone tells me a lot. Demo's still here: DEMO_URL

Send **one** follow-up, then stop.

---

## The three questions (why these)

- **"Do you trace today, with what, what do you hate?"** → tells you the real
  competitor and the actual pain. This is the highest-signal question.
- **"One thing that would make you use it?"** → your activation trigger / wedge.
- **"What's a dealbreaker for your stack?"** → the gap that blocks adoption
  (a missing integration, self-host requirement, data-residency, price, etc.).

Log every answer in a spreadsheet. After ~15–20 replies, patterns will tell you
what to build next far better than guessing.

---

## Tips

- Send from a real personal address, plain text, no images/tracking pixels.
- 5–8 sentences max. If they have to scroll, you've lost.
- Batch 10–20 personalized emails at a time; measure reply rate, iterate on the
  subject line and opener.
- If someone engages, offer a 15-min call — that's where the deepest insight is.
