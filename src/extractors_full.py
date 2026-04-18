#!/usr/bin/env python3
"""
Content Extractors for YouTube and GitHub
With full YouTube transcript extraction
Prepares data structures for vector database
"""

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

from prompt_builder import PromptBuilder

client = Anthropic(api_key=os.getenv("CLAUDE_API_KEY_GITHUB_EMAIL"))


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
            r'https?://(?:www\.|m\.)?youtube\.com/watch\?v=[^\s&]+',
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
    def get_video_info(url: str) -> Optional[Dict]:
        """Get YouTube video metadata using yt-dlp, with fallback when blocked."""
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
            return {
                'video_id': info.get('id', ''),
                'url': url,
                'title': info.get('title', 'Unknown'),
                'description': info.get('description', ''),
                'channel': info.get('uploader', 'Unknown'),
                'duration': info.get('duration', 0),
                'upload_date': info.get('upload_date', ''),
                'view_count': info.get('view_count', 0),
                'thumbnail': info.get('thumbnail', '')
            }
        except Exception as e:
            print(f"  ⚠️ yt-dlp blocked, using fallback: {e}")
            video_id = YouTubeExtractor._extract_video_id(url)
            return {
                'video_id': video_id or '',
                'url': url,
                'title': f'YouTube ({video_id})',
                'description': '',
                'channel': 'Unknown',
                'duration': 0,
                'upload_date': '',
                'view_count': 0,
                'thumbnail': ''
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
            return None

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

    @staticmethod
    def fetch_article(url: str) -> Optional[Dict]:
        """Fetch a URL and extract its readable text content."""
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (compatible; EmailBot/1.0)'}
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                print(f"  ⚠️ HTTP {resp.status_code} for {url}")
                return None

            soup = BeautifulSoup(resp.text, 'html.parser')

            title = ''
            if soup.title and soup.title.string:
                title = soup.title.string.strip()

            for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'form']):
                tag.decompose()

            text = re.sub(r'\s+', ' ', soup.get_text(separator=' ', strip=True)).strip()
            print(f"  ✅ Fetched article: {title[:60]} ({len(text)} chars)")
            return {'url': url, 'title': title, 'content': text[:5000]}
        except Exception as e:
            print(f"  ⚠️ Failed to fetch {url}: {e}")
            return None

    @staticmethod
    def summarize_article(article_data: Dict) -> Optional[Dict]:
        """Summarize an article with Claude."""
        try:
            from prompt_builder import PromptBuilder
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