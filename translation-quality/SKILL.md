---
name: translation-quality
description: >-
  Scores a translation line by line with the Vitra Universe API — accuracy,
  fluency, terminology and style — against the organization's translation
  memory and terminology, and returns an overall score, a pass/fail band and
  the worst lines with explained errors and a suggested better version. Use it
  whenever the user wants a translation reviewed or rated — "how good is this
  French translation?", "check our vendor's translations", "score these
  strings", "is this ready to publish?". Not for translating (document-
  translation, translation-memory) or market compliance (content-compliance).
compatibility: >-
  Python 3.10+, standard library only; outbound HTTPS to the Vitra API. Needs
  VITRA_UNIVERSE_API_KEY (a uvk_ key for one Vitra organization).
metadata:
  skill-author: Vitra.ai
  version: "1.0"
  display-name: Translation Quality
  category: Quality
  tags: Translation, Quality
  source: vitra
  added: "2026-09-26"
  updated: "2026-09-26"
---

# Translation Quality

Evaluates source → translation pairs and reports what's wrong, line by line.
The script prints **one line of JSON** and waits for the report.

## Step 0: Check access

```bash
python3 scripts/check_access.py
```

`ready`/`unknown`: continue. `blocked`: stop and tell the user which steps
their key can't do.

## Collect the inputs

| Input | Required | How |
|---|---|---|
| The pairs | yes | CSV/TSV (source, translation), JSON `[{"source","target"}]`, or two aligned files (`--source-file`, `--target-file`) |
| Languages | yes | Names or codes: `English`, `fr-FR` |
| Memory | when several fit | Its terminology is what "correct" means: `list_tms.py --target-language fr-FR`; ask if several |
| Domain / instructions | no | `--domain legal`, `--instructions "formal, for bank customers"` |

## Score ⏸

Confirm first: a report spends credits per source word.

```bash
python3 scripts/evaluate.py --pairs strings.csv --source-language English --target-language French \
  [--tm-name "<memory>"] [--domain marketing] [--show 10]
```

Report `score`, `band` and whether it `passed`, then the `worst` lines: each
with its errors (`severity`, `category`, `why`, `suggestion`) and a `better`
version when there is one. Summarize patterns ("terminology misses in 6
lines") rather than reading every error.

## Next steps worth offering

- Fix the source of repeated errors in the memory: the translation-memory
  skill's `correct_term.py`, with the user's approval.
- Re-translate the worst lines, then score again.

## Rules

- **Summaries over dumps.** Lead with the score and the patterns.
- **Ask before spending credits.** Show names, never ids.

## When something fails

Failures print `{"status": "failed", "error": {"code", "message", "retryable"}}`.
Explain `message` plainly; `retryable: true` → run the same command again.
`TM_CHOICE_NEEDED`: ask which memory (`choices`), then pass `--tm-name`.

| Exit | Meaning | Tell the user |
|---|---|---|
| 2 | API key not set | Show the setup lines the script printed |
| 3 | Key rejected or not allowed | Their Vitra admin must allow quality evaluation for their role |
| 4 | API error, a question, or no pairs found | Ask the question, or explain the message |
| 5 | Timed out | Still scoring: try again later |
| 6 | File not found | Ask for the right path |
