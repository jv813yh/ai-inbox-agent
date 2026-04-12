#!/usr/bin/env python3
"""
Email AI Summary Bot - Smart Filtering Version
Features:
- Read unread emails
- Intelligent filtering based on subject
- Auto-label AI_TEXT and AI_VIDEO
- Summarize with Claude
- Apply actions automatically
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
            print(f"[DEBUG] Message IDs: {message_ids}")
            
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
        print(f"[DEBUG] Parsing email with ID: {msg_id}")
        
        status, msg_data = self.mail.fetch(msg_id, "(RFC822)")
        print(f"[DEBUG] Fetch status: {status}")  # ← PRIDAJ
        
        if status != "OK":
            print(f"[DEBUG] Fetch failed!")  # ← PRIDAJ
            return None
        
        msg = email.message_from_bytes(msg_data[0][1])
        print(f"[DEBUG] Message parsed from bytes")  # ← PRIDAJ
        
        # Subject
        subject = decode_header(msg.get("Subject", "No Subject"))[0][0]
        if isinstance(subject, bytes):
            subject = subject.decode('utf-8', errors='ignore')
        print(f"[DEBUG] Subject: {subject}")  # ← PRIDAJ
        
        # From
        from_addr = msg.get("From", "Unknown")
        print(f"[DEBUG] From: {from_addr}")  # ← PRIDAJ
        
        # Body
        body = self._extract_body(msg)
        print(f"[DEBUG] Body length: {len(body)}")  # ← PRIDAJ
        
        email_data = {
            'id': msg_id,
            'subject': subject,
            'from': from_addr,
            'body': body[:2000],
            'date': msg.get("Date", "Unknown"),
            'message_id': msg.get("Message-ID", ""),
            'raw_msg': msg
        }
        
        print(f"[DEBUG] Email data created successfully")  # ← PRIDAJ
        return email_data
    
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
    
    # ======== EMAIL ACTIONS ========
    
    def mark_as_read(self, msg_ids: List[bytes]) -> bool:
        """Označ emaily ako prečítané"""
        try:
            for msg_id in msg_ids:
                self.mail.store(msg_id, '+FLAGS', '\\Seen')
            print(f"✅ Marked {len(msg_ids)} emails as read")
            return True
        except Exception as e:
            print(f"❌ Error marking as read: {e}")
            return False
    
    def mark_as_important(self, msg_ids: List[bytes]) -> bool:
        """Označ emaily ako důležité (add IMPORTANT label)"""
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
    
    def move_to_folder(self, msg_ids: List[bytes], folder: str) -> bool:
        """Presuň emaily do priečinka"""
        try:
            self.mail.select("INBOX")
            
            gmail_folders = {
                'archive': '[Gmail]/All Mail',
                'drafts': '[Gmail]/Drafts',
                'sent': '[Gmail]/Sent Mail',
                'spam': '[Gmail]/Spam',
                'trash': '[Gmail]/Trash',
                'important': '[Gmail]/Important'
            }
            
            target_folder = gmail_folders.get(folder.lower(), folder)
            
            for msg_id in msg_ids:
                self.mail.copy(msg_id, target_folder)
                self.mail.store(msg_id, '+FLAGS', '\\Deleted')
            
            self.mail.expunge()
            print(f"✅ Moved {len(msg_ids)} emails to {target_folder}")
            return True
        except Exception as e:
            print(f"❌ Error moving emails: {e}")
            return False

class EmailFilter:
    """Filtruj a klasifikuj emaily podľa subject-u"""
    
    # Definuj filter pravidlá
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
    

class LinkExtractor:
    """Extrahuj linky z emailov"""
    
    @staticmethod
    def extract_links(email_body: str) -> Dict[str, List[str]]:
        """Extrahuj všetky linky a kategorizuj ich"""
        
        # Regex na URLs
        url_pattern = r'https?://[^\s\]<>"{}|\\^`]+'
        links = re.findall(url_pattern, email_body)
        
        categorized = {
            'github': [],
            'youtube': [],
            'other': []
        }
        
        for link in links:
            domain = urlparse(link).netloc.lower()
            
            if 'github.com' in domain:
                categorized['github'].append(link)
            elif 'youtube.com' in domain or 'youtu.be' in domain:
                categorized['youtube'].append(link)
            else:
                categorized['other'].append(link)
        
        return categorized
    
    @staticmethod
    def format_links(links: Dict[str, List[str]]) -> str:
        """Formátuj linky na pekný výstup"""
        output = []
        
        if links['github']:
            output.append("🐙 **GitHub Repos:**")
            for link in links['github']:
                output.append(f"  • {link}")
        
        if links['youtube']:
            output.append("🎥 **YouTube Videos:**")
            for link in links['youtube']:
                output.append(f"  • {link}")
        
        if links['other']:
            output.append("🔗 **Other Links:**")
            for link in links['other']:
                output.append(f"  • {link}")
        
        return "\n".join(output) if output else ""

class EmailBot:
    def __init__(self):
        self.manager = EmailManager()
        self.telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    def summarize_emails(self, emails: List[Dict]) -> str:
        """Sumarizuj emaily cez Claude"""
        if not emails:
            return "Žiadne emaily na spracovanie"
        
        # Zoskupuj podľa typu
        ai_text = [e for e in emails if 'AI_TEXT' in e.get('labels', [])]
        ai_video = [e for e in emails if 'AI_VIDEO' in e.get('labels', [])]
        other = [e for e in emails if 'AI_TEXT' not in e.get('labels', []) and 'AI_VIDEO' not in e.get('labels', [])]
        
        sections = []
        
        if ai_text:
            sections.append(self._summarize_section("📝 AI Interested - Text", ai_text))
        
        if ai_video:
            sections.append(self._summarize_section("🎥 AI Interested - Video", ai_video))
        
        if other:
            sections.append(self._summarize_section("📧 Other Emails", other))
        
        return "\n\n".join(sections)
    
    def _summarize_section(self, title: str, emails: List[Dict]) -> str:
        """Sumarizuj jednu sekciu emailov"""
        if not emails:
            return ""
        
        emails_text = "\n\n---\n\n".join([
            f"Od: {e['from']}\nPredmet: {e['subject']}\n\nObsah:\n{e['body']}"
            for e in emails
        ])
        
        prompt = f"""Vytvor KRÁTKE zhrnutie týchto emailov v sekcii: {title}

{emails_text}

Požiadavky:
1. Slovenčina
2. Max 3-5 riadkov
3. Vyzdvihni CTA (čo urobiť)
4. Markdown"""
        
        try:
            response = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )
            all_links = {}
            for e in emails:
                for link_type, link_list in e.get('links', {}).items():
                    if link_type not in all_links:
                        all_links[link_type] = []
                    all_links[link_type].extend(link_list)
            
            section_text = f"**{title}**\n\n{response.content[0].text}"
            
            if any(all_links.values()):
                section_text += "\n\n" + LinkExtractor.format_links(all_links)
                
            return section_text
        except Exception as e:
            print(f"❌ Claude API Error: {e}")
            return f"**{title}**\nError summarizing"
    
    def send_telegram(self, message: str) -> bool:
        """Pošli správu do Telegramu"""
        if not self.telegram_token or not self.telegram_chat_id:
            print("❌ Telegram config missing!")
            return False
        
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
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
    
    def run(self):
        """Spusti email bot s filteringom"""
        print(f"\n🤖 Email Summary Bot (Smart Filtering) started at {datetime.now()}\n")
        
        try:
            # Connect
            self.manager.connect()
            
            # Get emails
            emails = self.manager.get_unread_emails(max_results=10)
            
            if not emails:
                print("📭 No unread emails")
                self.send_telegram("📭 Žiadne nové emaily.")
                return
            
            # Apply filters
            print("\n🔍 Applying filters...")
            filtered_emails = []
            
            for email_data in emails:
                filter_info = EmailFilter.classify_email(email_data)
                
                if filter_info['matched']:
                    print(f"\n✨ Matched: {email_data['subject']}")
                    EmailFilter.apply_filter(self.manager, email_data, filter_info)
                    email_data['labels'] = [filter_info['label']]
                    filtered_emails.append(email_data)
                else:
                    print(f"\n📧 Regular: {email_data['subject']}")
                    email_data['labels'] = []
                    filtered_emails.append(email_data)
            
            # Summarize
            print("\n📝 Summarizing with Claude...")
            summary = self.summarize_emails(filtered_emails)
            
            # Create message
            message = f"""📧 **Email Summary** - {datetime.now().strftime('%Y-%m-%d %H:%M')}

{summary}

---
*Bot spustený o 20:00 s inteligentným filteringom*"""
            
            # Send to Telegram
            print("\n📤 Sending to Telegram...")
            self.send_telegram(message)
            
            print("\n✅ Done!")
            
        except Exception as e:
            print(f"\n❌ Fatal error: {e}")
            self.send_telegram(f"❌ Bot Error: {str(e)}")
        finally:
            self.manager.disconnect()

if __name__ == "__main__":
    bot = EmailBot()
    bot.run()