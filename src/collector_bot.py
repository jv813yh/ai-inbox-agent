#!/usr/bin/env python3
"""
AI Content Collector — gathers AI/ML links from GitHub Trending, YouTube
channel RSS feeds, HackerNews, Reddit, and ArXiv, then emails them to the
inbox so the summarizer bot (email_summary_bot_final.py) can process them.

Pipeline:
  1. This bot runs first (18:00 UTC) and sends two emails:
       - Subject "AI interested stuff - video"  → YouTube links
       - Subject "AI interested stuff - text"   → GitHub / ArXiv / HN / Reddit links
  2. The summarizer runs later (20:00 UTC), reads those emails, extracts every
     URL, and summarizes each one with the existing extractors.
"""

import os
import json
import smtplib
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup

# ── AI keywords used to filter HackerNews stories and GitHub repos ───────────

AI_KEYWORDS = [
    'AI', 'LLM', 'GPT', 'machine learning', 'neural', 'Claude', 'OpenAI',
    'Anthropic', 'transformer', 'diffusion', 'benchmark', 'agent', 'RAG',
    'fine-tuning', 'inference', 'multimodal', 'reasoning', 'Gemini', 'Mistral',
    'Llama', 'deep learning', 'reinforcement learning', 'language model',
    'generative AI', 'foundation model', 'computer vision', 'NLP', 'chatbot',
    'embedding', 'vector', 'prompt', 'stable diffusion', 'image generation',
]

# ── YouTube channels to monitor via RSS (add/remove as needed) ───────────────

YOUTUBE_CHANNELS = {
    'Two Minute Papers':  'UCbfYPyITQ-7l4upoX8nvctg',
    'Andrej Karpathy':    'UCXUPKJO5MZQEMU4rYNJMNkA',
    'Yannic Kilcher':     'UCZHmQk67mSJgfCCTn7xBfew',
    'AI Explained':       'UCNJ1Ymd5yFuUPtn21xtRbbw',
    'Matt Wolfe':         'UCgnfPPb9JI3e9A4cXiTOedA',
    'Fireship':           'UCsBjURrPoezykLs9EqgamOA',
    '3Blue1Brown':        'UCYO_jab_esuFRV4b17AJtAg',
    'Lex Fridman':        'UCSHZKyawb77ixDdsGog4iWA',
}

# ── Reddit subreddits to scrape ───────────────────────────────────────────────

REDDIT_SUBS = ['MachineLearning', 'LocalLLaMA', 'artificial', 'singularity']

# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_ai_related(text: str) -> bool:
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in AI_KEYWORDS)


# ═══════════════════════════════════════════════════════════════════════════════
# Sources
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_youtube_rss(max_per_channel: int = 2, lookback_days: int = 7) -> list:
    """Return recent videos from curated AI YouTube channels via their RSS feeds."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    ns = {
        'atom':  'http://www.w3.org/2005/Atom',
        'yt':    'http://www.youtube.com/xml/schemas/2015',
        'media': 'http://search.yahoo.com/mrss/',
    }
    results = []

    for channel_name, channel_id in YOUTUBE_CHANNELS.items():
        feed_url = (
            f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}'
        )
        try:
            r = requests.get(feed_url, timeout=10)
            if r.status_code != 200:
                print(f'  ⚠️  YouTube RSS {channel_name}: HTTP {r.status_code}')
                continue

            root = ET.fromstring(r.text)
            count = 0
            for entry in root.findall('atom:entry', ns):
                if count >= max_per_channel:
                    break

                published_el = entry.find('atom:published', ns)
                if published_el is not None:
                    published = datetime.fromisoformat(
                        published_el.text.replace('Z', '+00:00')
                    )
                    if published < cutoff:
                        continue

                vid_id = entry.find('yt:videoId', ns)
                title  = entry.find('atom:title', ns)
                if vid_id is not None and title is not None:
                    results.append({
                        'url':     f'https://www.youtube.com/watch?v={vid_id.text}',
                        'title':   title.text,
                        'channel': channel_name,
                    })
                    count += 1

        except Exception as e:
            print(f'  ⚠️  YouTube RSS {channel_name}: {e}')

    print(f'  ✅ YouTube: {len(results)} videos')
    return results


def fetch_github_trending(max_items: int = 8) -> list:
    """Scrape GitHub Trending for daily AI/ML repos."""
    headers = {
        'Accept':     'text/html,application/xhtml+xml',
        'User-Agent': 'Mozilla/5.0 (compatible; ai-inbox-collector/1.0)',
    }
    seen    = set()
    results = []

    for lang in ('python', 'jupyter-notebook', ''):
        if len(results) >= max_items:
            break
        suffix = f'/{lang}' if lang else ''
        url = f'https://github.com/trending{suffix}?since=daily'
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                continue

            soup = BeautifulSoup(r.text, 'html.parser')
            for article in soup.find_all('article'):
                if len(results) >= max_items:
                    break

                h2 = article.find('h2')
                if not h2:
                    continue
                a = h2.find('a', href=True)
                if not a:
                    continue

                href = a['href'].strip().strip('/')
                if href.count('/') != 1:
                    continue

                repo_url = f'https://github.com/{href}'
                if repo_url in seen:
                    continue

                desc_el = article.find('p')
                desc = desc_el.get_text(strip=True) if desc_el else ''
                repo_name = href.split('/')[-1]

                if _is_ai_related(f'{desc} {repo_name} {href}'):
                    results.append({
                        'url':   repo_url,
                        'title': href,
                        'desc':  desc or repo_name,
                    })
                    seen.add(repo_url)

        except Exception as e:
            print(f'  ⚠️  GitHub Trending ({lang or "all"}): {e}')

    print(f'  ✅ GitHub Trending: {len(results)} repos')
    return results


def fetch_hackernews(max_items: int = 8) -> list:
    """Return top HackerNews stories that match AI keywords."""
    try:
        r = requests.get(
            'https://hacker-news.firebaseio.com/v0/topstories.json', timeout=10
        )
        r.raise_for_status()
        story_ids = r.json()[:150]
    except Exception as e:
        print(f'  ⚠️  HackerNews top stories: {e}')
        return []

    results = []
    for sid in story_ids:
        if len(results) >= max_items:
            break
        try:
            item = requests.get(
                f'https://hacker-news.firebaseio.com/v0/item/{sid}.json',
                timeout=8,
            ).json()
            if (
                item
                and item.get('type') == 'story'
                and item.get('url')
                and _is_ai_related(item.get('title', ''))
            ):
                results.append({
                    'url':   item['url'],
                    'title': item.get('title', ''),
                    'score': item.get('score', 0),
                })
        except Exception:
            continue

    print(f'  ✅ HackerNews: {len(results)} stories')
    return results


def fetch_reddit(max_per_sub: int = 4) -> list:
    """Return hot posts with external links from AI-focused subreddits."""
    headers = {'User-Agent': 'ai-inbox-collector/1.0 (automated research bot)'}
    results = []

    for sub in REDDIT_SUBS:
        try:
            r = requests.get(
                f'https://www.reddit.com/r/{sub}/hot.json?limit=25',
                headers=headers,
                timeout=10,
            )
            if r.status_code != 200:
                print(f'  ⚠️  Reddit r/{sub}: HTTP {r.status_code}')
                continue

            count = 0
            for post in r.json()['data']['children']:
                if count >= max_per_sub:
                    break
                data = post['data']
                url  = data.get('url', '')
                if (
                    url
                    and 'reddit.com' not in url
                    and not data.get('stickied', False)
                    and not data.get('is_self', False)
                ):
                    results.append({
                        'url':       url,
                        'title':     data.get('title', ''),
                        'subreddit': sub,
                        'score':     data.get('score', 0),
                    })
                    count += 1

        except Exception as e:
            print(f'  ⚠️  Reddit r/{sub}: {e}')

    print(f'  ✅ Reddit: {len(results)} posts')
    return results


def fetch_arxiv(max_items: int = 6) -> list:
    """Return recent AI/ML papers from ArXiv (last 3 days)."""
    query  = 'cat:cs.AI+OR+cat:cs.LG+OR+cat:cs.CL'
    url    = (
        f'https://export.arxiv.org/api/query'
        f'?search_query={query}'
        f'&sortBy=submittedDate&sortOrder=descending'
        f'&max_results={max_items * 2}'
    )
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f'  ⚠️  ArXiv: {e}')
        return []

    ns     = {'atom': 'http://www.w3.org/2005/Atom'}
    root   = ET.fromstring(r.text)
    cutoff = datetime.now(timezone.utc) - timedelta(days=3)
    results = []

    for entry in root.findall('atom:entry', ns):
        if len(results) >= max_items:
            break
        published_el = entry.find('atom:published', ns)
        if published_el is not None:
            published = datetime.fromisoformat(
                published_el.text.replace('Z', '+00:00')
            )
            if published < cutoff:
                continue

        title_el = entry.find('atom:title', ns)
        id_el    = entry.find('atom:id', ns)
        if title_el is not None and id_el is not None:
            results.append({
                'url':   id_el.text.strip(),
                'title': title_el.text.strip().replace('\n', ' '),
            })

    print(f'  ✅ ArXiv: {len(results)} papers')
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Email formatting
# ═══════════════════════════════════════════════════════════════════════════════

def _build_video_body(youtube_items: list) -> str:
    ts = datetime.now().strftime('%Y-%m-%d %H:%M UTC')
    lines = [
        f'AI Video Collection — {ts}',
        f'Collected {len(youtube_items)} video(s) from monitored YouTube channels.',
        '',
    ]
    for item in youtube_items:
        lines.append(
            f"{item['url']}  ({item['channel']}: {item['title']})"
        )
    return '\n'.join(lines)


def _build_text_body(
    gh_items:     list,
    arxiv_items:  list,
    hn_items:     list,
    reddit_items: list,
) -> str:
    ts = datetime.now().strftime('%Y-%m-%d %H:%M UTC')
    total = len(gh_items) + len(arxiv_items) + len(hn_items) + len(reddit_items)
    lines = [
        f'AI Content Collection — {ts}',
        f'Collected {total} link(s) from GitHub Trending, ArXiv, HackerNews, and Reddit.',
        '',
    ]

    if gh_items:
        lines += ['[GitHub Trending]']
        for item in gh_items:
            lines.append(f"{item['url']}  ({item['desc']})")
        lines.append('')

    if arxiv_items:
        lines += ['[ArXiv Papers]']
        for item in arxiv_items:
            lines.append(f"{item['url']}  ({item['title']})")
        lines.append('')

    if hn_items:
        lines += ['[HackerNews]']
        for item in hn_items:
            lines.append(f"{item['url']}  ({item['title']})")
        lines.append('')

    if reddit_items:
        lines += ['[Reddit]']
        for item in reddit_items:
            lines.append(
                f"{item['url']}  (r/{item['subreddit']}: {item['title']})"
            )
        lines.append('')

    return '\n'.join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Email sender
# ═══════════════════════════════════════════════════════════════════════════════

class EmailSender:
    def __init__(self, from_addr: str, app_password: str):
        self.from_addr    = from_addr
        self.app_password = app_password

    def send(self, to_addr: str, subject: str, body: str) -> bool:
        msg              = MIMEMultipart()
        msg['From']      = self.from_addr
        msg['To']        = to_addr
        msg['Subject']   = subject
        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        try:
            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
                smtp.login(self.from_addr, self.app_password)
                smtp.send_message(msg)
            print(f'  ✅ Sent: "{subject}"')
            return True
        except Exception as e:
            print(f'  ❌ Send failed ("{subject}"): {e}')
            return False


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def run():
    print(f'\n🤖 AI Collector Bot started at {datetime.now()}\n')

    creds_json = os.getenv('GMAIL_CREDENTIALS')
    if not creds_json:
        print('❌ GMAIL_CREDENTIALS not set — aborting')
        return

    creds        = json.loads(creds_json)
    email_addr   = creds['email']
    app_password = creds['app_password']
    sender       = EmailSender(email_addr, app_password)

    # ── Collect ───────────────────────────────────────────────────────────────
    print('📡 Fetching content from all sources...\n')
    yt_items     = fetch_youtube_rss()
    gh_items     = fetch_github_trending()
    arxiv_items  = fetch_arxiv()
    hn_items     = fetch_hackernews()
    reddit_items = fetch_reddit()

    text_total = len(gh_items) + len(arxiv_items) + len(hn_items) + len(reddit_items)
    total      = len(yt_items) + text_total
    print(f'\n📊 Total collected: {total} items  '
          f'(YouTube: {len(yt_items)}, text: {text_total})\n')

    if total == 0:
        print('⚠️  Nothing collected — skipping email send')
        return

    # ── Send emails ───────────────────────────────────────────────────────────
    print('📤 Sending emails...\n')

    if yt_items:
        body = _build_video_body(yt_items)
        sender.send(email_addr, 'AI interested stuff - video', body)

    if text_total > 0:
        body = _build_text_body(gh_items, arxiv_items, hn_items, reddit_items)
        sender.send(email_addr, 'AI interested stuff - text', body)

    print('\n✅ Collection complete!')


if __name__ == '__main__':
    run()
