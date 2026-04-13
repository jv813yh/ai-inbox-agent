#!/usr/bin/env python3
"""
Content Extractors for YouTube and GitHub
With full YouTube transcript extraction
Prepares data structures for vector database
"""

import re
import json
import requests
from datetime import datetime
from typing import Dict, List, Optional
from anthropic import Anthropic
from yt_dlp import YoutubeDL

client = Anthropic()

class YouTubeExtractor:
    """Extract YouTube video info, transcripts and summarize"""
    
    @staticmethod
    def extract_youtube_links(text: str) -> List[str]:
        """Extract all YouTube URLs from text"""
        patterns = [
            r'https?://(?:www\.)?youtube\.com/watch\?v=[^\s&]+',
            r'https?://(?:www\.)?youtu\.be/[^\s?]+',
            r'https?://(?:www\.)?youtube\.com/embed/[^\s?]+'
        ]
        
        links = []
        for pattern in patterns:
            links.extend(re.findall(pattern, text))
        
        return list(set(links))  # Remove duplicates
    
    @staticmethod
    def get_video_info(url: str) -> Optional[Dict]:
        """Get YouTube video metadata using yt-dlp"""
        try:
            print(f"  📥 Fetching video info...")
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
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
            print(f"  ❌ Error getting video info: {e}")
            return None
    
    @staticmethod
    def get_transcript(url: str) -> Optional[str]:
        """Get full transcript from YouTube"""
        try:
            print(f"  📝 Extracting transcript...")
            
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
                'writesubtitles': True,
                'writeautomaticsub': True,
                'subtitlesformat': 'vtt',
            }
            
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            
            # Check if subtitles are available
            if not info.get('subtitles') and not info.get('automatic_captions'):
                print(f"  ⚠️ No transcript available for this video")
                return None
            
            # Get English subtitles first, then any available
            subtitles = info.get('subtitles', {}) or info.get('automatic_captions', {})
            
            transcript_text = ""
            
            # Try English first
            if 'en' in subtitles:
                for sub in subtitles['en']:
                    if sub.get('data'):
                        transcript_text = sub['data']
                        break
            
            # If no English, try any language
            if not transcript_text:
                for lang, subs in subtitles.items():
                    for sub in subs:
                        if sub.get('data'):
                            transcript_text = sub['data']
                            break
                    if transcript_text:
                        break
            
            # Parse VTT format (remove timestamps)
            if transcript_text:
                # Remove VTT headers and timestamps
                lines = transcript_text.split('\n')
                clean_lines = []
                for line in lines:
                    # Skip VTT headers and empty lines
                    if line.startswith('WEBVTT') or line.startswith('NOTE') or '-->' in line or not line.strip():
                        continue
                    # Skip cue identifiers (numbers)
                    if line.isdigit():
                        continue
                    clean_lines.append(line.strip())
                
                transcript = ' '.join(clean_lines)
                print(f"  ✅ Got transcript ({len(transcript)} chars)")
                return transcript[:10000]  # Limit to 10K chars for API
            
            return None
            
        except Exception as e:
            print(f"  ⚠️ Error getting transcript: {e}")
            return None
    
    @staticmethod
    def summarize_video(url: str, title: str = "", description: str = "", transcript: str = "") -> Optional[Dict]:
        """Summarize YouTube video using Claude"""
        try:
            print(f"  🤖 Summarizing with Claude...")
            
            # Build context from available data
            context_parts = []
            if title:
                context_parts.append(f"Title: {title}")
            if description:
                context_parts.append(f"Description: {description[:500]}")
            if transcript:
                context_parts.append(f"Transcript (first 3000 chars): {transcript[:3000]}")
            
            context = "\n".join(context_parts)
            
            prompt = f"""Ty si expert na sumarizáciu videí.

YouTube Video:
{context}

Vytvor detailný MARKDOWN report:

## 📋 Súhrn
3-5 viet o čom je video

## 🎯 Kľúčové Poznatky
- Bod 1
- Bod 2
- Bod 3
- (max 5 bodov)

## 🏷️ Kategórie
Vyber relevantné: #AI #Trading #Business #Code #Data #Security #Web #DevOps #Personal #Finance #atď.

## ⭐ Relevancia
Ohodnoť 1-5 hviezd pre AI/Tech komunitu

## 🔗 Odporúčanie
Jednoducho: "Sledovať" alebo "Preskočiť" + dôvod"""
            
            response = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=1200,
                messages=[{"role": "user", "content": prompt}]
            )
            
            summary_text = response.content[0].text
            
            return {
                'type': 'youtube_video',
                'url': url,
                'title': title,
                'description': description[:500] if description else '',
                'transcript_preview': transcript[:1000] if transcript else '',
                'has_full_transcript': bool(transcript),
                'summary': summary_text,
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
        """Summarize GitHub repo using Claude"""
        try:
            print(f"  🤖 Analyzing repo...")
            
            prompt = f"""Ty si expert na vyhodnocovanie GitHub projektov.

Projekt: {repo_info['repo']}
Owner: {repo_info['owner']}
URL: {repo_info['url']}
Popis: {repo_info.get('description', 'Bez popisu')}
Stars: {repo_info.get('stars', 0)} ⭐
Forks: {repo_info.get('forks', 0)}
Jazyk: {repo_info.get('language', 'Unknown')}
Topics: {', '.join(repo_info.get('topics', []))}
Posledná aktualizácia: {repo_info.get('updated_at', 'Unknown')}

README (prvých 2000 chars):
{repo_info.get('readme', 'Neni dostupny')[:2000]}

Vytvor MARKDOWN report:

## 📝 O Projekte
Čo projekt robí (1-2 vety)

## 🎯 Použitie
Na čo sa hodí a prečo by mal byť zaujímavý

## 💻 Technológie
Aké technológie používa

## ⭐ Kvalita
1-5 hviezd - ako je projekt spravovaný a ako je populárny

## 🏷️ Kategórie
Vyber relevantné tagy: #AI #Trading #Backend #Frontend #Data #ML #DevTools #atď.

## ✅ Odporúčanie
"Sledovať" alebo "Preskočiť" + krátky dôvod"""
            
            response = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}]
            )
            
            summary_text = response.content[0].text
            
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
                'summary': summary_text,
                'readme_preview': repo_info.get('readme', '')[:500],
                'processed_at': datetime.now().isoformat(),
                'source': 'email'
            }
        
        except Exception as e:
            print(f"  ❌ Error summarizing repo: {e}")
            return None

class ContentPreparator:
    """Prepare content data for vector database"""
    
    @staticmethod
    def prepare_youtube_batch(urls: List[str]) -> List[Dict]:
        """Process multiple YouTube videos"""
        results = []
        
        for url in urls:
            print(f"\n🎥 Processing YouTube: {url}")
            
            # Get video info
            video_info = YouTubeExtractor.get_video_info(url)
            if not video_info:
                continue
            
            # Get transcript
            transcript = YouTubeExtractor.get_transcript(url)
            
            # Summarize
            summary = YouTubeExtractor.summarize_video(
                url,
                video_info.get('title', ''),
                video_info.get('description', ''),
                transcript
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