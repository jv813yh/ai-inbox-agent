# ai-inbox-agent — Email AI Summary Bot

Runs daily via GitHub Actions. Reads unread Gmail, auto-detects content type from the email body, summarizes with Claude, sends results to Telegram, and saves `prepared_content.json` as a CI artifact.

---

## How It Works

Every unread email is processed. Content type is detected automatically from the body — no special subject required:

| Body contains | Logic |
|---|---|
| YouTube link | Fetch metadata (yt-dlp) + transcript (youtube-transcript-api) + Claude Opus detailed notes |
| GitHub link | Fetch repo info + README via GitHub API + Claude Opus detailed analysis |
| Neither | Claude Haiku summarizes the email in 3-5 bullet points |

The `EmailFilter` class still applies Gmail labels/stars based on subject keywords, but does **not** gate content extraction.

---

## File Structure

```
src/
  email_summary_bot_final.py   Main bot — Gmail IMAP, email loop, Telegram sending
  extractors_full.py           YouTubeExtractor, GitHubExtractor, ContentPreparator
  prompt_builder.py            Applies active prompt templates from prompts.py
  prompts.py                   All prompt strings — versioned + latest_* pointers
.github/workflows/
  email-summary.yml            CI workflow (cron + manual trigger)
```

---

## Prompt System

All prompts live in `prompts.py` as versioned constants:

```python
YOUTUBE_V1    = "..."
GITHUB_V1     = "..."
PLAIN_EMAIL_V1 = "..."

# Change these single lines to swap prompts everywhere
latest_youtube     = YOUTUBE_V1
latest_github      = GITHUB_V1
latest_plain_email = PLAIN_EMAIL_V1
```

`prompt_builder.py` reads only `latest_*` and handles data prep (truncation, context building) + `str.format()`. To add a new content type: add a constant in `prompts.py` + a method in `prompt_builder.py`.

---

## GitHub Actions Workflow

**Trigger:** Daily at 20:00 UTC / `workflow_dispatch` for manual runs.

**Required secrets:**

| Secret | Used as env var |
|---|---|
| `GMAIL_CREDENTIALS` | `GMAIL_CREDENTIALS` |
| `TELEGRAM_BOT_TOKEN` | `TELEGRAM_BOT_TOKEN` |
| `TELEGRAM_CHAT_ID` | `TELEGRAM_CHAT_ID` |
| `CLAUDE_API_KEY_GITHUB_EMAIL` | `CLAUDE_API_KEY` + `CLAUDE_API_KEY_GITHUB_EMAIL` |
| `SUPADATA_API_KEY` | `SUPADATA_API_KEY` |

**Timezone:** `TZ: Europe/Bratislava` set in workflow env.

**Artifact:** `src/prepared_content.json` uploaded after each run, retained 30 days.

---

## prepared_content.json Structure

```json
{
  "youtube": [
    {
      "type": "youtube_video",
      "url": "...",
      "title": "...",
      "detailed_notes": "...",
      "has_full_transcript": true,
      "transcript_preview": "...",
      "processed_at": "..."
    }
  ],
  "github": [
    {
      "type": "github_repo",
      "url": "...",
      "owner": "...",
      "repo": "...",
      "stars": 0,
      "forks": 0,
      "language": "...",
      "detailed_summary": "...",
      "processed_at": "..."
    }
  ],
  "plain_emails": [
    {
      "subject": "...",
      "from": "...",
      "date": "...",
      "summary": "..."
    }
  ],
  "emails_processed": 2,
  "timestamp": "2026-04-16T20:00:00"
}
```

---

## Server-local Hermes + AgentWiki mode

Use this mode when the bot should read Jozef's `learning` Gmail account on the server and write durable notes into HumanAgentWiki/Obsidian.

**Why local:** GitHub Actions cannot write to `/home/jozef/humanagentwiki/notes`, so AgentWiki persistence runs on the server via Hermes cron.

### Entry point

```bash
python3 src/server_runner.py --dry-run --max-emails 3
```

Real run:

```bash
python3 src/server_runner.py --max-emails 5
```

### Defaults

| Setting | Default |
|---|---|
| Gmail account | `learning` |
| OAuth token | `/home/jozef/.hermes/google_accounts/learning/google_token.json` |
| Gmail query | `in:inbox is:unread newer_than:30d (youtube OR youtu.be OR github.com OR subject:YouTube OR subject:GitHub)` |
| HumanAgentWiki notes | `/home/jozef/humanagentwiki/notes` |
| State DB | `/home/jozef/.hermes/state/ai-inbox-agent/processed.sqlite` |

### Behavior

- Reads all unread messages from the dedicated learning Gmail inbox (`in:inbox is:unread newer_than:30d`).
- Processes emails containing one link or a list of links: YouTube, GitHub, generic web pages/articles, blogs, newsletters, Substack, Medium, arXiv, and similar URLs.
- Long plain emails without supported links are summarized by default for the learning Gmail account; short/no-link emails are recorded as `skipped_unclassified` so they do not loop forever.
- Classifies notes into logical wiki folders (`Technologie`, `Investovanie`, `Produktivita`, `Biznis`, `Ostatne`) using deterministic host/keyword rules before falling back to `Ostatne`.
- Writes GitHub Markdown notes into:
  - `GitHub Projects/`
- Writes web article Markdown notes into:
  - `Web Articles/<classification>/<domain>/`
- Writes plain email Markdown notes into:
  - `Emails/<classification>/<YYYY-MM>/`
- Writes YouTube Markdown notes into topic/channel folders for later RAG/fine-tuning use:
  - `YouTube/Investovanie/<channel>/`
  - `YouTube/Technologie/<channel>/`
  - `YouTube/Ostatne/<channel>/`
- Adds RAG-friendly frontmatter metadata such as `domain`, `topic`, `channel_slug`, `dataset_use`, and `source_type`.
- Maintains per-domain YouTube index notes such as `Indexes/youtube-investovanie-index.md` and `Indexes/youtube-technologie-index.md`.
- Maintains article and email indexes:
  - `Indexes/web-article-index.md`
  - `Indexes/plain-email-index.md`
- Saves the Telegram/stdout digest into HumanAgentWiki for later retrieval:
  - `Daily Personal AI news/<YYYY-MM-DD>/<HHMM>/ai-inbox-agent.md`
- Maintains a local SQLite dedupe store so repeated links are not processed again. YouTube dedupes by `video_id`, GitHub by `owner/repo`, and web articles by canonical URL with tracking params stripped.
- Runs the HumanAgentWiki indexer after successful note writes.
- Marks email as read only after successful processing.
- Prints a Telegram-ready digest to stdout for Hermes cron delivery.

### Hermes cron wrapper

Server wrapper:

```bash
/home/jozef/.hermes/scripts/ai_inbox_learning_agent.sh
```

Recommended cron schedule after manual dry-run validation:

```text
every 2h
```

Do not create/push/merge GitHub changes or create cron jobs without Jozef confirmation.

---

## Known Issues & Notes

- **YouTube on CI:** yt-dlp is blocked by YouTube bot detection on GitHub Actions IPs. Transcripts use `youtube-transcript-api` instead. If a video has no captions, Claude summarizes using title + description only.
- **GitHub API rate limit:** Unauthenticated requests are limited to 60/hr. Add a `GITHUB_TOKEN` header in `get_repo_info()` if hitting limits.
- **Telegram message length:** Messages are split into 4096-char chunks automatically. All AI-generated content is HTML-escaped to prevent parse errors (`parse_mode: HTML`).
- **Email read status:** Emails are fetched with `BODY.PEEK[]` so they are **not** marked as read during processing.

---

## Fixes Applied (session history)

| # | Issue | Fix |
|---|---|---|
| 1 | Wrong script name in workflow | `email_summary_bot_apppassword.py` → `email_summary_bot_final.py` |
| 2 | Artifact path wrong | `prepared_content.json` → `src/prepared_content.json` |
| 3 | `upload-artifact` v3 deprecated | Upgraded to v4 |
| 4 | Wrong `sys.path` in bot | `os.path.dirname(__file__) + '..'` → `os.path.dirname(os.path.abspath(__file__))` |
| 5 | Wrong import name | `from extractors import` → `from extractors_full import` |
| 6 | API key not found in runner | Workflow now exposes both `CLAUDE_API_KEY` and `CLAUDE_API_KEY_GITHUB_EMAIL` |
| 7 | Timestamps 2h behind | Added `TZ: Europe/Bratislava` to workflow env |
| 8 | Telegram Markdown crash | Switched to `parse_mode: HTML` + HTML-escape all AI content |
| 9 | Emails marked as read on fetch | Changed IMAP fetch from `RFC822` → `BODY.PEEK[]` |
| 10 | yt-dlp blocked on CI | Transcripts now use `youtube-transcript-api`; `get_video_info` falls back to stub |
| 11 | Plain emails not processed | Added Claude Haiku summarization for emails with no YT/GitHub links |
| 12 | Prompts scattered in code | Extracted to `prompts.py` (versioned) + `prompt_builder.py` |
| 13 | YouTube: Claude got no context when yt-dlp blocked + no transcript | `prepare_youtube_batch` now accepts `email_body`; used as description fallback so Claude can summarize from the email content itself |
