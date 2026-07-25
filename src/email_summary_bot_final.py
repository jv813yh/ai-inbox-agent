#!/usr/bin/env python3
"""
Email AI Summary Bot - Full Content Extraction with Detailed Telegram Messages
"""

import os
import json
import imaplib
import email
from email.header import decode_header
from anthropic import Anthropic
import requests
from datetime import datetime
from typing import List, Dict
import sys
from bs4 import BeautifulSoup

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from extractors_full import YouTubeExtractor, GitHubExtractor, ContentPreparator, WebArticleExtractor
    from prompt_builder import PromptBuilder
    import llm
except ImportError:
    print("❌ Error: extractors_full.py or prompt_builder.py not found in src/")
    sys.exit(1)

# Anthropic client
client = Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))

class EmailManager:
    def __init__(self):
        self.creds = self.load_credentials()
        self.email_addr = self.creds.get("email")
        self.app_password = self.creds.get("app_password")
        self.mail = None

    def load_credentials(self) -> Dict:
        """Load Gmail credentials"""
        try:
            creds_json = os.getenv("GMAIL_CREDENTIALS")
            if not creds_json:
                raise ValueError("GMAIL_CREDENTIALS is not set!")

            creds = json.loads(creds_json)
            print(f"✅ Loaded credentials for {creds.get('email')}")
            return creds
        except Exception as e:
            print(f"❌ Error loading credentials: {e}")
            raise

    def connect(self) -> imaplib.IMAP4_SSL:
        """Connect to Gmail"""
        try:
            print(f"🔗 Connecting to Gmail as {self.email_addr}...")
            mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
            mail.login(self.email_addr, self.app_password)
            self.mail = mail
            print("✅ Connected to Gmail")
            return mail
        except Exception as e:
            print(f"❌ Connection error: {e}")
            raise

    def disconnect(self):
        """Disconnect from Gmail"""
        if self.mail:
            try:
                self.mail.close()
                self.mail.logout()
                print("✅ Disconnected from Gmail")
            except:
                pass

    def get_unread_emails(self, max_results: int = 10) -> List[Dict]:
        """Fetch unread emails from inbox"""
        try:
            self.mail.select("INBOX")
            status, messages = self.mail.search(None, "UNSEEN")

            if status != "OK":
                print(f"❌ Search failed: {status}")
                return []

            message_ids = messages[0].split()[:max_results]
            print(f"📧 Found {len(message_ids)} unread emails")

            emails = []
            for msg_id in message_ids:
                try:
                    email_data = self.parse_email(msg_id)
                    if email_data:
                        emails.append(email_data)
                except Exception as e:
                    print(f"⚠️ Error parsing email: {e}")
                    continue

            return emails
        except Exception as e:
            print(f"❌ Error getting unread emails: {e}")
            return []

    def parse_email(self, msg_id: bytes) -> Dict:
        """Parse email content"""
        status, msg_data = self.mail.fetch(msg_id, "(BODY.PEEK[])")
        if status != "OK":
            return None

        msg = email.message_from_bytes(msg_data[0][1])

        # Subject
        subject = decode_header(msg.get("Subject", "No Subject"))[0][0]
        if isinstance(subject, bytes):
            subject = subject.decode('utf-8', errors='ignore')

        # From
        from_addr = msg.get("From", "Unknown")

        # Body
        body = self._extract_body(msg)

        return {
            'id': msg_id,
            'subject': subject,
            'from': from_addr,
            'body': body[:5000],
            'date': msg.get("Date", "Unknown"),
            'message_id': msg.get("Message-ID", ""),
            'raw_msg': msg
        }

    def _extract_body(self, msg) -> str:
        """Extract text from email, falling back to HTML when no plain-text part exists."""
        plain = ""
        html = ""

        def _decode(part) -> str:
            raw = part.get_payload(decode=True)
            if not raw:
                return ""
            try:
                return raw.decode('utf-8')
            except Exception:
                return raw.decode('latin-1', errors='ignore')

        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                if ct == "text/plain" and not plain:
                    plain = _decode(part)
                elif ct == "text/html" and not html:
                    html = _decode(part)
        else:
            text = _decode(msg)
            if msg.get_content_type() == "text/html":
                html = text
            else:
                plain = text

        if plain:
            return plain

        # HTML-only email — strip tags so URL regexes can find links
        if html:
            soup = BeautifulSoup(html, 'html.parser')
            # Preserve href URLs that might not appear as visible text
            for a in soup.find_all('a', href=True):
                a.insert_after(f" {a['href']} ")
            return soup.get_text(separator=' ', strip=True)

        return ""

    def mark_as_read(self, msg_ids: List[bytes]) -> bool:
        """Mark emails as read (\\Seen flag)"""
        try:
            for msg_id in msg_ids:
                self.mail.store(msg_id, '+FLAGS', '\\Seen')
            print(f"✅ Marked {len(msg_ids)} emails as read")
            return True
        except Exception as e:
            print(f"❌ Error marking as read: {e}")
            return False

    def mark_as_important(self, msg_ids: List[bytes]) -> bool:
        """Mark emails as important"""
        try:
            for msg_id in msg_ids:
                self.mail.store(msg_id, '+FLAGS', '\\Flagged')
            print(f"✅ Marked {len(msg_ids)} emails as important")
            return True
        except Exception as e:
            print(f"❌ Error marking as important: {e}")
            return False

    def add_label(self, msg_ids: List[bytes], label: str) -> bool:
        """Add a custom Gmail label to emails"""
        try:
            for msg_id in msg_ids:
                self.mail.store(msg_id, '+X-GM-LABELS', label)
            print(f"✅ Added label '{label}' to {len(msg_ids)} emails")
            return True
        except Exception as e:
            print(f"❌ Error adding label: {e}")
            return False


class EmailFilter:
    """Filter and classify emails by subject keywords (controls Gmail labels/stars only)"""

    FILTERS = {
        'ai_text': {
            'keywords': ['AI interested stuff - text', 'AI stuff - text'],
            'label': 'AI_TEXT',
            'mark_important': True,
            'description': 'AI Related - Text Content'
        },
        'ai_video': {
            'keywords': ['AI interested stuff - video', 'AI stuff - video'],
            'label': 'AI_VIDEO',
            'mark_important': True,
            'description': 'AI Related - Video Content'
        }
    }

    @staticmethod
    def classify_email(email_data: Dict) -> Dict:
        """Classify email and return matching filter info"""
        subject = email_data['subject'].lower()

        for filter_key, filter_config in EmailFilter.FILTERS.items():
            for keyword in filter_config['keywords']:
                if keyword.lower() in subject:
                    return {
                        'matched': True,
                        'filter_key': filter_key,
                        'label': filter_config['label'],
                        'mark_important': filter_config['mark_important'],
                        'description': filter_config['description']
                    }

        return {'matched': False}

    @staticmethod
    def apply_filter(manager: EmailManager, email_data: Dict, filter_info: Dict) -> bool:
        """Apply Gmail label and star to matched email"""
        if not filter_info['matched']:
            return False

        msg_id = email_data['id']
        actions = []

        # Add label
        if manager.add_label([msg_id], filter_info['label']):
            actions.append(f"✅ Label: {filter_info['label']}")

        # Mark as important
        if filter_info['mark_important']:
            if manager.mark_as_important([msg_id]):
                actions.append("⭐ Marked as important")

        print(f"\n🔄 Applied filter '{filter_info['description']}':")
        for action in actions:
            print(f"  {action}")

        return True


class EmailBot:
    def __init__(self):
        self.manager = EmailManager()
        self.telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

    def send_telegram(self, message: str) -> bool:
        """Send plain-text message to Telegram, chunking at paragraph boundaries."""
        if not self.telegram_token or not self.telegram_chat_id:
            print("❌ Telegram config missing!")
            return False

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        chunks = self._chunk_message(message)

        for i, chunk in enumerate(chunks, 1):
            payload = {'chat_id': self.telegram_chat_id, 'text': chunk, 'parse_mode': 'HTML'}
            try:
                response = requests.post(url, json=payload, timeout=10)
                if response.status_code == 200:
                    print(f"✅ Telegram chunk {i}/{len(chunks)} sent")
                else:
                    print(f"❌ Telegram error (chunk {i}): {response.text}")
                    return False
            except Exception as e:
                print(f"❌ Telegram exception (chunk {i}): {e}")
                return False

        return True

    @staticmethod
    def _chunk_message(text: str, max_length: int = 4000) -> list:
        """Split text into chunks that respect paragraph boundaries."""
        if len(text) <= max_length:
            return [text]

        chunks = []
        # Split on blank lines (paragraph boundaries) first
        paragraphs = text.split('\n\n')
        current = ""

        for para in paragraphs:
            candidate = (current + "\n\n" + para).strip() if current else para
            if len(candidate) <= max_length:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                # Single paragraph larger than limit — split by line
                if len(para) > max_length:
                    for line in para.split('\n'):
                        candidate = (current + "\n" + line).strip() if current else line
                        if len(candidate) <= max_length:
                            current = candidate
                        else:
                            if current:
                                chunks.append(current)
                            current = line
                else:
                    current = para

        if current:
            chunks.append(current)

        return chunks

    def run(self):
        """Run the email bot with full content extraction"""
        print(f"\n🤖 Email Summary Bot started at {datetime.now()}\n")

        try:
            # 1. Connect
            self.manager.connect()

            # 2. Get emails
            emails = self.manager.get_unread_emails(max_results=10)

            if not emails:
                print("📭 No unread emails")
                self.send_telegram("📭 No new emails.")
                return

            # 3. Initialize content storage
            all_content = {
                'youtube': [],
                'github': [],
                'articles': [],
                'plain_emails': [],
                'emails_processed': len(emails),
                'timestamp': datetime.now().isoformat()
            }

            # 4. Process every email — auto-detect content type from body
            print("\n🔍 Processing emails and extracting content...\n")

            for email_data in emails:
                print(f"\n📨 Processing: {email_data['subject']}")

                # Apply Gmail labels/stars (optional, subject-based)
                filter_info = EmailFilter.classify_email(email_data)
                if filter_info['matched']:
                    EmailFilter.apply_filter(self.manager, email_data, filter_info)

                body = email_data['body']
                subject = email_data.get('subject', '')
                found_special = False

                # Determine source label for Telegram display
                if subject in ('AI_VIDEO_BOT', 'AI_TEXT_BOT'):
                    source = '🤖 AI Content Collection'
                else:
                    source = email_data.get('from', 'Unknown sender')

                # Auto-detect: YouTube links in body
                yt_urls = YouTubeExtractor.extract_youtube_links(body)
                if yt_urls:
                    print(f"\n🎥 Found {len(yt_urls)} YouTube video(s)")
                    yt_data = ContentPreparator.prepare_youtube_batch(yt_urls, email_body=body)
                    for item in yt_data:
                        item['source'] = source
                    all_content['youtube'].extend(yt_data)
                    found_special = True

                # Auto-detect: GitHub links in body
                gh_urls = GitHubExtractor.extract_github_links(body)
                if gh_urls:
                    print(f"\n🐙 Found {len(gh_urls)} GitHub repo(s)")
                    gh_data = ContentPreparator.prepare_github_batch(gh_urls)
                    for item in gh_data:
                        item['source'] = source
                    all_content['github'].extend(gh_data)
                    found_special = True

                # Auto-detect: article/blog links (non-YouTube, non-GitHub URLs)
                article_urls = WebArticleExtractor.extract_urls(body)
                if article_urls:
                    print(f"\n📰 Found {len(article_urls)} article link(s)")
                    for art_url in article_urls:
                        article_data = WebArticleExtractor.fetch_article(art_url)
                        if article_data:
                            summary = WebArticleExtractor.summarize_article(article_data)
                            if summary:
                                summary['source'] = source
                                all_content['articles'].append(summary)
                    found_special = True

                # Plain email — no special links → summarize with Claude
                if not found_special:
                    print(f"\n📝 Plain email — summarizing with Claude...")
                    summary = self._summarize_plain_email(email_data)
                    summary['source'] = source
                    all_content['plain_emails'].append(summary)

            # 5. Mark all processed emails as read
            processed_ids = [e['id'] for e in emails]
            self.manager.mark_as_read(processed_ids)

            # 7. Save prepared data to JSON
            print("\n\n💾 Saving prepared data...")
            output_file = 'prepared_content.json'

            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(all_content, f, indent=2, ensure_ascii=False)

            print(f"✅ Data saved to {output_file}")

            if os.path.exists(output_file):
                print(f"✅ File exists: {os.path.abspath(output_file)}")
            else:
                print(f"❌ File not created!")

            # 8. Create Telegram messages
            print("\n📤 Creating Telegram messages...")
            telegram_messages = self._create_summary_messages(all_content)

            # 9. Send to Telegram
            for i, msg in enumerate(telegram_messages, 1):
                print(f"\n📤 Sending message {i}/{len(telegram_messages)}...")
                self.send_telegram(msg)

            print("\n✅ Done!")

        except Exception as e:
            print(f"\n❌ Fatal error: {e}")
            import traceback
            traceback.print_exc()
            self.send_telegram(f"❌ Bot Error: {str(e)}")
        finally:
            self.manager.disconnect()

    def _summarize_plain_email(self, email_data: Dict) -> Dict:
        """Summarize a plain email using Claude"""
        try:
            response = llm.create_message(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": PromptBuilder.plain_email(
                        email_data['subject'],
                        email_data['from'],
                        email_data['body']
                    )
                }]
            )
            raw = response.content[0].text
        except Exception as e:
            print(f"⚠️ Claude summarization failed: {e}")
            raw = email_data['body'][:500]

        marker = "🧠 MY TAKE:"
        idx = raw.find(marker)
        summary = raw[:idx].strip() if idx != -1 else raw.strip()
        my_take = raw[idx:].strip() if idx != -1 else ""

        return {
            'subject': email_data['subject'],
            'from': email_data['from'],
            'date': email_data['date'],
            'summary': summary,
            'my_take': my_take,
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _esc(text: str) -> str:
        return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    @staticmethod
    def _one_liner(summary: str) -> str:
        """
        Extract the ONE-LINE SUMMARY marker from article summaries (ARTICLE_V3),
        or fall back to the first meaningful sentence for other content types.
        """
        marker = '📌 ONE-LINE SUMMARY:'
        idx = summary.find(marker)
        if idx != -1:
            rest = summary[idx + len(marker):].strip()
            return rest.split('\n')[0].strip()
        # Fallback: first sentence up to '. ' or first line
        for sep in ('. ', '\n'):
            pos = summary.find(sep)
            if 0 < pos < 250:
                return summary[:pos + 1].strip()
        return summary[:180].strip()

    def _create_summary_messages(self, content: Dict) -> List[str]:
        """
        Build Telegram messages in two passes:
          1. A single Quick Digest overview — one line per item across all categories.
          2. One detailed message per item — teacher-style explanation with all sections.
        """
        esc = self._esc

        youtube  = content.get('youtube', [])
        articles = content.get('articles', [])
        github   = content.get('github', [])
        emails   = content.get('plain_emails', [])
        total    = len(youtube) + len(articles) + len(github) + len(emails)

        messages = []

        # ── Message 1: Quick Digest ───────────────────────────────────────────
        digest = (
            f"📧 <b>AI Digest</b> — "
            f"<i>{datetime.now().strftime('%Y-%m-%d %H:%M')}</i>\n"
            f"{total} item(s) summarised below.\n"
        )

        if youtube:
            digest += f"\n🎥 <b>YouTube ({len(youtube)})</b>\n"
            for i, v in enumerate(youtube, 1):
                title    = esc(v.get('title', 'Unknown'))
                url      = esc(v.get('url', ''))
                summary  = v.get('summary', '')
                one_line = esc(self._one_liner(summary)) if summary else ''
                source   = esc(v.get('source', ''))
                digest += f"  {i}. <a href=\"{url}\">{title}</a>"
                if source:
                    digest += f"  <i>· {source}</i>"
                digest += "\n"
                if one_line:
                    digest += f"     ↳ {one_line}\n"

        if articles:
            digest += f"\n📰 <b>Articles ({len(articles)})</b>\n"
            for i, a in enumerate(articles, 1):
                title    = esc(a.get('title', 'Untitled'))
                url      = esc(a.get('url', ''))
                summary  = a.get('summary', '')
                one_line = esc(self._one_liner(summary)) if summary else ''
                source   = esc(a.get('source', ''))
                digest += f"  {i}. <a href=\"{url}\">{title}</a>"
                if source:
                    digest += f"  <i>· {source}</i>"
                digest += "\n"
                if one_line:
                    digest += f"     ↳ {one_line}\n"

        if github:
            digest += f"\n🐙 <b>GitHub ({len(github)})</b>\n"
            for i, r in enumerate(github, 1):
                name     = esc(f"{r['owner']}/{r['repo']}")
                url      = esc(r.get('url', ''))
                stars    = r.get('stars', 0)
                summary  = r.get('summary', '')
                one_line = esc(self._one_liner(summary)) if summary else ''
                source   = esc(r.get('source', ''))
                digest += f"  {i}. <a href=\"{url}\">{name}</a>  ⭐{stars}"
                if source:
                    digest += f"  <i>· {source}</i>"
                digest += "\n"
                if one_line:
                    digest += f"     ↳ {one_line}\n"

        if emails:
            digest += f"\n📩 <b>Other emails ({len(emails)})</b>\n"
            for i, e in enumerate(emails, 1):
                digest += (
                    f"  {i}. {esc(e['subject'])} — <i>{esc(e['from'])}</i>\n"
                )

        messages.append(digest.strip())

        # ── Messages 2…N: section banners + one detail message per item ─────────

        def section_banner(icon: str, title: str, count: int) -> str:
            line = "━" * 28
            return f"{line}\n{icon}  <b>{title}</b>  ({count})\n{line}"

        if youtube:
            messages.append(section_banner("🎥", "YOUTUBE VIDEOS FROM EMAIL", len(youtube)))
            for video in youtube:
                block  = f"🎥 <b>{esc(video.get('title', 'Unknown'))}</b>\n"
                block += f"🔗 <a href=\"{esc(video['url'])}\">Watch on YouTube</a>\n"
                if video.get('source'):
                    block += f"📌 <i>Source: {esc(video['source'])}</i>\n"
                if video.get('has_full_transcript'):
                    block += "<i>✅ Transcript sampled from full video</i>\n"
                block += "\n"
                if video.get('summary'):
                    block += esc(video['summary']) + "\n"
                if video.get('my_take'):
                    block += "\n" + esc(video['my_take']) + "\n"
                messages.append(block.strip())

        if articles:
            messages.append(section_banner("📰", "ARTICLES &amp; BLOGS FROM EMAIL", len(articles)))
            for art in articles:
                block  = f"📰 <b>{esc(art.get('title', 'Untitled'))}</b>\n"
                block += f"🔗 <a href=\"{esc(art['url'])}\">Read article</a>\n"
                if art.get('source'):
                    block += f"📌 <i>Source: {esc(art['source'])}</i>\n"
                block += "\n"
                if art.get('summary'):
                    block += esc(art['summary']) + "\n"
                if art.get('my_take'):
                    block += "\n" + esc(art['my_take']) + "\n"
                messages.append(block.strip())

        if github:
            messages.append(section_banner("🐙", "GITHUB REPOS FROM EMAIL", len(github)))
            for repo in github:
                name   = f"{repo['owner']}/{repo['repo']}"
                block  = f"🐙 <b>{esc(name)}</b>  ⭐ {repo.get('stars', 0)}\n"
                block += f"🔗 <a href=\"{esc(repo['url'])}\">Open repo</a>\n"
                if repo.get('source'):
                    block += f"📌 <i>Source: {esc(repo['source'])}</i>\n"
                block += "\n"
                if repo.get('summary'):
                    block += esc(repo['summary']) + "\n"
                if repo.get('my_take'):
                    block += "\n" + esc(repo['my_take']) + "\n"
                messages.append(block.strip())

        if emails:
            messages.append(section_banner("📩", "OTHER EMAILS", len(emails)))
            for em in emails:
                block  = f"📩 <b>{esc(em['subject'])}</b>\n"
                block += f"<i>{esc(em['from'])}</i> · <i>{esc(em['date'])}</i>\n\n"
                if em.get('summary'):
                    block += esc(em['summary']) + "\n"
                if em.get('my_take'):
                    block += "\n" + esc(em['my_take']) + "\n"
                messages.append(block.strip())

        return messages


if __name__ == "__main__":
    bot = EmailBot()
    bot.run()
