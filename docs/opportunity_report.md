# Opportunity Report — Cynbit AI Proposal Analyst

**Status:** independent MVP assessment, 29 October 2026
**Prepared for:** Cynbit Technologies (proposed, not commissioned)
**Disclaimer:** This is an independent prototype and analysis. It is not an official Cynbit product, and it is not
affiliated with or endorsed by Cynbit. Company facts below come only from Cynbit's public website, cited inline;
everything about internal process, costs or demand is an explicit hypothesis to validate.

---

## 1. Executive summary

Cynbit publicly positions itself around AI automation, autonomous agents, LLM-based document handling, custom
software and cloud delivery ([cynbit.in](https://www.cynbit.in/), [services](https://www.cynbit.in/services)). Its
sales motion therefore depends on reading prospective clients' requirements and turning them into a credible
technical response — repeatedly, under time pressure, with senior architects involved.

This MVP tests one narrow idea: an internal **AI Proposal Analyst** that reads an RFP, extracts evidence-backed
requirements, exposes gaps, ambiguities and risks, drafts clarification questions, and proposes a solution direction —
while refusing to invent costs, timelines or citations.

The working prototype demonstrates that the core loop is feasible on a free model tier (measured with the previous Groq
default): structured output validated,
a synthetic RFP analyzed end to end, and 23 of 34 citations traced back to extracted page text in a single measured
run. The weakest areas — ambiguity and risk detection — are exactly where senior judgement matters most, which
supports positioning the tool as analyst assistance rather than automation of the bid decision.

**Recommendation:** treat this as a pre-sales productivity experiment. Run it on past, anonymised RFPs, measure
time-to-first-draft and reviewer corrections, and only then decide whether it becomes an internal platform or a
client-facing product.

---

## 2. The problem

> Hypothesis: Cynbit's pre-sales work is document-heavy, senior-heavy and inconsistent between bids. Validate against
> real bid logs before investing further.

RFP response work typically involves:

- reading a long, inconsistently structured document and finding the actual requirements;
- separating what the client **stated** from what the responder **assumed**;
- spotting contradictions, missing operational details and unstated non-functional expectations;
- writing clarification questions before committing to architecture;
- producing an internal summary that delivery and leadership can trust.

The failure modes are familiar and expensive: a missed requirement becomes rework, an unstated assumption becomes a
commercial dispute, and a confident-sounding but unsupported claim damages credibility. Generic chatbots make this
worse because they produce fluent summaries without traceability.

The opportunity is not "summarise the PDF". It is **auditable triage**: every claim tied to a page, every inference
labelled, and every gap turned into a question.

---

## 3. Who feels it

| User | Job to be done | What success looks like |
|---|---|---|
| Pre-sales lead | Decide quickly whether a bid is worth pursuing | First-pass requirements and risks in minutes |
| Solution architect | Shape architecture without missing constraints | Gaps and NFRs surfaced before estimation |
| Delivery lead | Understand scope and ambiguity | Explicit vs inferred scope, clear questions |
| Founder / leadership | Compare opportunities | Consistent one-page summaries across bids |

These roles are inferred from how software services firms typically operate, not from Cynbit's internal org chart.
Confirm them before designing a rollout.

---

## 4. Why this fits Cynbit's public positioning

Cynbit's public site states that it builds autonomous AI agents, LLM automation for document handling, AI stack
integration, full-stack software, and cloud infrastructure on AWS and Azure
([services](https://www.cynbit.in/services)). It also lists a proprietary SaaS suite — Cynbit Studio, Revio and
TenantEase — and an education arm, BitElevate ([home](https://www.cynbit.in/), [products](https://www.cynbit.in/products)).

That makes an RFP analyst a credible **internal dogfood project**:

- it uses the same capabilities Cynbit sells (LLM automation, document handling, structured extraction);
- it produces reusable IP for pre-sales and delivery;
- it creates a reference story for clients considering similar document-automation work;
- it is small enough to validate without a platform team.

What the public site does **not** establish: bid volume, win rates, current tooling, team structure or willingness to
pay. Those are open questions in section 11.

---

## 5. Product concept

**One-line:** upload an RFP, get a validated, evidence-referenced analysis and a prioritized question list.

**Core loop**

1. Extract text in memory with page references (PDF, DOCX, TXT).
2. Ask the model for structured findings: summary, requirements, technical needs, gaps, ambiguities, risks.
3. Validate the response against a strict schema; repair once; fail clearly.
4. Ask a second, smaller model call for clarification questions, recommendations and complexity.
5. Audit every citation against the extracted page text.
6. Present an eight-tab dashboard and export Markdown or JSON.

**Deliberate non-goals**

- no cost, timeline, team-size or ROI guesses;
- no OCR;
- no auto-send to clients;
- no replacement for the bid/no-bid decision.

---

## 6. What the MVP actually delivers

| Capability | State |
|---|---|
| PDF / DOCX / TXT extraction with page map | Working |
| Ten analysis sections (A–J equivalent) | Working |
| Explicit vs inferred labelling | Working |
| Prompt-injection boundary and tag neutralisation | Working, tested |
| Long-document chunk + merge | Working, tested offline |
| Schema validation + one targeted bounded repair | Working, tested |
| Citation audit | Working; lexical, not semantic |
| Markdown / JSON export | Working |
| Live end-to-end run on a synthetic RFP | Working, measured |
| Offline test suite | 110 passing |

The measured run is documented in [`evaluation/README.md`](../evaluation/README.md). It is one synthetic document and
one run; treat the numbers as a smoke signal, not evidence of general accuracy.

---

## 7. Value proposition

**For the bid team**

- Faster first pass over a long document.
- Fewer missed requirements and unlabelled assumptions.
- Better clarification questions earlier, before architecture is committed.
- A consistent summary format across opportunities.

**For Cynbit as a business**

- Internal productivity and quality story.
- Reusable pattern for client-facing document automation.
- Demonstration of evidence-first AI engineering rather than chatbot wrappers.

**How to measure it (proposed, not yet measured)**

| Metric | How to collect | Target to agree |
|---|---|---|
| Time to first internal draft | Timestamp before/after rollout | Hypothesis: meaningful reduction; set after baseline |
| Reviewer corrections per analysis | Count edits in review | Downward trend |
| Requirement coverage vs human checklist | Sample audit | Set after baseline |
| Clarification questions accepted | Client/architect feedback | Set after baseline |
| Rework caused by missed requirements | Delivery retro | Downward trend |

No numeric targets are claimed here because no baseline exists. That is intentional.

---

## 8. Differentiation

Most "chat with your RFP" tools optimise for fluent output. This prototype optimises for **reviewability**:

1. **Schema-first**: the model cannot return free-form prose; every section is validated.
2. **Evidence-first**: claims carry page and quote, and citations are checked mechanically.
3. **Explicit vs inferred**: recommendations are never presented as client requirements.
4. **Bounded failure**: one repair attempt, then a clear error — no silent partial reports.
5. **No invented commercials**: cost, timeline and ROI are refused by design.
6. **Injection-aware**: document instructions are treated as data.

The honest weakness is recall on ambiguity and risk. A production version would need a stronger review workflow, not
just a better prompt.

---

## 9. Rollout options

**Option A — internal experiment (recommended first)**
Run on 5–10 anonymised past RFPs. Compare against the human analysis. Measure corrections and time. Low cost, low risk.

**Option B — internal pre-sales tool**
Add authentication, a document store, reviewer comments and an approval step. Integrate with the CRM only if the
experiment shows sustained use.

**Option C — client-facing product**
Only after B proves value. Would need multi-tenancy, retention controls, SSO, audit logs, SLA and a support model.

Sequencing matters: the current MVP has no auth, persistence or multi-tenancy, so B and C are real engineering
programmes, not configuration changes.

---

## 10. What would make this fail

- Reviewers do not trust the output and re-read the document anyway.
- The model misses a requirement that causes commercial damage.
- Confidential client documents cannot be sent to a third-party model provider.
- Free-tier rate limits make concurrent use impractical.
- The output is impressive but not actionable for architects.

Each of these is testable in Option A.

---

## 11. Open questions and hypotheses

| # | Question | Why it matters |
|---|---|---|
| 1 | How many RFPs per month, and who reads them? | Determines whether the tool saves meaningful time |
| 2 | What is the current time-to-first-draft? | Needed for any credible ROI claim |
| 3 | Which sections are most often missed today? | Focuses model and UX work |
| 4 | Are client documents permitted to leave Cynbit's environment? | May force a self-hosted or redacted workflow |
| 5 | Would architects trust labelled inferences? | Determines review design |
| 6 | Is the buyer internal (ops) or external (clients)? | Changes the roadmap entirely |
| 7 | Which languages and formats dominate? | Current MVP is English-centric, no OCR |

These are hypotheses, not findings. Answering them is the point of the pilot.

---

## 12. Recommendation

Proceed to a **small, instrumented internal pilot**, not a product launch.

1. Select 5–10 past RFPs; anonymise as needed.
2. Run the MVP and a human analyst on the same documents.
3. Record time, corrections, missed items and reviewer sentiment.
4. Review the citation failures (currently 11 of 34 flagged) and decide whether the audit needs semantic checking.
5. Only then choose Option A, B or C.

The MVP is strong enough to support that conversation and honest enough to show where it is weak.

---

### Sources

- Cynbit homepage — <https://www.cynbit.in/> (accessed 29 Oct 2026)
- Cynbit services — <https://www.cynbit.in/services> (accessed 29 Oct 2026)
- Cynbit products — <https://www.cynbit.in/products> (linked publicly; not independently audited)
- Cynbit case studies — <https://www.cynbit.in/case-studies> (linked publicly; not independently audited)

Company descriptions are paraphrased from public pages. No internal Cynbit information was used.
