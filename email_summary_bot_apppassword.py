#!/usr/bin/env python3
"""
Email AI Summary Bot (Version 2 - App Password)
- Číta nešpecifikované emaily z Gmailu (cez App Password)
- Sumarizuje ich cez Claude API
- Pošle do Telegramu každý večer
"""

import os
import json
import base64
import imaplib
import email
from email.header import decode_header
from anthropic import Anthropic
import requests
from datetime import datetime

# Inicializuj Anthropic client
client_anthropic = Anthropic(api_key=os.getenv("CLAUDE_API_KEY_GITHUB_EMAIL"))

class EmailSummaryBot:
    def __init__(self):
        self.telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        
        # Načítaj Gmail credentials
        gmail_creds_json = os.getenv("GMAIL_CREDENTIALS")
        self.gmail_creds = json.loads(gmail_creds_json)
        
        self.gmail_email = self.gmail_creds.get("email")
        self.gmail_app_password = self.gmail_creds.get("app_password")
        
        if not self.gmail_email or not self.gmail_app_password:
            raise ValueError("GMAIL_CREDENTIALS chýba 'email' alebo 'app_password'")
    
    def connect_to_gmail(self):
        """Pripoj sa k Gmailu cez IMAP"""
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(self.gmail_email, self.gmail_app_password)
            mail.select("INBOX")
            return mail
        except imaplib.IMAP4.error as e:
            print(f"❌ Gmail IMAP connection error: {e}")
            print("   Skontroluj: email, app_password, alebo 2FA")
            raise
    
    def get_unread_emails(self, max_results=5):
        """Získaj nešpecifikované emaily"""
        try:
            mail = self.connect_to_gmail()
            
            # Vyhľadaj nešpecifikované emaily
            status, messages = mail.search(None, "UNSEEN")
            
            if status != "OK":
                print(f"❌ Search failed: {status}")
                return []
            
            message_ids = messages[0].split()[:max_results]
            print(f"📧 Nájdené {len(message_ids)} nešpecifikovaných emailov")
            
            emails = []
            for msg_id in message_ids:
                status, msg_data = mail.fetch(msg_id, "(RFC822)")
                if status == "OK":
                    email_message = email.message_from_bytes(msg_data[0][1])
                    email_data = self._parse_email(email_message, msg_id)
                    if email_data:
                        emails.append(email_data)
            
            mail.close()
            mail.logout()
            return emails
            
        except Exception as e:
            print(f"❌ Error getting unread emails: {e}")
            return []
    
    def _parse_email(self, email_message, msg_id):
        """Parsuj email obsah"""
        try:
            # Subject
            subject = self._decode_header(email_message.get("Subject", "No Subject"))
            
            # From
            from_email = email_message.get("From", "Unknown")
            
            # Body
            body = ""
            if email_message.is_multipart():
                for part in email_message.walk():
                    if part.get_content_type() == "text/plain":
                        try:
                            body = part.get_payload(decode=True).decode('utf-8')
                        except:
                            body = part.get_payload(decode=True).decode('latin-1')
                        break
            else:
                try:
                    body = email_message.get_payload(decode=True).decode('utf-8')
                except:
                    body = email_message.get_payload(decode=True).decode('latin-1')
            
            return {
                'id': msg_id,
                'subject': subject,
                'from': from_email,
                'body': body[:2000]  # Limituj na 2000 znakov
            }
        except Exception as e:
            print(f"⚠️ Error parsing email: {e}")
            return None
    
    def _decode_header(self, header_text):
        """Dekóduj email header"""
        try:
            decoded_parts = decode_header(header_text)
            result = ""
            for part, encoding in decoded_parts:
                if isinstance(part, bytes):
                    result += part.decode(encoding or 'utf-8')
                else:
                    result += part
            return result
        except:
            return str(header_text)
    
    def summarize_emails(self, emails):
        """Sumarizuj emaily cez Claude API"""
        if not emails:
            return "Žiadne emaily na spracovanie"
        
        emails_text = "\n\n---\n\n".join([
            f"📧 Od: {e['from']}\n📌 Predmet: {e['subject']}\n\nObsah:\n{e['body']}"
            for e in emails
        ])
        
        prompt = f"""Ty si AI asistent, ktorý pomáhaš čítať a organizovať emaily.

Získal si nasledovné nešpecifikované emaily. Vytvor stručný, ale informatívny zhrnutie:

{emails_text}

POŽIADAVKY:
1. Zhrnutie by malo byť v slovenčine
2. Zameraj sa na najdôležitejšie body
3. Vyzdvihni akýchkoľvek CTA (calls to action) - čo je potrebné urobiť
4. Formátuj výstup tak, aby sa dobre čítal v Telegramu (Markdown)
5. Ak je veľa emailov, zoskupuj ich podľa tém
6. Buď stručný a na vec

Vráť výstup v Markdowne s jasnou štruktúrou."""
        
        response = client_anthropic.messages.create(
            model="claude-opus-4-6",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
        
        return response.content[0].text
    
    def send_to_telegram(self, message):
        """Pošli správu do Telegramu"""
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {
            'chat_id': self.telegram_chat_id,
            'text': message,
            'parse_mode': 'Markdown'
        }
        
        try:
            response = requests.post(url, json=payload)
            if response.status_code == 200:
                print("✅ Telegram message sent successfully")
                return True
            else:
                print(f"❌ Telegram error: {response.text}")
                return False
        except Exception as e:
            print(f"❌ Error sending to Telegram: {e}")
            return False
    
    def run(self):
        """Spusti celý bot"""
        print(f"\n🤖 Email Summary Bot started at {datetime.now()}")
        
        try:
            # 1. Získaj nešpecifikované emaily
            emails = self.get_unread_emails(max_results=5)
            
            if not emails:
                self.send_to_telegram("📭 Žiadne nové emaily na spracovanie.")
                return
            
            # 2. Sumarizuj cez Claude
            summary = self.summarize_emails(emails)
            
            # 3. Pošli do Telegramu
            telegram_message = f"""📧 **Email Summary** - {datetime.now().strftime('%Y-%m-%d %H:%M')}

{summary}

---
*Bot spustený automaticky o 20:00*"""
            
            self.send_to_telegram(telegram_message)
            
            print("✅ Email summary completed")
            
        except Exception as e:
            print(f"❌ Fatal error: {e}")
            self.send_to_telegram(f"❌ Email Bot Error: {str(e)}")

if __name__ == "__main__":
    bot = EmailSummaryBot()
    bot.run()