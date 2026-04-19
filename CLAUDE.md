# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the bot locally

```bash
cd src
GMAIL_CREDENTIALS='{"email":"...","app_password":"..."}' \
CLAUDE_API_KEY_GITHUB_EMAIL=sk-... \
TELEGRAM_BOT_TOKEN=... \
TELEGRAM_CHAT_ID=... \
SUPADATA_API_KEY=... \
python email_summary_bot_final.py
```

The bot reads **unread** emails, processes all links, and sends results to Telegram.

## Architecture

Three separate pipelines run daily via GitHub Actions:

```
18:00 UTC  collector_bot.py           — scrapes YouTube RSS, GitHub trending, ArXiv, HN, Reddit, RSS feeds
                                        → filters with Claude Haiku → sends emails to inbox
20:00 UTC  email_summary_bot_final.py — reads those emails → extracts links → summarizes → Telegram
21:00 UTC  channel_watcher_bot.py     — checks watched_channels.yaml for new videos per channel
                                        → summarizes → one Telegram message per channel
```

**Content routing in `email_summary_bot_final.py`:** Each email body is scanned for YouTube links → GitHub links → other URLs → if none, treated as plain email. Processing is handled by `extractors_full.py`.

**Extractor classes (`src/extractors_full.py`):**
- `YouTubeExtractor` — transcript pipeline: Supadata API → yt-dlp subtitles → youtube-transcript-api. Long transcripts are sampled (15k chars: start/mid/end). Uses Claude Opus.
- `GitHubExtractor` — GitHub REST API for repo info + README. Uses Claude Opus.
- `WebArticleExtractor` — plain HTTP fetch + BeautifulSoup. LinkedIn returns 999/login wall — no content possible without session cookie.
- `ContentPreparator` — orchestrates batches, passes `email_body` as fallback context to YouTube when transcript unavailable.

## Prompt system

All prompt strings are in `src/prompts.py` as versioned constants (`YOUTUBE_V1`, `YOUTUBE_V2`, …). The `latest_*` pointers at the bottom of that file control which version is active everywhere. `src/prompt_builder.py` reads only `latest_*` and handles truncation/formatting before calling Claude.

**Output format rule for all prompts:** plain text only — no Markdown. Use `EMOJI + CAPS` headers. Output must be Telegram-safe (HTML-escaped via `_esc()`).

To add a new content type: add a versioned constant in `prompts.py` + a method in `prompt_builder.py` + extractor logic in `extractors_full.py`.

## Models used

| Content type | Model |
|---|---|
| YouTube, GitHub | `claude-opus-4-6` |
| Plain email, web article, collector filtering | `claude-haiku-4-5-20251001` |

## GitHub Actions workflows

| Workflow | Trigger | Entry point |
|---|---|---|
| `collector.yml` | 18:00 UTC daily | `src/collector_bot.py` |
| `email-summary.yml` | 20:00 UTC daily | `src/email_summary_bot_final.py` |
| `channel-watcher.yml` | 21:00 UTC daily | `src/channel_watcher_bot.py` |
| `video-processor.yml` | manual | dedicated video processing |
| `repo-evaluator.yml` | manual | GitHub repo evaluation |

All workflows set `working-directory: src` and `TZ: Europe/Bratislava`.

### Channel Watcher state persistence
`channel_watcher_bot.py` stores `{channel_id: last_seen_video_id}` in `src/channel_state.json`. The workflow downloads this file as a GitHub Actions artifact at the start of each run (`channel-state`, retention 90 days) and uploads the updated version at the end. On the **first ever run**, the artifact won't exist (`continue-on-error: true`) — the bot seeds each channel with only its latest video to avoid flooding Telegram with history.

Edit `config/watched_channels.yaml` to add/remove channels. Each entry needs `name` and `id` (YouTube channel ID).

## Known limitations

- **Supadata** (`SUPADATA_API_KEY`) — preferred YouTube transcript source; bypasses bot detection that blocks yt-dlp on GitHub Actions IPs. Also supports general web scraping for AI use cases.
- **YouTube URLs with non-standard parameter order** (e.g. `?app=desktop&v=ID`): fixed 2026-04-19 — regex now matches `watch?[^\s]+`.
- **yt-dlp blocked on GitHub Actions IPs** — falls back to stub title; transcripts still attempted via youtube-transcript-api.
- **LinkedIn links** — always fail (HTTP 999 / login wall). No authentication in place.
- **GitHub API rate limit** — 60 req/hr unauthenticated. Add `GITHUB_TOKEN` to workflow if hitting limits.
- **Telegram message limit** — split at 4000 chars automatically.
