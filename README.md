# AI Inbox Agent

Turn a learning inbox into structured AI notes, implementation ideas, and Telegram digests.

AI Inbox Agent reads learning emails, extracts links, summarizes useful content with Claude, writes durable Markdown notes, and keeps a local dedupe state so the same source is not processed repeatedly. It can run as a GitHub Actions bot or as a server-local pipeline that writes into a HumanAgentWiki/Obsidian-style notes folder.

## Highlights

- **Email → knowledge base:** process unread learning emails into Markdown notes.
- **Multi-source extraction:** YouTube videos, GitHub repositories, web articles, newsletters, and long plain emails.
- **RAG-friendly notes:** consistent frontmatter plus sections such as Summary, Key points, Entities, Claims, and Actionable ideas.
- **HumanAgentWiki support:** writes source notes, index notes, daily digests, AI Learning System notes, and reviewable AI Suggestions notes.
- **Telegram-ready output:** concise digests for chat delivery or cron/no-agent delivery.
- **Safe dedupe:** YouTube by video ID, GitHub by `owner/repo`, articles by canonical URL, and messages by Gmail ID.
- **Failure-safe Gmail handling:** messages are marked read only after note writing and HumanAgentWiki indexing succeed.
- **Reprocess on demand:** put `no check` in the email subject to bypass source/message dedupe for that email.
- **Outcome mode:** print compact practical takeaways from newly created notes.
- **Suggestions mode:** save pending-review implementation suggestions that a human can approve, modify, or reject before anything is implemented.
- **Prompt-injection aware:** prompts treat email bodies, transcripts, READMEs, and web content as untrusted data.

## Pipeline modes

### 1. GitHub Actions bot mode

Good for a hosted daily email-summary/Telegram workflow.

Main entry points:

| Script | Purpose |
|---|---|
| `src/email_summary_bot_final.py` | Read unread Gmail via IMAP/app password, summarize links/plain emails, send Telegram output. |
| `src/collector_bot.py` | Collect AI/news links from configured sources and email them into the inbox. |
| `src/channel_watcher_bot.py` | Watch configured YouTube channels and summarize new videos. |
| `src/youtube_queue_bot.py` | Process manually queued YouTube URLs from `config/youtube_queue.txt`. |

GitHub workflows are manual by default (`workflow_dispatch`). Add a `schedule` block if you want cron execution.

### 2. Server-local HumanAgentWiki mode

Good when you want durable notes on a server instead of only Telegram output.

Entry point:

```bash
python src/server_runner.py --dry-run
python src/server_runner.py
```

Useful flags:

```bash
python src/server_runner.py --dry-run --max-emails 3
python src/server_runner.py --with-outcome
python src/server_runner.py --with-suggestions
```

Typical server wrapper names used in production deployments:

```bash
ai_inbox_learning_agent.sh
ai_inbox_learning_agent_with_outcome.sh
ai_inbox_learning_agent_with_suggestions.sh
```

These wrappers are intentionally not part of the repo because they usually contain machine-specific paths.

## What gets written in HumanAgentWiki mode

| Output | Example path |
|---|---|
| YouTube notes | `YouTube/Technologie/<channel>/YYYY-MM-DD--<video-id>--<slug>.md` |
| GitHub notes | `GitHub Projects/<owner>--<repo>.md` |
| Web article notes | `Web Articles/<classification>/<domain>/<slug>.md` |
| Plain email notes | `Emails/<classification>/<YYYY-MM>/<slug>.md` |
| AI Learning notes | `AI Learning System/<domain>/<slug>.md` |
| YouTube channel hubs | `YouTube Channels/<channel>.md` |
| Index notes | `Indexes/*.md` |
| Daily digest | `Daily Personal AI news/YYYY-MM-DD/HHMM/ai-inbox-agent.md` |
| Pending-review suggestions | `AI Suggestions/YYYY-MM-DD/HHMM/ai-inbox-agent-suggestions.md` |

## Content handling

| Input | Behavior |
|---|---|
| YouTube URL | Fetch metadata, try transcript sources, summarize with Claude, write source note and channel hub. |
| GitHub repo URL | Fetch repo metadata/README, summarize purpose, architecture, and adoption ideas. |
| Web article URL | Fetch readable page content and summarize into a structured article note. |
| Long plain email | Summarize directly when it is likely useful learning content. |
| Duplicate source | Skip by default and record state. |
| Subject contains `no check` | Reprocess even if the source/message was seen before. |

YouTube transcript extraction tries multiple sources. Cloud/server IPs may still be blocked by YouTube; when transcript retrieval fails, the pipeline can fall back to email body/context so the workflow still produces a useful note.

## Outcome and suggestions modes

### Outcome mode

```bash
python src/server_runner.py --with-outcome
```

After processing, prints compact practical takeaways from the notes created in that run.

### Suggestions mode

```bash
python src/server_runner.py --with-suggestions
```

After processing, creates a pending-review note with possible implementation ideas, for example:

- create a reusable skill/checklist,
- add a verification workflow,
- turn a video process into a runbook,
- add a project template,
- investigate a tool mentioned in the source.

Suggestions are **not executed automatically**. They are proposals for a human to approve, modify, or reject.

## Configuration

### Environment variables

| Variable | Used by | Notes |
|---|---|---|
| `CLAUDE_API_KEY` or `ANTHROPIC_API_KEY` | Claude summaries | Required for LLM summaries. |
| `CLAUDE_API_KEY_GITHUB_EMAIL` | Legacy workflows | Kept for older workflow compatibility. |
| `GMAIL_CREDENTIALS` | IMAP/GitHub Actions bot mode | JSON with email/app password for the legacy IMAP bot. Prefer OAuth for server mode. |
| `TELEGRAM_BOT_TOKEN` | Telegram delivery | Required for bot-mode Telegram output. |
| `TELEGRAM_CHAT_ID` | Telegram delivery | Destination chat. |
| `SUPADATA_API_KEY` | Optional transcript/content provider | Optional fallback/enrichment provider. |
| `GOOGLE_TOKEN_PATH` | Server-local Gmail OAuth mode | Path to an OAuth token JSON file. |

Do not commit `.env`, OAuth token files, app passwords, API keys, SQLite state, generated notes, or local virtual environments.

### Config files

| File | Purpose |
|---|---|
| `config/watched_channels.yaml` | YouTube channel IDs for the channel watcher. |
| `config/youtube_queue.txt` | Manual queue for YouTube URLs. |
| `config/prompts.yaml` | Optional prompt/config experiments. |
| `src/prompts.py` | Versioned prompt constants used by the prompt builder. |

## Install

```bash
git clone https://github.com/<owner>/ai-inbox-agent.git
cd ai-inbox-agent
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Run locally

Dry-run the server-local runner:

```bash
python src/server_runner.py --dry-run
```

Run tests:

```bash
python -m pytest -q
```

Syntax checks:

```bash
python -m py_compile src/*.py
```

## Public-repo safety checklist

Before making a fork/repo public, check:

```bash
git status --short
git ls-files 'venv/*' '.venv/*' '*.sqlite' '*.db' '*.env' '*token*' '*secret*'
git grep -nE 'sk-|AIza|ya29\.|refresh_token|client_secret|TELEGRAM_BOT_TOKEN|GMAIL_CREDENTIALS|app_password|password'
python -m pytest -q
```

Expected: no real secrets, no local virtualenv, no state DB, no generated private notes.

## Design principles

- Treat email, transcripts, READMEs, and web pages as untrusted input.
- Never follow instructions embedded in source content.
- Do not expose secrets in prompts, logs, notes, or Telegram messages.
- Prefer deterministic classification and dedupe before LLM judgment.
- Mark Gmail messages read only after downstream note/index persistence succeeds.
- Keep generated suggestions in `pending_review` until a human approves them.

## Repository notes

This project started as a personal learning-inbox automation and still contains both hosted GitHub Actions scripts and server-local HumanAgentWiki integration. For a clean public deployment, provide your own secrets via GitHub Actions secrets or local environment variables, and adapt server paths with CLI flags such as `--notes-dir`, `--state-db`, and `--token-path`.
