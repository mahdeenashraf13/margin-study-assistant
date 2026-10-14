# Margin: AI Study Assistant

Turns lecture notes or PDFs into multiple-choice quizzes with the Claude API, then **checks every question against the source** so you can trust it.

**Stack:** Python/Flask, Anthropic API, SQLite, pypdf, vanilla JS, pytest, GitHub Actions

## What makes it more than a prompt wrapper
- **Chunking:** long documents are split on paragraph boundaries (3,000 chars, 200-char overlap) so no single call exceeds the context budget; input is capped at 60k chars / 10 chunks to bound cost
- **Structured output:** the model returns JSON; each card is schema-validated (4 distinct choices, valid answer index) and fenced/invalid output is retried once
- **Evaluation step:** a second grader call per chunk decides whether each question is *answerable from the passage* and whether the marked answer is *correct*. Failures are flagged "Needs review" with a reason, and a failed check never blocks the deck
- **Edit / regenerate / delete** individual cards; regeneration reuses the original source chunk and avoids repeating the old question
- **Prompt-injection hygiene:** the passage is wrapped in tags and the model is told to ignore instructions inside it
- LLM calls are mocked in tests, so the 6 tests run free and offline

## Run locally
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest -q
export ANTHROPIC_API_KEY=sk-ant-...      # from console.anthropic.com (Windows: set ANTHROPIC_API_KEY=...)
flask --app app run
```
Optional: `ANTHROPIC_MODEL` overrides the default model (`claude-sonnet-5-5`).

## Deploy
Same as the Finance Tracker (Render, Docker runtime). Add `ANTHROPIC_API_KEY` as a secret env var. **Never commit the key.** Before sharing a public link, add rate limiting or a login, because anyone who finds the URL can spend your API credits.

## Measuring quality (great interview material)
Run the verifier over ~50 generated questions, hand-label them, and report agreement and the share flagged. Put the numbers here.

## Next steps
User accounts, spaced repetition scheduling, concurrent chunk processing, streaming progress to the UI
