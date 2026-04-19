#!/usr/bin/env python3
"""
YouTube Queue Bot — reads YouTube links from config/youtube_queue.txt,
summarizes each video with Claude Opus, sends results to Telegram,
then clears the queue file.

Schedule: runs every morning at 8:00 (Europe/Bratislava).
Queue file: config/youtube_queue.txt — one URL per line, # lines are comments.

After processing the workflow commits the cleared queue file back to the repo.
"""

import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import requests
from anthropic import Anthropic

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extractors_full import YouTubeExtractor

# ── Config ────────────────────────────────────────────────────────────────────

QUEUE_FILE = Path(__file__).parent.parent / 'config' / 'youtube_queue.txt'

COMMENTS_HEADER = """\
# YouTube Queue — one URL per line
# The bot reads this file every morning at 8:00, summarizes each video,
# sends it to Telegram, then clears this file automatically.
# Lines starting with # are ignored.
#
# Example:
# https://www.youtube.com/watch?v=dQw4w9WgXcQ
"""

client = Anthropic(
    api_key=os.getenv('CLAUDE_API_KEY') or os.getenv('CLAUDE_API_KEY_GITHUB_EMAIL')
)

# ── Queue helpers ─────────────────────────────────────────────────────────────

def read_queue() -> List[str]:
    """Read YouTube URLs from the queue file. Returns list of URLs."""
    if not QUEUE_FILE.exists():
        print(f'⚠️  Queue file not found: {QUEUE_FILE}')
        return []

    urls = []
    for line in QUEUE_FILE.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if 'youtube.com' in line or 'youtu.be' in line:
            urls.append(line)
        else:
            print(f'  ⚠️  Skipping non-YouTube line: {line[:80]}')

    return urls


def clear_queue() -> None:
    """Overwrite the queue file with just the header comments."""
    QUEUE_FILE.write_text(COMMENTS_HEADER, encoding='utf-8')
    print(f'🗑️  Queue cleared: {QUEUE_FILE}')


# ── Telegram ──────────────────────────────────────────────────────────────────

def _esc(text: str) -> str:
    return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _chunk(text: str, max_length: int = 4000) -> List[str]:
    if len(text) <= max_length:
        return [text]
    chunks = []
    paragraphs = text.split('\n\n')
    current = ''
    for para in paragraphs:
        candidate = (current + '\n\n' + para).strip() if current else para
        if len(candidate) <= max_length:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = para
    if current:
        chunks.append(current)
    return chunks


def send_telegram(message: str) -> bool:
    token   = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    if not token or not chat_id:
        print('❌ Telegram config missing')
        return False

    url = f'https://api.telegram.org/bot{token}/sendMessage'
    for i, chunk in enumerate(_chunk(message), 1):
        payload = {'chat_id': chat_id, 'text': chunk, 'parse_mode': 'HTML'}
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                print(f'  ✅ Telegram chunk {i} sent')
            else:
                print(f'  ❌ Telegram error: {resp.text[:200]}')
                return False
        except Exception as e:
            print(f'  ❌ Telegram exception: {e}')
            return False
    return True


# ── Message builder ───────────────────────────────────────────────────────────

def build_section_banner(count: int) -> str:
    line = '━' * 28
    return (
        f'{line}\n'
        f'🎬  <b>YOUTUBE MORNING QUEUE</b>\n'
        f'{line}\n'
        f'{count} video{"s" if count != 1 else ""}  ·  '
        f'<i>{datetime.now().strftime("%Y-%m-%d %H:%M")}</i>'
    )


def build_video_message(video_data: dict) -> str:
    esc = _esc
    block  = f'🎥 <b>{esc(video_data.get("title", "Unknown"))}</b>\n'
    block += f'🔗 <a href="{esc(video_data["url"])}">Watch on YouTube</a>\n'
    if video_data.get('has_transcript'):
        block += '<i>✅ Transcript available</i>\n'
    block += '\n'
    if video_data.get('summary'):
        block += esc(video_data['summary']) + '\n'
    if video_data.get('my_take'):
        block += '\n' + esc(video_data['my_take']) + '\n'
    return block.strip()


# ── Processing ────────────────────────────────────────────────────────────────

def process_url(url: str) -> Optional[dict]:
    print(f'\n  🎬 Processing: {url}')

    info = YouTubeExtractor.get_video_info(url)
    title       = info.get('title', '') if info else ''
    description = info.get('description', '') if info else ''

    transcript = YouTubeExtractor.get_transcript(url)

    summary_data = YouTubeExtractor.summarize_video(
        url,
        title=title,
        description=description,
        transcript=transcript or '',
    )
    if not summary_data:
        print(f'  ❌ Summarization failed')
        return None

    return {
        'url':            url,
        'title':          summary_data.get('title') or title,
        'summary':        summary_data.get('summary', ''),
        'my_take':        summary_data.get('my_take', ''),
        'has_transcript': bool(transcript),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    print(f'\n🎬 YouTube Queue Bot started at {datetime.now()}\n')

    urls = read_queue()

    if not urls:
        print('📭 Queue is empty — nothing to process')
        return

    print(f'📋 Found {len(urls)} URL(s) in queue\n')

    # Send section banner first
    send_telegram(build_section_banner(len(urls)))

    processed = 0
    for url in urls:
        result = process_url(url)
        if result:
            send_telegram(build_video_message(result))
            processed += 1

    # Clear queue regardless of success — avoid reprocessing on next run
    clear_queue()

    print(f'\n✅ Done — {processed}/{len(urls)} video(s) summarised, queue cleared')


if __name__ == '__main__':
    run()
