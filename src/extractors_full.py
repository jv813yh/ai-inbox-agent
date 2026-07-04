#!/usr/bin/env python3
"""
Content Extractors for YouTube and GitHub
With full YouTube transcript extraction
Prepares data structures for vector database
"""

import html
import os
import re
import json
import requests
from datetime import datetime
from typing import Dict, List, Optional
from anthropic import Anthropic
from yt_dlp import YoutubeDL
from youtube_transcript_api import YouTubeTranscriptApi
from bs4 import BeautifulSoup

try:
    from .prompt_builder import PromptBuilder
except ImportError:
    from prompt_builder import PromptBuilder

client = Anthropic(
    api_key=(
        os.getenv("CLAUDE_API_KEY_GITHUB_EMAIL")
        or os.getenv("CLAUDE_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
    )
)


def _split_take(text: str) -> tuple[str, str]:
    """Split a Claude response into (intro, my_take) on the '🧠 MY TAKE:' boundary."""
    marker = "🧠 MY TAKE:"
    idx = text.find(marker)
    if idx == -1:
        return text.strip(), ""
    return text[:idx].strip(), text[idx:].strip()

class YouTubeExtractor:
    """Extract YouTube video info, transcripts and summarize"""
    
    @staticmethod
    def extract_youtube_links(text: str) -> List[str]:
        """Extract all YouTube URLs from text"""
        patterns = [
            r'https?://(?:www\.|m\.)?youtube\.com/watch\?[^\s]+',
            r'https?://(?:www\.)?youtu\.be/[^\s?\s]+',
            r'https?://(?:www\.|m\.)?youtube\.com/embed/[^\s?]+',
            r'https?://(?:www\.|m\.)?youtube\.com/shorts/[^\s?]+',
        ]
        
        links = []
        for pattern in patterns:
            links.extend(re.findall(pattern, text))
        
        return list(set(links))  # Remove duplicates
    
    @staticmethod
    def _extract_video_id(url: str) -> Optional[str]:
        """Extract video ID from any YouTube URL format."""
        match = re.search(r'(?:v=|youtu\.be/|embed/)([A-Za-z0-9_-]{11})', url)
        return match.group(1) if match else None

    @staticmethod
    def _sample_transcript(text: str, max_chars: int = 15000) -> str:
        """Return a representative sample covering start, middle, and end of long transcripts."""
        if len(text) <= max_chars:
            return text
        chunk = max_chars // 3
        mid_start = (len(text) - chunk) // 2
        return (
            text[:chunk]
            + "\n\n[...]\n\n"
            + text[mid_start:mid_start + chunk]
            + "\n\n[...]\n\n"
            + text[-chunk:]
        )

    class _SilentLogger:
        """Suppress all yt-dlp output — errors are still raised as exceptions."""
        def debug(self, _): pass
        def warning(self, _): pass
        def error(self, _): pass

    @staticmethod
    def _get_oembed_info(url: str) -> Dict:
        """Fetch lightweight public YouTube oEmbed metadata without an API key."""
        try:
            resp = requests.get(
                "https://www.youtube.com/oembed",
                params={"url": url, "format": "json"},
                timeout=10,
                headers={"User-Agent": WebArticleExtractor._BROWSER_UA if "WebArticleExtractor" in globals() else "Mozilla/5.0"},
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "title": data.get("title") or "",
                    "channel": data.get("author_name") or "",
                    "author_url": data.get("author_url") or "",
                    "thumbnail": data.get("thumbnail_url") or "",
                }
        except Exception as e:
            print(f"  ⚠️ YouTube oEmbed metadata failed: {e}")
        return {}

    @staticmethod
    def _get_watch_page_info(url: str) -> Dict:
        """Parse channel/title metadata directly from the public YouTube watch page."""
        try:
            resp = requests.get(
                url,
                timeout=15,
                headers={"User-Agent": WebArticleExtractor._BROWSER_UA if "WebArticleExtractor" in globals() else "Mozilla/5.0"},
            )
            if resp.status_code != 200:
                return {}
            page_html = resp.text
            patterns = {
                "channel": [
                    r'"ownerChannelName"\s*:\s*"([^"]+)"',
                    r'"author"\s*:\s*"([^"]+)"',
                    r'<link itemprop="name" content="([^"]+)"',
                ],
                "title": [
                    r'"title"\s*:\s*\{"runs"\s*:\s*\[\{"text"\s*:\s*"([^"]+)"',
                    r'<meta property="og:title" content="([^"]+)"',
                ],
                "channel_id": [r'"externalChannelId"\s*:\s*"([^"]+)"'],
            }
            out = {}
            for key, pats in patterns.items():
                for pat in pats:
                    match = re.search(pat, page_html)
                    if match:
                        value = html.unescape(match.group(1))
                        out[key] = value
                        break
            return out
        except Exception as e:
            print(f"  ⚠️ YouTube watch page metadata failed: {e}")
            return {}

    @staticmethod
    def get_video_info(url: str) -> Optional[Dict]:
        """Get YouTube video metadata using yt-dlp, with oEmbed fallback for channel/title."""
        print(f"  📥 Fetching video info...")
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
                'logger': YouTubeExtractor._SilentLogger(),
            }
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            channel = info.get('uploader') or info.get('channel') or info.get('creator') or ''
            title = info.get('title') or ''
            thumbnail = info.get('thumbnail') or ''
            if not channel or channel in {'Unknown', 'unknown'}:
                oembed = YouTubeExtractor._get_oembed_info(url)
                watch_page = {} if oembed.get('channel') else YouTubeExtractor._get_watch_page_info(url)
                channel = oembed.get('channel') or watch_page.get('channel') or channel or 'Unknown'
                title = title or oembed.get('title') or watch_page.get('title') or 'Unknown'
                thumbnail = thumbnail or oembed.get('thumbnail') or ''
            return {
                'video_id': info.get('id', ''),
                'url': url,
                'title': title or 'Unknown',
                'description': info.get('description', ''),
                'channel': channel or 'Unknown',
                'duration': info.get('duration', 0),
                'upload_date': info.get('upload_date', ''),
                'view_count': info.get('view_count', 0),
                'thumbnail': thumbnail
            }
        except Exception as e:
            print(f"  ⚠️ yt-dlp blocked, using fallback: {e}")
            video_id = YouTubeExtractor._extract_video_id(url)
            oembed = YouTubeExtractor._get_oembed_info(url)
            watch_page = {} if oembed.get('channel') else YouTubeExtractor._get_watch_page_info(url)
            return {
                'video_id': video_id or '',
                'url': url,
                'title': oembed.get('title') or watch_page.get('title') or f'YouTube ({video_id})',
                'description': '',
                'channel': oembed.get('channel') or watch_page.get('channel') or 'Unknown',
                'duration': 0,
                'upload_date': '',
                'view_count': 0,
                'thumbnail': oembed.get('thumbnail') or ''
            }

    @staticmethod
    def _get_transcript_via_ytdlp(video_id: str) -> Optional[str]:
        """Extract transcript from YouTube auto-captions via yt-dlp subtitle URLs."""
        url = f"https://www.youtube.com/watch?v={video_id}"
        try:
            ydl_opts = {
                'skip_download': True,
                'quiet': True,
                'no_warnings': True,
                'logger': YouTubeExtractor._SilentLogger(),
            }
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

            for sub_dict in [info.get('subtitles', {}), info.get('automatic_captions', {})]:
                for lang in ['en', 'en-US', 'en-GB']:
                    if lang not in sub_dict:
                        continue
                    for fmt in sub_dict[lang]:
                        if fmt.get('ext') != 'json3':
                            continue
                        resp = requests.get(fmt['url'], timeout=15)
                        if resp.status_code != 200:
                            continue
                        events = resp.json().get('events', [])
                        parts = [
                            seg.get('utf8', '')
                            for event in events
                            for seg in event.get('segs', [])
                            if seg.get('utf8', '') not in ('', '\n')
                        ]
                        text = ' '.join(parts).strip()
                        if text:
                            print(f"  ✅ yt-dlp subtitle transcript ({len(text)} chars)")
                            return YouTubeExtractor._sample_transcript(text)
        except Exception as e:
            print(f"  ⚠️ yt-dlp subtitle extraction failed: {e}")
        return None

    @staticmethod
    def get_transcript(url: str) -> Optional[str]:
        """Fetch transcript: Supadata API → yt-dlp subtitles → youtube-transcript-api → None."""
        print(f"  📝 Extracting transcript...")
        video_id = YouTubeExtractor._extract_video_id(url)
        if not video_id:
            print(f"  ⚠️ Could not extract video ID from URL")
            return None

        # 1. Supadata API (bypasses YouTube bot detection)
        supadata_key = os.getenv("SUPADATA_API_KEY")
        if supadata_key:
            try:
                resp = requests.get(
                    "https://api.supadata.ai/v1/youtube/transcript",
                    params={"videoId": video_id, "text": "true"},
                    headers={"x-api-key": supadata_key},
                    timeout=15,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    text = data.get("content") or data.get("transcript") or ""
                    if isinstance(text, list):
                        text = " ".join(
                            item.get("text", "") if isinstance(item, dict) else str(item)
                            for item in text
                        )
                    if text:
                        print(f"  ✅ Supadata transcript ({len(text)} chars)")
                        return YouTubeExtractor._sample_transcript(text)
                else:
                    print(f"  ⚠️ Supadata error: {resp.status_code}")
            except Exception as e:
                print(f"  ⚠️ Supadata failed: {e}")

        # 2. yt-dlp subtitle extraction (fetches caption URLs directly)
        text = YouTubeExtractor._get_transcript_via_ytdlp(video_id)
        if text:
            return text

        # 3. youtube-transcript-api (handles both v0.x and v1.x)
        try:
            api = YouTubeTranscriptApi()                          # v1.x
            fetched = api.fetch(video_id)
            text = " ".join(item.text for item in fetched)
            print(f"  ✅ youtube-transcript-api transcript ({len(text)} chars)")
            return YouTubeExtractor._sample_transcript(text)
        except Exception:
            pass

        try:
            transcript_list = YouTubeTranscriptApi.get_transcript( # v0.x fallback
                video_id, languages=["en", "en-US", "en-GB", "a.en"]
            )
            text = " ".join(item["text"] for item in transcript_list)
            print(f"  ✅ youtube-transcript-api v0 transcript ({len(text)} chars)")
            return YouTubeExtractor._sample_transcript(text)
        except Exception as e:
            print(f"  ⚠️ All transcript sources failed: {e}")
            return None
    
    @staticmethod
    def summarize_video(url: str, title: str = "", description: str = "",
                        transcript: str = "", email_context: str = "") -> Optional[Dict]:
        """Summarize YouTube video using Claude - Teacher Notes Version"""
        try:
            print(f"  🤖 Summarizing with Claude (detailed notes mode)...")

            prompt = PromptBuilder.youtube(title, description, transcript, email_context)
            
            response = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}]
            )
            
            intro, my_take = _split_take(response.content[0].text)

            return {
                'type': 'youtube_video',
                'url': url,
                'title': title,
                'description': description[:500] if description else '',
                'transcript_preview': transcript[:1500] if transcript else '',
                'has_full_transcript': bool(transcript),
                'summary': intro,
                'my_take': my_take,
                'processed_at': datetime.now().isoformat(),
                'source': 'email'
            }
        
        except Exception as e:
            print(f"  ❌ Error summarizing video: {e}")
            return None

class GitHubExtractor:
    """Extract GitHub repo info and summarize"""
    
    @staticmethod
    def extract_github_links(text: str) -> List[str]:
        """Extract all GitHub URLs from text"""
        pattern = r'https?://(?:www\.)?github\.com/[^\s/]+/[^\s/\?]+'
        links = re.findall(pattern, text)
        return list(set(links))  # Remove duplicates
    
    @staticmethod
    def parse_repo_url(url: str) -> Optional[Dict[str, str]]:
        """Parse GitHub URL to owner and repo name"""
        try:
            match = re.search(r'github\.com/([^/]+)/([^\/?]+)', url)
            if match:
                return {
                    'owner': match.group(1),
                    'repo': match.group(2),
                    'url': url
                }
            return None
        except:
            return None
    
    @staticmethod
    def get_repo_info(owner: str, repo: str) -> Optional[Dict]:
        """Get GitHub repo metadata from API"""
        try:
            print(f"  📥 Fetching repo info...")
            url = f"https://api.github.com/repos/{owner}/{repo}"
            response = requests.get(url, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                
                # Get README
                readme = GitHubExtractor.get_readme(owner, repo)
                
                return {
                    'owner': owner,
                    'repo': repo,
                    'url': data.get('html_url', f'https://github.com/{owner}/{repo}'),
                    'description': data.get('description', ''),
                    'stars': data.get('stargazers_count', 0),
                    'forks': data.get('forks_count', 0),
                    'language': data.get('language', 'Unknown'),
                    'topics': data.get('topics', []),
                    'updated_at': data.get('updated_at', ''),
                    'readme': readme
                }
            else:
                print(f"  ⚠️ GitHub API error: {response.status_code}")
                return None
        except Exception as e:
            print(f"  ❌ Error getting repo info: {e}")
            return None
    
    @staticmethod
    def get_readme(owner: str, repo: str) -> Optional[str]:
        """Get README content from GitHub"""
        try:
            url = f"https://api.github.com/repos/{owner}/{repo}/readme"
            response = requests.get(url, headers={'Accept': 'application/vnd.github.v3.raw'}, timeout=5)
            
            if response.status_code == 200:
                return response.text[:2000]  # First 2000 chars
            return None
        except:
            return None
    
    @staticmethod
    def summarize_repo(repo_info: Dict) -> Optional[Dict]:
        """Summarize GitHub repo using Claude - Detailed Teacher Version"""
        try:
            print(f"  🤖 Analyzing repo (detailed mode)...")
            
            prompt = PromptBuilder.github(repo_info)
            
            response = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )
            
            intro, my_take = _split_take(response.content[0].text)

            return {
                'type': 'github_repo',
                'url': repo_info['url'],
                'owner': repo_info['owner'],
                'repo': repo_info['repo'],
                'description': repo_info.get('description', ''),
                'stars': repo_info.get('stars', 0),
                'forks': repo_info.get('forks', 0),
                'language': repo_info.get('language', 'Unknown'),
                'topics': repo_info.get('topics', []),
                'summary': intro,
                'my_take': my_take,
                'readme_preview': repo_info.get('readme', '')[:500],
                'processed_at': datetime.now().isoformat(),
                'source': 'email'
            }
        
        except Exception as e:
            print(f"  ❌ Error summarizing repo: {e}")
            topics = repo_info.get('topics', []) or []
            topic_text = ", ".join(topics) if topics else "no listed topics"
            readme = repo_info.get('readme') or ''
            readme_first_lines = " ".join(
                line.strip().lstrip('# ').strip()
                for line in readme.splitlines()[:12]
                if line.strip()
            )[:700]
            why_use = []
            if repo_info.get('description'):
                why_use.append(f"- Use it as a reference for: {repo_info.get('description')}.")
            if topics:
                why_use.append(f"- Explore implementation patterns around: {topic_text}.")
            if repo_info.get('language') and repo_info.get('language') != 'Unknown':
                why_use.append(f"- Inspect the {repo_info.get('language')} codebase for architecture, APIs, and integration patterns you can reuse.")
            if readme_first_lines:
                why_use.append(f"- README signal: {readme_first_lines}")
            if not why_use:
                why_use.append("- Treat this as a discovery item: inspect stars, issues, examples, and recent commits before spending build time.")
            fallback_summary = (
                "📌 ONE-LINE SUMMARY: GitHub metadata fallback because LLM summarization failed.\n\n"
                f"🎓 WHAT IS THIS PROJECT?\n"
                f"{repo_info.get('owner', 'unknown')}/{repo_info.get('repo', 'unknown')} is a "
                f"{repo_info.get('language', 'Unknown')} project with {repo_info.get('stars', 0)} stars and {repo_info.get('forks', 0)} forks. "
                f"Description: {repo_info.get('description') or 'No description provided.'}\n\n"
                f"💡 WHY IT MAY MATTER\n"
                + "\n".join(why_use[:4])
                + "\n\n🚀 HOW JOZEF COULD USE THIS\n"
                "- Extract concrete implementation ideas, API patterns, repo structure, prompts, or automation workflows.\n"
                "- Compare the project with Jozef's agent/cloud/backend workflows and save only reusable patterns.\n"
                "- If promising, create a small spike: run the example, inspect open issues, and identify one feature worth copying or improving."
            )
            return {
                'type': 'github_repo',
                'url': repo_info.get('url', ''),
                'owner': repo_info.get('owner', ''),
                'repo': repo_info.get('repo', ''),
                'description': repo_info.get('description', ''),
                'stars': repo_info.get('stars', 0),
                'forks': repo_info.get('forks', 0),
                'language': repo_info.get('language', 'Unknown'),
                'topics': topics,
                'summary': fallback_summary,
                'my_take': '🧠 MY TAKE: LLM summarization failed, but the metadata/README still provide enough signal for a practical triage note. Use this as a candidate for follow-up only if the repo topics, README signal, or implementation patterns match Jozef\'s agent/backend/cloud goals.',
                'readme_preview': repo_info.get('readme', '')[:500],
                'processed_at': datetime.now().isoformat(),
                'source': 'email'
            }

class WebArticleExtractor:
    """Fetch and summarize web articles linked in emails."""

    @staticmethod
    def extract_urls(text: str) -> List[str]:
        """Extract HTTP(S) URLs that are not YouTube or GitHub links."""
        pattern = r'https?://[^\s<>"\'\]]+[^\s<>"\'\]\.\,\;\:\!\?]'
        urls = re.findall(pattern, text)
        filtered = []
        for url in urls:
            if 'youtube.com' in url or 'youtu.be' in url:
                continue
            if 'github.com' in url:
                continue
            filtered.append(url)
        return list(dict.fromkeys(filtered))  # deduplicate, preserve order

    _BROWSER_UA = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    )

    @staticmethod
    def _fetch_via_supadata(url: str) -> Optional[Dict]:
        """Fetch article content via Supadata web scraping API (fallback for blocked sites)."""
        api_key = os.getenv('SUPADATA_API_KEY')
        if not api_key:
            return None
        try:
            resp = requests.get(
                'https://api.supadata.ai/v1/web/scrape',
                params={'url': url},
                headers={'x-api-key': api_key},
                timeout=15,
            )
            if resp.status_code != 200:
                print(f"  ⚠️ Supadata web: HTTP {resp.status_code}")
                return None
            data = resp.json()
            content = data.get('content') or data.get('text') or ''
            title = data.get('title') or ''
            if not content:
                return None
            print(f"  ✅ Supadata web article: {title[:60]} ({len(content)} chars)")
            return {'url': url, 'title': title, 'content': content[:5000]}
        except Exception as e:
            print(f"  ⚠️ Supadata web failed: {e}")
            return None

    @staticmethod
    def fetch_article(url: str) -> Optional[Dict]:
        """Fetch a URL and extract its readable text content.
        Falls back to Supadata when the direct fetch is blocked (e.g. Medium/TDS 403).
        """
        try:
            headers = {
                'User-Agent': WebArticleExtractor._BROWSER_UA,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
            }
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                print(f"  ⚠️ HTTP {resp.status_code} for {url} — trying Supadata")
                return WebArticleExtractor._fetch_via_supadata(url)

            soup = BeautifulSoup(resp.text, 'html.parser')

            title = ''
            if soup.title and soup.title.string:
                title = soup.title.string.strip()

            for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'form']):
                tag.decompose()

            text = re.sub(r'\s+', ' ', soup.get_text(separator=' ', strip=True)).strip()

            # Paywall / login-wall detection — fall back to Supadata
            if len(text) < 300 or 'sign in' in text[:500].lower() or '403 forbidden' in text[:200].lower():
                print(f"  ⚠️ Content looks blocked ({len(text)} chars) — trying Supadata")
                supadata_result = WebArticleExtractor._fetch_via_supadata(url)
                if supadata_result:
                    return supadata_result

            print(f"  ✅ Fetched article: {title[:60]} ({len(text)} chars)")
            return {'url': url, 'title': title, 'content': text[:5000]}
        except Exception as e:
            print(f"  ⚠️ Failed to fetch {url}: {e}")
            return WebArticleExtractor._fetch_via_supadata(url)

    @staticmethod
    def summarize_article(article_data: Dict) -> Optional[Dict]:
        """Summarize an article with Claude."""
        try:
            prompt = PromptBuilder.article(
                article_data['title'],
                article_data['url'],
                article_data['content'],
            )
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
            )
            intro, my_take = _split_take(response.content[0].text)
            return {
                'type': 'web_article',
                'url': article_data['url'],
                'title': article_data['title'],
                'summary': intro,
                'my_take': my_take,
                'processed_at': datetime.now().isoformat(),
            }
        except Exception as e:
            print(f"  ❌ Error summarizing article: {e}")
            return None


class ContentPreparator:
    """Prepare content data for vector database"""
    
    @staticmethod
    def prepare_youtube_batch(urls: List[str], email_body: str = "") -> List[Dict]:
        """Process multiple YouTube videos.

        email_body is used as fallback context when yt-dlp is blocked and no
        transcript is available — the email itself often contains a description
        or table of contents for the linked video.
        """
        results = []

        for url in urls:
            print(f"\n🎥 Processing YouTube: {url}")

            # Get video info (falls back to stub when yt-dlp is blocked)
            video_info = YouTubeExtractor.get_video_info(url)
            if not video_info:
                continue

            # Get transcript via youtube-transcript-api
            transcript = YouTubeExtractor.get_transcript(url)

            title = video_info.get('title', '')
            description = video_info.get('description', '')

            if email_body:
                print(f"  ℹ️ Email body included as additional context")

            # Summarize — always pass email_body separately so it is never truncated
            summary = YouTubeExtractor.summarize_video(
                url,
                title,
                description,
                transcript,
                email_context=email_body
            )
            
            if summary:
                # Preserve metadata fetched outside the LLM call. The writer and
                # classifier need the real YouTube channel for folder routing;
                # without this, notes fall back to "Unknown Channel" even when
                # metadata was available.
                for key in ['video_id', 'channel', 'duration', 'upload_date', 'view_count', 'thumbnail']:
                    if video_info.get(key) not in (None, ''):
                        summary.setdefault(key, video_info.get(key))
                results.append(summary)
                print(f"✅ Processed: {summary.get('title', 'Unknown')}")
        
        return results
    
    @staticmethod
    def prepare_github_batch(urls: List[str]) -> List[Dict]:
        """Process multiple GitHub repos"""
        results = []
        
        for url in urls:
            print(f"\n🐙 Processing GitHub: {url}")
            
            # Parse URL
            parsed = GitHubExtractor.parse_repo_url(url)
            if not parsed:
                print(f"❌ Invalid GitHub URL: {url}")
                continue
            
            # Get repo info
            repo_info = GitHubExtractor.get_repo_info(parsed['owner'], parsed['repo'])
            if not repo_info:
                print(f"❌ Could not fetch repo info: {url}")
                continue
            
            # Summarize
            summary = GitHubExtractor.summarize_repo(repo_info)
            
            if summary:
                results.append(summary)
                print(f"✅ Processed: {summary.get('repo', 'Unknown')}")
        
        return results
    
    @staticmethod
    def prepare_article_batch(urls: List[str], *, max_per_email: int = 5) -> List[Dict]:
        """Process generic web article URLs."""
        results = []
        for url in urls[:max_per_email]:
            print(f"\n📰 Processing article: {url}")
            article = WebArticleExtractor.fetch_article(url)
            if not article:
                print(f"❌ Could not fetch article: {url}")
                continue
            summary = WebArticleExtractor.summarize_article(article)
            if summary:
                results.append(summary)
                print(f"✅ Processed article: {summary.get('title', 'Unknown')}")
        return results

    @staticmethod
    def prepare_plain_email(subject: str, from_addr: str, body: str) -> Optional[Dict]:
        """Summarize a useful plain email with Claude."""
        try:
            print(f"\n✉️ Processing plain email: {subject[:80]}")
            prompt = PromptBuilder.plain_email(subject=subject, from_addr=from_addr, body=body[:5000])
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
            )
            intro, my_take = _split_take(response.content[0].text)
            return {
                'type': 'plain_email',
                'subject': subject,
                'from_addr': from_addr,
                'summary': intro,
                'my_take': my_take,
                'processed_at': datetime.now().isoformat(),
                'source': 'email',
            }
        except Exception as e:
            print(f"  ❌ Error summarizing plain email: {e}")
            return None

    @staticmethod
    def format_for_storage(content_data: Dict) -> str:
        """Format content data as JSON for storage"""
        return json.dumps(content_data, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    # Test extractors
    print("Testing extractors...")
    
    # Test YouTube
    yt_urls = YouTubeExtractor.extract_youtube_links(
        "Check this video: https://youtube.com/watch?v=dQw4w9WgXcQ"
    )
    print(f"Found YouTube URLs: {yt_urls}")
    
    # Test GitHub
    gh_urls = GitHubExtractor.extract_github_links(
        "See my repo: https://github.com/facebook/react"
    )
    print(f"Found GitHub URLs: {gh_urls}")