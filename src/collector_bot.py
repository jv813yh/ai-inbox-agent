#!/usr/bin/env python3
"""
AI Content Collector — gathers AI/ML links from multiple sources and emails
them to the inbox so the summarizer bot (email_summary_bot_final.py) can
summarize each one.

Sources
-------
  YouTube      — RSS feeds from curated AI channels (last 7 days)
  GitHub       — Daily trending repos filtered by AI relevance
  ArXiv        — Latest cs.AI / cs.LG / cs.CL papers (last 3 days)
  HackerNews   — Top stories with AI keywords
  Reddit       — Hot posts from ML/AI subreddits (external links only)
  RSS feeds    — Towards Data Science, KDnuggets, LangChain blog, The Gradient

LinkedIn is intentionally excluded — it requires authentication and actively
blocks automated access.

After collection every non-YouTube item is filtered by Claude Haiku, which
decides what is genuinely relevant, insightful, or practically useful —
not just keyword-matched noise.

Pipeline timing
---------------
  18:00 UTC  — this collector runs, sends emails
  20:00 UTC  — the summarizer reads those emails and processes each link
"""

import os
import json
import smtplib
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.header import decode_header as _decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import parsedate_to_datetime
from bs4 import BeautifulSoup
from anthropic import Anthropic
try:
    from . import llm
except ImportError:
    import llm

# ── AI keywords (fallback when Claude is unavailable) ────────────────────────

AI_KEYWORDS = [
    'AI', 'LLM', 'GPT', 'machine learning', 'neural', 'Claude', 'OpenAI',
    'Anthropic', 'transformer', 'diffusion', 'benchmark', 'agent', 'RAG',
    'fine-tuning', 'inference', 'multimodal', 'reasoning', 'Gemini', 'Mistral',
    'Llama', 'deep learning', 'reinforcement learning', 'language model',
    'generative AI', 'foundation model', 'computer vision', 'NLP',
    'chatbot', 'embedding', 'vector database', 'prompt engineering',
]

# ── YouTube channels to monitor ──────────────────────────────────────────────

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

# ── RSS feeds (articles / blogs) ─────────────────────────────────────────────

RSS_FEEDS = {
    'Towards Data Science': 'https://medium.com/feed/towards-data-science',
    'KDnuggets':            'https://www.kdnuggets.com/feed',
    'LangChain Blog':       'https://blog.langchain.dev/rss/',
    'The Gradient':         'https://thegradient.pub/rss/',
    'Import AI':            'https://jack-clark.net/feed/',
}

# ── Reddit subreddits ─────────────────────────────────────────────────────────

REDDIT_SUBS = ['MachineLearning', 'LocalLLaMA', 'artificial', 'singularity']

# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_ai_related(text: str) -> bool:
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in AI_KEYWORDS)


def _parse_rss_date(item: ET.Element) -> datetime | None:
    """Try to parse a date from common RSS/Atom date elements."""
    for tag in ('pubDate', 'published', 'updated', 'dc:date'):
        el = item.find(tag)
        if el is None:
            # Try with namespace prefix stripped
            for child in item:
                if child.tag.endswith(f'}}{tag}') or child.tag == tag:
                    el = child
                    break
        if el is not None and el.text:
            raw = el.text.strip()
            # RFC 2822  (RSS 2.0)
            try:
                return parsedate_to_datetime(raw).astimezone(timezone.utc)
            except Exception:
                pass
            # ISO 8601  (Atom)
            try:
                return datetime.fromisoformat(
                    raw.replace('Z', '+00:00')
                ).astimezone(timezone.utc)
            except Exception:
                pass
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Sources
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_youtube_rss(max_per_channel: int = 2, lookback_days: int = 7) -> list:
    """Recent videos from curated AI YouTube channels via their public RSS feeds."""
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
                    try:
                        published = datetime.fromisoformat(
                            published_el.text.replace('Z', '+00:00')
                        )
                        if published < cutoff:
                            continue
                    except Exception:
                        pass

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


def fetch_rss_feeds(max_per_feed: int = 3, lookback_days: int = 3) -> list:
    """Fetch latest articles from configured RSS / Atom feeds."""
    cutoff  = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    headers = {'User-Agent': 'ai-inbox-collector/1.0'}
    results = []

    for feed_name, feed_url in RSS_FEEDS.items():
        try:
            r = requests.get(feed_url, headers=headers, timeout=15)
            if r.status_code != 200:
                print(f'  ⚠️  RSS {feed_name}: HTTP {r.status_code}')
                continue

            root = ET.fromstring(r.text)

            # Collect raw item/entry elements — handle RSS 2.0 and Atom
            raw_items: list[ET.Element] = []
            channel = root.find('channel')
            if channel is not None:
                raw_items = channel.findall('item')
            else:
                # Atom — entries may be direct children or namespaced
                atom_ns = 'http://www.w3.org/2005/Atom'
                raw_items = (
                    root.findall(f'{{{atom_ns}}}entry')
                    or root.findall('entry')
                )

            count = 0
            for item in raw_items:
                if count >= max_per_feed:
                    break

                # Date filter
                pub = _parse_rss_date(item)
                if pub is not None and pub < cutoff:
                    continue

                # Title
                title_el = item.find('title')
                title = (title_el.text or '').strip() if title_el is not None else ''

                # URL — RSS <link>, Atom <link href="…">
                url = ''
                link_el = item.find('link')
                if link_el is not None:
                    url = (link_el.get('href') or link_el.text or '').strip()
                # Atom alternate link
                if not url:
                    for child in item:
                        if child.tag.endswith('}link') or child.tag == 'link':
                            url = (
                                child.get('href')
                                or child.text
                                or ''
                            ).strip()
                            if url:
                                break

                if not title or not url:
                    continue

                results.append({'url': url, 'title': title, 'source': feed_name})
                count += 1

        except Exception as e:
            print(f'  ⚠️  RSS {feed_name}: {e}')

    print(f'  ✅ RSS feeds: {len(results)} articles')
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

                desc_el  = article.find('p')
                desc     = desc_el.get_text(strip=True) if desc_el else ''
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
    """Return top HackerNews stories matching AI keywords."""
    try:
        r = requests.get(
            'https://hacker-news.firebaseio.com/v0/topstories.json', timeout=10
        )
        r.raise_for_status()
        story_ids = r.json()[:150]
    except Exception as e:
        print(f'  ⚠️  HackerNews: {e}')
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
    """Hot posts with external links from AI-focused subreddits."""
    headers = {'User-Agent': 'ai-inbox-collector/1.0 (automated research bot)'}
    results = []

    for sub in REDDIT_SUBS:
        try:
            r = requests.get(
                f'https://www.reddit.com/r/{sub}/hot.json?limit=25',
                headers=headers, timeout=10,
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
    """Recent AI/ML papers from ArXiv (last 3 days)."""
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
            try:
                published = datetime.fromisoformat(
                    published_el.text.replace('Z', '+00:00')
                )
                if published < cutoff:
                    continue
            except Exception:
                pass

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
# Claude relevance filter
# ═══════════════════════════════════════════════════════════════════════════════

def filter_with_claude(items: list) -> list:
    """
    Use Claude Haiku to select only genuinely relevant, insightful, or
    practically useful items from the collected list.

    Falls back to keyword filtering when CLAUDE_API_KEY is not set.
    """
    if not items:
        return items

    api_key = os.getenv('CLAUDE_API_KEY')
    if not api_key:
        print('  ℹ️  CLAUDE_API_KEY not set — using keyword filter as fallback')
        return [i for i in items if _is_ai_related(i.get('title', '') + ' ' + i.get('desc', ''))]

    numbered = [
        {'i': idx, 'title': item.get('title', ''), 'url': item.get('url', '')}
        for idx, item in enumerate(items)
    ]

    prompt = (
        'You are an expert AI/ML content curator for a daily digest.\n'
        'A reader wants links that are: genuinely relevant to AI, ML, or LLMs; '
        'novel, insightful, or practically useful; NOT pure marketing, ads, '
        'or completely off-topic content.\n\n'
        'Below is a JSON list of collected items. '
        'Return ONLY a JSON array of the indices (field "i") you would KEEP '
        '— no other text, no explanation.\n\n'
        'Items:\n'
        + json.dumps(numbered, ensure_ascii=False)
    )

    try:
        client = Anthropic(api_key=api_key)
        response = llm.create_message(
            model='claude-haiku-4-5-20251001',
            max_tokens=256,
            messages=[{'role': 'user', 'content': prompt}],
        )
        raw = response.content[0].text.strip()
        # Extract the JSON array even if surrounded by prose
        start, end = raw.find('['), raw.rfind(']')
        if start == -1 or end == -1:
            raise ValueError(f'No JSON array in response: {raw}')
        keep_indices = set(json.loads(raw[start:end + 1]))
        filtered = [item for idx, item in enumerate(items) if idx in keep_indices]
        print(f'  🤖 Claude filter: {len(items)} → {len(filtered)} items kept')
        return filtered
    except Exception as e:
        print(f'  ⚠️  Claude filter failed ({e}) — keeping all items')
        return items


# ═══════════════════════════════════════════════════════════════════════════════
# Email formatting
# ═══════════════════════════════════════════════════════════════════════════════

def _build_video_body(youtube_items: list) -> str:
    ts    = datetime.now().strftime('%Y-%m-%d %H:%M UTC')
    lines = [
        f'AI Video Collection — {ts}',
        f'Collected {len(youtube_items)} video(s) from monitored YouTube channels.',
        '',
    ]
    for item in youtube_items:
        lines.append(f"{item['url']}  ({item['channel']}: {item['title']})")
    return '\n'.join(lines)


def _build_text_body(
    gh_items:     list,
    arxiv_items:  list,
    hn_items:     list,
    reddit_items: list,
    rss_items:    list,
) -> str:
    ts    = datetime.now().strftime('%Y-%m-%d %H:%M UTC')
    total = sum(len(x) for x in (gh_items, arxiv_items, hn_items, reddit_items, rss_items))
    lines = [
        f'AI Content Collection — {ts}',
        f'Collected {total} link(s) from GitHub Trending, ArXiv, HackerNews, Reddit, and blogs.',
        '',
    ]

    if gh_items:
        lines += ['[GitHub Trending]']
        for item in gh_items:
            lines.append(f"{item['url']}  ({item.get('desc', item['title'])})")
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

    if rss_items:
        lines += ['[Blogs & Newsletters]']
        for item in rss_items:
            lines.append(f"{item['url']}  ({item['source']}: {item['title']})")
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
        msg            = MIMEMultipart()
        msg['From']    = self.from_addr
        msg['To']      = to_addr
        msg['Subject'] = subject
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

    # ── Collect from all sources ──────────────────────────────────────────────
    print('📡 Fetching content from all sources...\n')
    yt_items     = fetch_youtube_rss()
    gh_items     = fetch_github_trending()
    arxiv_items  = fetch_arxiv()
    hn_items     = fetch_hackernews()
    reddit_items = fetch_reddit()
    rss_items    = fetch_rss_feeds()

    # ── Claude relevance filter (text content only — YouTube kept as-is) ─────
    print('\n🤖 Filtering text content with Claude...\n')
    text_raw  = gh_items + arxiv_items + hn_items + reddit_items + rss_items
    text_kept = filter_with_claude(text_raw)

    # Rebuild per-source lists from the filtered set for the email body
    kept_urls  = {item['url'] for item in text_kept}
    gh_items     = [i for i in gh_items     if i['url'] in kept_urls]
    arxiv_items  = [i for i in arxiv_items  if i['url'] in kept_urls]
    hn_items     = [i for i in hn_items     if i['url'] in kept_urls]
    reddit_items = [i for i in reddit_items if i['url'] in kept_urls]
    rss_items    = [i for i in rss_items    if i['url'] in kept_urls]

    text_total = len(text_kept)
    total      = len(yt_items) + text_total
    print(
        f'\n📊 Final totals: {total} items  '
        f'(YouTube: {len(yt_items)}, text: {text_total})\n'
    )

    if total == 0:
        print('⚠️  Nothing collected — skipping email send')
        return

    # ── Send emails ───────────────────────────────────────────────────────────
    print('📤 Sending emails...\n')

    if yt_items:
        body = _build_video_body(yt_items)
        sender.send(email_addr, 'AI_VIDEO_BOT', body)

    if text_total > 0:
        body = _build_text_body(gh_items, arxiv_items, hn_items, reddit_items, rss_items)
        sender.send(email_addr, 'AI_TEXT_BOT', body)

    print('\n✅ Collection complete!')


if __name__ == '__main__':
    run()
