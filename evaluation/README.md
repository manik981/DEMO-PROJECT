# Evaluation

This folder contains a small, manually annotated evaluation of the live analysis pipeline. It exists to keep the
project honest: the numbers in the README and reports come from an actual run, not from estimates.

**The dataset is synthetic and tiny. These metrics are a smoke signal, not a benchmark.**

## Files

| File | Purpose |
|---|---|
| `ground_truth.json` | Manually annotated expected items for the synthetic RFP |
| `evaluate.py` | Runs the real pipeline, matches output, writes `results.json` |
| `results.json` | Last measured run (committed as evidence) |
| `last_run.log` | Local diagnostic log from the last run (gitignored) |

## Dataset

`sample_data/sample_rfp.pdf` — a four-page fictional RFP for a "Riverton" permit portal. It was written for this
evaluation and contains deliberate imperfections:

- 12 functional requirements;
- 9 non-functional requirements (some explicit, some omitted by the client);
- 7 technical items (explicit, suggested and unspecified);
- 9 missing-information topics;
- 5 ambiguities, including two contradictions;
- 5 risks;
- an embedded prompt-injection sentence;
- no cost, timeline or team-size information.

Ground truth lives in `ground_truth.json` with a `canonical` phrase and optional `aliases` per item.

## How to run

```powershell
# .env must contain a valid AGNES_API_KEY
python evaluation/evaluate.py
```

Options:

```powershell
python evaluation/evaluate.py --document path\to\file.pdf --ground-truth path\to\truth.json --threshold 0.42
```

The script calls the real API, prints progress, and writes `results.json`. It may wait 20–60 s between stages when the
provider reports a per-minute token limit. A run typically takes 40–120 s.

## Metric definitions

Items are matched greedily, one-to-one, by lexical similarity:

- tokenise lowercased text, drop stopwords and short tokens;
- compute token-set F1 between each ground-truth phrase/alias and each actual item;
- accept a pair at or above `--threshold` (default 0.42), highest scores first.

From the matches:

- **precision** = true positives / actual items;
- **recall** = true positives / ground-truth items;
- **F1** = harmonic mean.

Sections scored: functional, non-functional, combined requirements, missing information, technical requirements,
ambiguities and risks.

Citation verification is separate: every evidence-bearing item is checked for page existence and lexical evidence
overlap with that page's extracted text. It is **not** a semantic correctness check.

## Measured run — 2026-10-29 (previous `openai/gpt-oss-120b` / Groq default)

Model `openai/gpt-oss-120b`, direct mode, one run, 41.29 s, 9,931 tokens. Not re-run against `agnes-2.5-flash`:

| Metric | Precision | Recall | F1 |
|---|---|---|---|
| Requirements (overall) | 0.950 | 0.905 | 0.927 |
| Functional | 1.000 | 1.000 | 1.000 |
| Non-functional | 0.875 | 0.778 | 0.824 |
| Missing information | 1.000 | 0.667 | 0.800 |
| Technical | 0.857 | 0.857 | 0.857 |
| Ambiguities | 0.500 | 0.200 | 0.286 |
| Risks | 0.400 | 0.400 | 0.400 |

- Structured output valid: yes (1/1).
- Citation traceability: 23/34 (67.6 %).
- Missed requirements: `GT-NFR-02`, `GT-NFR-05`; one extra NFR was returned.
- Missed gaps: `GT-MI-01`, `GT-MI-06`, `GT-MI-07`.
- Ambiguities: only one of five matched; one unmatched ambiguity.
- Risks: two of five matched; three unmatched risks.

The full per-item matches, unmatched IDs and false positives are in `results.json`.

## Why the weak scores are plausible

- The findings prompt asks for all six sections in one response with a 30-word concision rule. Ambiguities and risks
  are the sections most likely to be compressed away.
- Lexical matching under-credits correct paraphrases. Some "false positives" may be valid risks phrased differently.
- One run gives no variance estimate; a second run could move these numbers materially.

## Limitations

- One synthetic document, one model, one run.
- Ground truth reflects one annotator's reading.
- Lexical matching is not semantic evaluation.
- The valid-structured-output rate is 1/1 by construction: a failed run writes no results.
- Results do not generalise to real RFPs, other languages, scanned documents or other models.

## What to do next

1. Add 5–10 anonymised real RFPs with human baselines.
2. Split ambiguity/risk extraction into a dedicated call and re-measure.
3. Report mean and spread over at least three runs.
4. Add a semantic citation check or human sign-off before treating citations as verified.
