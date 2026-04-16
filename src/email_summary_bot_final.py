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

# Pridaj src do path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from extractors_full import YouTubeExtractor, GitHubExtractor, ContentPreparator
except ImportError:
    print("❌ Error: extractors_full.py not found in src/")
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
        """Načítaj Gmail credentials"""
        try:
            creds_json = os.getenv("GMAIL_CREDENTIALS")
            if not creds_json:
                raise ValueError("GMAIL_CREDENTIALS nie je nastavené!")
            
            creds = json.loads(creds_json)
            print(f"✅ Loaded credentials for {creds.get('email')}")
            return creds
        except Exception as e:
            print(f"❌ Error loading credentials: {e}")
            raise
    
    def connect(self) -> imaplib.IMAP4_SSL:
        """Pripoj sa k Gmailu"""
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
        """Odpoj od Gmailu"""
        if self.mail:
            try:
                self.mail.close()
                self.mail.logout()
                print("✅ Disconnected from Gmail")
            except:
                pass
    
    def get_unread_emails(self, max_results: int = 10) -> List[Dict]:
        """Získaj nešpecifikované emaily"""
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
        """Parse email obsah"""
        status, msg_data = self.mail.fetch(msg_id, "(RFC822)")
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
        """Extrahuj text z emailu"""
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    try:
                        body = part.get_payload(decode=True).decode('utf-8')
                    except:
                        body = part.get_payload(decode=True).decode('latin-1', errors='ignore')
                    break
        else:
            try:
                body = msg.get_payload(decode=True).decode('utf-8')
            except:
                body = msg.get_payload(decode=True).decode('latin-1', errors='ignore')
        
        return body
    
    def mark_as_important(self, msg_ids: List[bytes]) -> bool:
        """Označ emaily ako důležité"""
        try:
            for msg_id in msg_ids:
                self.mail.store(msg_id, '+FLAGS', '\\Flagged')
            print(f"✅ Marked {len(msg_ids)} emails as important")
            return True
        except Exception as e:
            print(f"❌ Error marking as important: {e}")
            return False
    
    def add_label(self, msg_ids: List[bytes], label: str) -> bool:
        """Pridaj custom label k emailom"""
        try:
            for msg_id in msg_ids:
                self.mail.store(msg_id, '+X-GM-LABELS', label)
            print(f"✅ Added label '{label}' to {len(msg_ids)} emails")
            return True
        except Exception as e:
            print(f"❌ Error adding label: {e}")
            return False

class EmailFilter:
    """Filtruj a klasifikuj emaily podľa subject-u"""
    
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
        """Klasifikuj email a vráť filter info"""
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
        """Aplikuj filter na email"""
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
        """Pošli správu do Telegramu (s support pre dlhé správy)"""
        if not self.telegram_token or not self.telegram_chat_id:
            print("❌ Telegram config missing!")
            return False
        
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        
        # Telegram limit je 4096 znakov, takže rozdelíme na časti
        max_length = 4096
        
        if len(message) <= max_length:
            # Kratká správa — pošli naraz
            payload = {
                'chat_id': self.telegram_chat_id,
                'text': message,
                'parse_mode': 'Markdown'
            }
            
            try:
                response = requests.post(url, json=payload, timeout=10)
                if response.status_code == 200:
                    print("✅ Telegram message sent")
                    return True
                else:
                    print(f"❌ Telegram error: {response.text}")
                    return False
            except Exception as e:
                print(f"❌ Telegram exception: {e}")
                return False
        else:
            # Dlhá správa — rozdelíme na časti
            parts = []
            current_part = ""
            
            lines = message.split('\n')
            for line in lines:
                if len(current_part) + len(line) + 1 > max_length:
                    if current_part:
                        parts.append(current_part)
                    current_part = line
                else:
                    current_part += '\n' + line if current_part else line
            
            if current_part:
                parts.append(current_part)
            
            # Pošli všetky časti
            for i, part in enumerate(parts):
                payload = {
                    'chat_id': self.telegram_chat_id,
                    'text': part,
                    'parse_mode': 'Markdown'
                }
                
                try:
                    response = requests.post(url, json=payload, timeout=10)
                    if response.status_code != 200:
                        print(f"❌ Telegram error on part {i+1}: {response.text}")
                        return False
                except Exception as e:
                    print(f"❌ Telegram exception on part {i+1}: {e}")
                    return False
            
            print(f"✅ Sent {len(parts)} Telegram messages")
            return True
    
    def run(self):
        """Spusti email bot s úplným content extracting"""
        print(f"\n🤖 Email Summary Bot (Full Content Extraction) started at {datetime.now()}\n")
        
        try:
            # 1. Connect
            self.manager.connect()
            
            # 2. Get emails
            emails = self.manager.get_unread_emails(max_results=10)
            
            if not emails:
                print("📭 No unread emails")
                self.send_telegram("📭 Žiadne nové emaily.")
                return
            
            # 3. Initialize content storage
            all_content = {
                'youtube': [],
                'github': [],
                'emails_processed': len(emails),
                'timestamp': datetime.now().isoformat()
            }
            
            # 4. Apply filters and extract content
            print("\n🔍 Processing emails and extracting content...\n")
            
            for email_data in emails:
                print(f"\n📨 Processing: {email_data['subject']}")
                
                # Apply email filters
                filter_info = EmailFilter.classify_email(email_data)
                if filter_info['matched']:
                    EmailFilter.apply_filter(self.manager, email_data, filter_info)
                
                body = email_data['body']
                
                # Extract YouTube links
                yt_urls = YouTubeExtractor.extract_youtube_links(body)
                if yt_urls:
                    print(f"\n🎥 Found {len(yt_urls)} YouTube video(s)")
                    yt_data = ContentPreparator.prepare_youtube_batch(yt_urls)
                    all_content['youtube'].extend(yt_data)
                
                # Extract GitHub links
                gh_urls = GitHubExtractor.extract_github_links(body)
                if gh_urls:
                    print(f"\n🐙 Found {len(gh_urls)} GitHub repo(s)")
                    gh_data = ContentPreparator.prepare_github_batch(gh_urls)
                    all_content['github'].extend(gh_data)
            
            # 5. Save prepared data to JSON
            print("\n\n💾 Saving prepared data...")
            
            # Ensure we're in the right directory
            output_file = 'prepared_content.json'
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(all_content, f, indent=2, ensure_ascii=False)
            
            print(f"✅ Data saved to {output_file}")
            
            # Verify file was created
            if os.path.exists(output_file):
                print(f"✅ File exists: {os.path.abspath(output_file)}")
            else:
                print(f"❌ File not created!")
            
            # 6. Create Telegram messages
            print("\n📤 Creating Telegram messages...")
            telegram_messages = self._create_summary_messages(all_content)
            
            # 7. Send to Telegram
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
    
    def _create_summary_messages(self, content: Dict) -> List[str]:
        """Vytvor Telegram správy s detailným obsahom (môže byť viacero)"""
        messages = []
        
        # Header message
        header = f"📧 **Email Summary** - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        header += f"✅ Spracované {content['emails_processed']} email(ov)\n\n"
        messages.append(header)
        
        # YouTube section
        if content['youtube']:
            for i, video in enumerate(content['youtube'], 1):
                msg = f"🎥 **YouTube Video {i}**\n\n"
                msg += f"**{video.get('title', 'Unknown')}**\n"
                msg += f"🔗 {video['url']}\n\n"
                
                # Detailed notes
                notes = video.get('detailed_notes', '')
                if notes:
                    msg += f"📝 **Poznámky:**\n{notes}\n"
                
                if video.get('has_full_transcript'):
                    msg += "\n✅ Úplný prepis dostupný v prepared_content.json\n"
                
                messages.append(msg)
        
        # GitHub section
        if content['github']:
            for i, repo in enumerate(content['github'], 1):
                msg = f"🐙 **GitHub Repo {i}**\n\n"
                msg += f"**{repo['owner']}/{repo['repo']}**\n"
                msg += f"🔗 {repo['url']}\n"
                msg += f"⭐ Stars: {repo.get('stars', 0)}\n\n"
                
                # Detailed summary
                summary = repo.get('detailed_summary', '')
                if summary:
                    msg += f"📝 **Analýza:**\n{summary}\n"
                
                messages.append(msg)
        
        # Final message
        final = f"\n✅ **Všetky dáta uložené v prepared_content.json**\n"
        final += f"Timestamp: {content['timestamp']}"
        messages.append(final)
        
        return messages

if __name__ == "__main__":
    bot = EmailBot()
    bot.run()