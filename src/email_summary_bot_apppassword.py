#!/usr/bin/env python3
"""
Email AI Summary Bot - Extended Version with Email Actions
Features:
- Read unread emails
- Summarize with Claude
- Move emails to folders
- Mark as important/spam
- Delete emails
- Mark as read
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
    
    def get_unread_emails(self, max_results: int = 5) -> List[Dict]:
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
            'body': body[:1500],
            'date': msg.get("Date", "Unknown"),
            'message_id': msg.get("Message-ID", "")
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
    
    def mark_as_unread(self, msg_ids: List[bytes]) -> bool:
        """Označ emaily ako neprečítané"""
        try:
            for msg_id in msg_ids:
                self.mail.store(msg_id, '-FLAGS', '\\Seen')
            print(f"✅ Marked {len(msg_ids)} emails as unread")
            return True
        except Exception as e:
            print(f"❌ Error marking as unread: {e}")
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
    
    def mark_as_spam(self, msg_ids: List[bytes]) -> bool:
        """Presuň emaily do SPAM"""
        try:
            self.mail.select("INBOX")
            for msg_id in msg_ids:
                self.mail.copy(msg_id, "[Gmail]/Spam")
                self.mail.store(msg_id, '+FLAGS', '\\Deleted')
            print(f"✅ Marked {len(msg_ids)} emails as spam")
            return True
        except Exception as e:
            print(f"❌ Error marking as spam: {e}")
            return False
    
    def delete_email(self, msg_ids: List[bytes]) -> bool:
        """Vymaž emaily"""
        try:
            for msg_id in msg_ids:
                self.mail.store(msg_id, '+FLAGS', '\\Deleted')
            self.mail.expunge()
            print(f"✅ Deleted {len(msg_ids)} emails")
            return True
        except Exception as e:
            print(f"❌ Error deleting emails: {e}")
            return False
    
    def move_to_folder(self, msg_ids: List[bytes], folder: str) -> bool:
        """Presuň emaily do priečinka"""
        try:
            self.mail.select("INBOX")
            
            # Gmail folder names use [Gmail]/ prefix
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
    
    def create_filter(self, from_addr: str, label: str) -> bool:
        """Vytvor filter pre konkrétneho odosielateľa"""
        # POZNÁMKA: Toto sa dá urobiť iba cez Gmail API, nie IMAP
        # Pre teraz je to iba placeholder
        print(f"📋 Filter rule: Emails from {from_addr} → Label: {label}")
        return True

class EmailBot:
    def __init__(self):
        self.manager = EmailManager()
        self.telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    def summarize_emails(self, emails: List[Dict]) -> str:
        """Sumarizuj emaily cez Claude"""
        if not emails:
            return "Žiadne emaily na spracovanie"
        
        emails_text = "\n\n---\n\n".join([
            f"📧 Od: {e['from']}\n📌 Predmet: {e['subject']}\n\nObsah:\n{e['body']}"
            for e in emails
        ])
        
        prompt = f"""Ty si AI asistent, ktorý pomáhaš čítať a organizovať emaily.

Vytvor KRÁTKE zhrnutie týchto emailov:

{emails_text}

Požiadavky:
1. Slovenčina
2. Najdôležitejšie body
3. CTA (čo urobiť?)
4. Markdown formát
5. Buď stručný"""
        
        try:
            response = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text
        except Exception as e:
            print(f"❌ Claude API Error: {e}")
            return f"Error: {str(e)}"
    
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
        """Spusti email bot"""
        print(f"\n🤖 Email Summary Bot started at {datetime.now()}\n")
        
        try:
            # Connect
            self.manager.connect()
            
            # Get emails
            emails = self.manager.get_unread_emails(max_results=5)
            
            if not emails:
                print("📭 No unread emails")
                self.send_telegram("📭 Žiadne nové emaily.")
                return
            
            # Summarize
            print("\n📝 Summarizing with Claude...")
            summary = self.summarize_emails(emails)
            
            # Create message
            message = f"""📧 **Email Summary** - {datetime.now().strftime('%Y-%m-%d %H:%M')}

{summary}

---
*Bot spustený o 20:00*"""
            
            # Send to Telegram
            print("\n📤 Sending to Telegram...")
            self.send_telegram(message)
            
            # Mark emails as read (optional - comment out if you want to keep them unread)
            # msg_ids = [e['id'] for e in emails]
            # self.manager.mark_as_read(msg_ids)
            
            print("\n✅ Done!")
            
        except Exception as e:
            print(f"\n❌ Fatal error: {e}")
            self.send_telegram(f"❌ Bot Error: {str(e)}")
        finally:
            self.manager.disconnect()

if __name__ == "__main__":
    bot = EmailBot()
    bot.run()