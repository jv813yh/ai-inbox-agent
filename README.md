# AI Inbox Agent

> Turn a learning inbox into structured AI notes, implementation ideas, and Telegram-ready digests.

AI Inbox Agent watches a Gmail learning inbox, extracts useful links and long-form content, summarizes them with Claude, and writes durable Markdown notes for a knowledge base such as HumanAgentWiki or Obsidian.

It is built for people who send themselves YouTube videos, GitHub repos, newsletters, articles, and AI ideas — and want those inputs turned into searchable notes, practical takeaways, and reviewable implementation suggestions.

---

## What it does

```text
Unread Gmail
   ↓
Link + content detection
   ↓
YouTube / GitHub / Web article / Plain email extraction
   ↓
Claude summaries with prompt-injection safeguards
   ↓
Markdown notes + indexes + dedupe state
   ↓
Telegram digest / HumanAgentWiki / pending-review suggestions
```

## Why this is useful

- **Capture once, reuse later** — forward links or notes to a learning inbox instead of losing them in chat/bookmarks.
- **Structured knowledge base** — save consistent Markdown notes with frontmatter and reusable sections.
- **Practical output** — get summaries, key points, claims, entities, and actionable ideas.
- **Implementation thinking** — generate pending-review suggestions for skills, checklists, runbooks, or project improvements.
- **Safe automation** — mark Gmail messages read only after notes and indexing succeed.

---

## Core features

| Feature | What it means |
|---|---|
| **Gmail learning inbox** | Reads unread messages from a dedicated learning inbox. |
| **YouTube processing** | Fetches metadata, tries transcript sources, summarizes videos, and creates channel hubs. |
| **GitHub repo processing** | Fetches repo metadata/README and produces practical repo analysis. |
| **Article/newsletter processing** | Extracts web article content and summarizes it into structured notes. |
| **Plain email summaries** | Summarizes long emails even when no supported link is present. |
| **HumanAgentWiki / Obsidian notes** | Writes Markdown notes, daily digests, indexes, and AI Learning System notes. |
| **RAG mode** | Writes raw sources, extracted knowledge JSON, concept candidates, and JSONL chunks for retrieval systems. |
| **Outcome mode** | Prints compact practical takeaways from newly created notes. |
| **Suggestions mode** | Saves pending-review implementation ideas for a human to approve/modify/reject. |
| **Dedupe state** | Avoids reprocessing the same YouTube video, GitHub repo, article, or Gmail message. |
| **`no check` bypass** | Put `no check` in the subject to intentionally reprocess a duplicate source. |
| **Prompt-injection aware** | Treats email bodies, transcripts, web pages, and READMEs as untrusted input. |

---

## Example outputs

### Telegram/stdout digest

```text
📬 AI Inbox Agent
🎥 Building Reliable AI Agents — Example Channel → YouTube/Technologie/Example Channel/...
🧠 Learning → AI Learning System/Technologie/...

🗞️ Saved daily AI news digest → Daily Personal AI news/2026-07-06/1611/ai-inbox-agent.md
```

### Pending-review suggestions

```md
## AI Implementation Suggestions

**Status:** pending_review
**Do not execute automatically:** no skills, code, or operational changes are created without approval.

- [ ] Create a reusable verification checklist for AI-generated code.
- [ ] Turn this workflow into a project runbook.
- [ ] Add a prompt template for evaluating new automation ideas.
```

---

## Operating modes

AI Inbox Agent supports two main modes.

### 1. GitHub Actions bot mode

A hosted workflow for Gmail → Claude → Telegram summaries.

| Script | Purpose |
|---|---|
| `src/email_summary_bot_final.py` | Read unread Gmail via IMAP/app password, summarize links/plain emails, send Telegram output. |
| `src/collector_bot.py` | Collect AI/news links from configured sources and email them into the inbox. |
| `src/channel_watcher_bot.py` | Watch configured YouTube channels and summarize new videos. |
| `src/youtube_queue_bot.py` | Process manually queued YouTube URLs from `config/youtube_queue.txt`. |

Workflows are manual by default via `workflow_dispatch`. Add a `schedule` trigger if you want cron execution.

### 2. Server-local HumanAgentWiki mode

A local/server workflow for Gmail OAuth → Markdown notes → HumanAgentWiki indexing → Telegram-ready digest.

Main entry point:

```bash
python src/server_runner.py --dry-run
python src/server_runner.py
```

Useful variants:

```bash
python src/server_runner.py --with-outcome
python src/server_runner.py --with-suggestions
python src/server_runner.py --rag
python src/server_runner.py --dry-run --max-emails 3
```

Machine-specific wrapper scripts are intentionally not committed. A deployment can provide wrappers such as:

```bash
ai_inbox_learning_agent.sh
ai_inbox_learning_agent_with_outcome.sh
ai_inbox_learning_agent_with_suggestions.sh
ai_inbox_learning_agent_rag.sh
```

---

## What gets written

In HumanAgentWiki/Obsidian mode, the runner writes Markdown files like these:

| Output type | Example path |
|---|---|
| YouTube source note | `YouTube/Technologie/<channel>/YYYY-MM-DD--<video-id>--<slug>.md` |
| YouTube channel hub | `YouTube Channels/<channel>.md` |
| GitHub repo note | `GitHub Projects/<owner>--<repo>.md` |
| Web article note | `Web Articles/<classification>/<domain>/<slug>.md` |
| Plain email note | `Emails/<classification>/<YYYY-MM>/<slug>.md` |
| AI Learning note | `AI Learning System/<domain>/<slug>.md` |
| Daily digest | `Daily Personal AI news/YYYY-MM-DD/HHMM/ai-inbox-agent.md` |
| Suggestions review note | `AI Suggestions/YYYY-MM-DD/HHMM/ai-inbox-agent-suggestions.md` |
| Raw RAG source | `Raw Sources/YouTube/<channel>/YYYY-MM-DD--<id>--<slug>.md` |
| Extracted knowledge JSON | `Extracted Knowledge/YouTube/YYYY-MM-DD--<id>--<slug>.json` |
| Concept candidate | `Concepts/<domain>/<concept>.md` |
| RAG chunks JSONL | `RAG/Chunks/YYYY-MM-DD--<id>--<slug>.jsonl` |
| Indexes | `Indexes/*.md` |

---

## Content handling

| Input | Behavior |
|---|---|
| YouTube URL | Fetch metadata, try transcripts, summarize with Claude, write a source note and channel hub. |
| GitHub repo URL | Fetch repository metadata and README, then summarize purpose, architecture, risks, and usage ideas. |
| Web article URL | Fetch readable page content and summarize it into a structured article note. |
| Long plain email | Summarize directly when it looks like useful learning material. |
| Duplicate source | Skip by default and record state. |
| Subject contains `no check` | Reprocess the source even if it was already seen. |

YouTube transcript extraction can be blocked on cloud/server IPs. When that happens, the pipeline can still use email context and metadata so the run produces a useful note instead of failing completely.

---

## RAG mode

```bash
python src/server_runner.py --rag
```

RAG mode keeps the normal source notes, then adds machine-friendly retrieval artifacts:

1. **Raw source** with stable metadata and content hash.
2. **Extracted knowledge JSON** with claims, principles, frameworks, risks, metrics, and actionable checklists.
3. **Concept candidates** under `Concepts/<domain>/` so repeated ideas can later be merged into durable knowledge notes.
4. **JSONL chunks** under `RAG/Chunks/` with metadata for vector/keyword indexing.

This is meant for RAG first. Fine-tuning datasets should be generated later from curated Q/A or extraction examples, not directly from raw video summaries.

---

## Outcome vs suggestions

### Outcome mode

```bash
python src/server_runner.py --with-outcome
```

Prints practical takeaways from notes created in the current run.

Use it when you want an immediate “what can I do with this?” summary.

### Suggestions mode

```bash
python src/server_runner.py --with-suggestions
```

Creates a `pending_review` note with possible implementation ideas, such as:

- create a reusable skill,
- add a checklist,
- write a runbook,
- build a project template,
- investigate a tool or technique,
- improve an existing automation.

Suggestions are **not executed automatically**. They are intentionally saved for human approval first.

---

## Installation

```bash
git clone https://github.com/<owner>/ai-inbox-agent.git
cd ai-inbox-agent
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Run tests:

```bash
python -m pytest -q
```

Run syntax checks:

```bash
python -m py_compile src/*.py
```

---

## Configuration

### Environment variables

| Variable | Used by | Notes |
|---|---|---|
| `CLAUDE_API_KEY` or `ANTHROPIC_API_KEY` | Claude summaries | Required for LLM summarization. |
| `CLAUDE_API_KEY_GITHUB_EMAIL` | Legacy workflows | Kept for older GitHub Actions compatibility. |
| `GMAIL_CREDENTIALS` | GitHub Actions IMAP mode | JSON containing email/app-password fields. Prefer OAuth for server mode. |
| `GOOGLE_TOKEN_PATH` | Server-local OAuth mode | Path to a Google OAuth token JSON file. |
| `TELEGRAM_BOT_TOKEN` | Telegram delivery | Telegram bot token. |
| `TELEGRAM_CHAT_ID` | Telegram delivery | Destination chat. |
| `SUPADATA_API_KEY` | Optional transcript/content enrichment | Optional fallback provider. |

### Config files

| File | Purpose |
|---|---|
| `config/watched_channels.yaml` | YouTube channels for the channel watcher. |
| `config/youtube_queue.txt` | Manual queue for YouTube URLs. |
| `config/prompts.yaml` | Optional prompt/config experiments. |
| `src/prompts.py` | Versioned prompt constants used by the prompt builder. |

---

## Safety model

AI Inbox Agent is designed around a few important safety rules:

- **Untrusted input:** email bodies, transcripts, READMEs, and web pages are data, not instructions.
- **No secret exposure:** prompts and logs must not include API keys, OAuth tokens, app passwords, or local state DB content.
- **Safe Gmail marking:** messages are marked read only after downstream persistence succeeds.
- **Idempotent processing:** dedupe state prevents accidental repeated processing.
- **Human approval:** suggestions remain `pending_review` until a human approves them.

---

## Public-repo checklist

Before publishing a fork or deployment repo, run:

```bash
git status --short
git ls-files 'venv/*' '.venv/*' '*.sqlite' '*.db' '*.env' '*token*' '*secret*'
git grep -nE 'sk-|AIza|ya29\.|refresh_token|client_secret|TELEGRAM_BOT_TOKEN|GMAIL_CREDENTIALS|app_password|password'
python -m pytest -q
```

Expected:

- no real secrets,
- no local virtualenv,
- no OAuth token files,
- no SQLite state DB,
- no generated private notes.

---

## Project status

This project started as a personal learning-inbox automation and now contains both:

1. a reusable GitHub Actions Gmail/Telegram bot, and
2. a server-local HumanAgentWiki knowledge pipeline.

For public use, bring your own secrets and adapt paths with CLI flags such as:

```bash
python src/server_runner.py \
  --token-path /path/to/google_token.json \
  --notes-dir /path/to/notes \
  --state-db /path/to/processed.sqlite
```

---

## License

No license file is currently included. Add one before encouraging external contributions or reuse.
