#!/usr/bin/env python3
"""
Channel Watcher Bot — monitors watched YouTube channels for new videos,
summarizes them with Claude Opus, and sends per-channel Telegram messages.

State persistence:
  A JSON file (channel_state.json) tracks the last-seen video ID per channel.
  In GitHub Actions this file is downloaded as an artifact at the start of each
  run and uploaded again at the end, so state survives across daily runs.

Config:
  config/watched_channels.yaml  — list of channels to monitor

Env vars required:
  CLAUDE_API_KEY           — Anthropic API key
  TELEGRAM_BOT_TOKEN       — Telegram bot token
  TELEGRAM_CHAT_ID         — Telegram chat ID
  SUPADATA_API_KEY         — (optional) preferred transcript source
"""

import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
import yaml
from anthropic import Anthropic

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extractors_full import YouTubeExtractor

# ── Config ────────────────────────────────────────────────────────────────────

CONFIG_PATH = Path(__file__).parent.parent / 'config' / 'watched_channels.yaml'
STATE_FILE  = Path(__file__).parent / 'channel_state.json'

client = Anthropic(api_key=os.getenv('CLAUDE_API_KEY') or os.getenv('CLAUDE_API_KEY_GITHUB_EMAIL'))

RSS_NS = {
    'atom':  'http://www.w3.org/2005/Atom',
    'yt':    'http://www.youtube.com/xml/schemas/2015',
    'media': 'http://search.yahoo.com/mrss/',
}

# ── State helpers ─────────────────────────────────────────────────────────────

def load_state() -> Dict[str, str]:
    """Load last-seen video IDs keyed by channel ID."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding='utf-8'))
        except Exception as e:
            print(f'⚠️  Could not load state: {e}')
    return {}


def save_state(state: Dict[str, str]) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'💾 State saved to {STATE_FILE}')


# ── RSS fetching ──────────────────────────────────────────────────────────────

def fetch_channel_videos(channel_id: str, channel_name: str) -> List[Dict]:
    """Return all videos from the channel RSS feed (up to 15 most recent)."""
    url = f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}'
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            print(f'  ⚠️  RSS {channel_name}: HTTP {r.status_code}')
            return []

        root = ET.fromstring(r.text)
        videos = []
        for entry in root.findall('atom:entry', RSS_NS):
            vid_id = entry.find('yt:videoId', RSS_NS)
            title  = entry.find('atom:title',   RSS_NS)
            if vid_id is None or title is None:
                continue
            published_el = entry.find('atom:published', RSS_NS)
            published = ''
            if published_el is not None and published_el.text:
                published = published_el.text.strip()
            videos.append({
                'video_id':  vid_id.text,
                'url':       f'https://www.youtube.com/watch?v={vid_id.text}',
                'title':     title.text,
                'channel':   channel_name,
                'published': published,
            })
        return videos

    except Exception as e:
        print(f'  ⚠️  RSS {channel_name}: {e}')
        return []


def find_new_videos(
    videos: List[Dict],
    last_seen_id: Optional[str],
) -> Tuple[List[Dict], str]:
    """
    Return videos that are newer than last_seen_id (RSS order = newest first).
    Also returns the new last_seen_id (= first video in feed = most recent).
    """
    if not videos:
        return [], last_seen_id or ''

    new_last_seen = videos[0]['video_id']

    if last_seen_id is None:
        # First run — treat only the most recent video as "new" to avoid
        # flooding Telegram with the entire channel history.
        print(f'  ℹ️  First run — seeding with latest video only')
        return [videos[0]], new_last_seen

    new_videos = []
    for v in videos:
        if v['video_id'] == last_seen_id:
            break
        new_videos.append(v)

    return new_videos, new_last_seen


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


# ── Per-video processing ──────────────────────────────────────────────────────

def process_video(video: Dict) -> Optional[Dict]:
    """Fetch transcript and summarize a single video. Returns result dict or None."""
    url   = video['url']
    title = video['title']
    print(f'\n  🎬 {title}')

    info = YouTubeExtractor.get_video_info(url)
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
        'title':      title,
        'url':        url,
        'published':  video.get('published', ''),
        'summary':    summary_data.get('summary', ''),
        'my_take':    summary_data.get('my_take', ''),
        'has_transcript': bool(transcript),
    }


# ── Telegram message builder ──────────────────────────────────────────────────

def build_channel_message(channel_name: str, results: List[Dict]) -> str:
    """Build a single Telegram message for all new videos from one channel."""
    header = (
        f'📺 <b>{_esc(channel_name)}</b> — '
        f'{len(results)} new video{"s" if len(results) != 1 else ""}\n'
        f'<i>{datetime.now().strftime("%Y-%m-%d %H:%M")}</i>\n'
    )

    blocks = [header]
    for v in results:
        block  = f'\n🎥 <b>{_esc(v["title"])}</b>\n'
        block += f'🔗 <a href="{_esc(v["url"])}">Watch on YouTube</a>\n'
        if v.get('published'):
            block += f'📅 <i>{_esc(v["published"][:10])}</i>\n'
        if v.get('has_transcript'):
            block += '<i>✅ Transcript available</i>\n'
        block += '\n'
        if v.get('summary'):
            block += _esc(v['summary']) + '\n'
        if v.get('my_take'):
            block += '\n' + _esc(v['my_take']) + '\n'
        blocks.append(block)

    return '\n'.join(blocks)


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    print(f'\n📺 Channel Watcher Bot started at {datetime.now()}\n')

    # Load channel config
    if not CONFIG_PATH.exists():
        print(f'❌ Config not found: {CONFIG_PATH}')
        sys.exit(1)

    with open(CONFIG_PATH, encoding='utf-8') as f:
        config = yaml.safe_load(f)

    channels = config.get('channels', [])
    if not channels:
        print('⚠️  No channels configured')
        return

    print(f'📋 Watching {len(channels)} channel(s)\n')

    # Load persisted state
    state = load_state()

    total_new = 0

    for ch in channels:
        ch_name = ch['name']
        ch_id   = ch['id']
        print(f'\n🔍 Checking: {ch_name} ({ch_id})')

        videos = fetch_channel_videos(ch_id, ch_name)
        if not videos:
            print(f'  ⚠️  No videos found in RSS')
            continue

        print(f'  📡 RSS returned {len(videos)} video(s)')

        last_seen = state.get(ch_id)
        new_videos, new_last_seen = find_new_videos(videos, last_seen)

        # Update state immediately so even a partial run saves progress
        state[ch_id] = new_last_seen
        save_state(state)

        if not new_videos:
            print(f'  ✅ No new videos since last run')
            continue

        print(f'  🆕 {len(new_videos)} new video(s) — processing...')
        total_new += len(new_videos)

        results = []
        for video in new_videos:
            result = process_video(video)
            if result:
                results.append(result)

        if not results:
            print(f'  ⚠️  All summarizations failed for {ch_name}')
            continue

        msg = build_channel_message(ch_name, results)
        print(f'\n📤 Sending Telegram message for {ch_name}...')
        send_telegram(msg)

    print(f'\n✅ Done — {total_new} new video(s) processed across all channels')


if __name__ == '__main__':
    run()
