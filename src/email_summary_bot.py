#!/usr/bin/env python3
"""
Email AI Summary Bot
- Číta nešpecifikované emaily z Gmailu
- Sumarizuje ich cez Claude API
- Pošle do Telegramu každý večer
"""

import os
import json
import base64
import pickle
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.api_core.client_options import ClientOptions
from google.cloud import gmail_v1
from anthropic import Anthropic
import requests
from datetime import datetime

# Inicializuj Anthropic client
client_anthropic = Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))

class EmailSummaryBot:
    def __init__(self):
        self.telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.gmail_client = self._init_gmail()
        
    def _init_gmail(self):
        """Inicializuj Gmail API"""
        # Credentials sú uložené v GitHub Secrets ako JSON
        creds_json = os.getenv("GMAIL_CREDENTIALS")
        creds = Credentials.from_authorized_user_info(json.loads(creds_json))
        
        # Refresh token ak je potrebné
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        
        return gmail_v1.GmailService(credentials=creds)
    
    def get_unread_emails(self, max_results=10):
        """Získaj prvé nešpecifikované emaily"""
        try:
            # Query: is:unread - emaily, ktoré sú nešpecifikované
            results = self.gmail_client.users().messages().list(
                userId='me',
                q='is:unread',
                maxResults=max_results
            ).execute()
            
            messages = results.get('messages', [])
            print(f"📧 Nájdené {len(messages)} nešpecifikovaných emailov")
            return messages
        except Exception as e:
            print(f"❌ Gmail error: {e}")
            return []
    
    def get_email_content(self, message_id):
        """Získaj obsah emailu"""
        try:
            message = self.gmail_client.users().messages().get(
                userId='me',
                id=message_id,
                format='full'
            ).execute()
            
            headers = message['payload']['headers']
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
            from_email = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown')
            
            # Získaj text tela emailu
            body = ""
            if 'parts' in message['payload']:
                for part in message['payload']['parts']:
                    if part['mimeType'] == 'text/plain':
                        if 'data' in part['body']:
                            body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                        break
            else:
                if 'body' in message['payload'] and 'data' in message['payload']['body']:
                    body = base64.urlsafe_b64decode(message['payload']['body']['data']).decode('utf-8')
            
            return {
                'id': message_id,
                'subject': subject,
                'from': from_email,
                'body': body[:2000]  # Limituj na 2000 znakov
            }
        except Exception as e:
            print(f"❌ Error getting email content: {e}")
            return None
    
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
            else:
                print(f"❌ Telegram error: {response.text}")
        except Exception as e:
            print(f"❌ Error sending to Telegram: {e}")
    
    def mark_as_read(self, message_ids):
        """Označ emaily ako prečítané"""
        try:
            self.gmail_client.users().messages().batchModify(
                userId='me',
                body={'ids': message_ids, 'addLabelIds': ['IMPORTANT']}
            ).execute()
            print(f"✅ Marked {len(message_ids)} emails as important")
        except Exception as e:
            print(f"⚠️ Could not mark emails: {e}")
    
    def run(self):
        """Spusti celý bot"""
        print(f"\n🤖 Email Summary Bot started at {datetime.now()}")
        
        # 1. Získaj nešpecifikované emaily
        unread_messages = self.get_unread_emails(max_results=5)
        
        if not unread_messages:
            self.send_to_telegram("📭 Žiadne nové emaily na spracovanie.")
            return
        
        # 2. Získaj obsah emailov
        emails = []
        message_ids = []
        for msg in unread_messages:
            email_data = self.get_email_content(msg['id'])
            if email_data:
                emails.append(email_data)
                message_ids.append(msg['id'])
        
        # 3. Sumarizuj cez Claude
        summary = self.summarize_emails(emails)
        
        # 4. Pošli do Telegramu
        telegram_message = f"""📧 **Email Summary** - {datetime.now().strftime('%Y-%m-%d %H:%M')}

{summary}

---
*Bot spustený automaticky o 20:00*"""
        
        self.send_to_telegram(telegram_message)
        
        # 5. Označ ako prečítané
        self.mark_as_read(message_ids)
        
        print("✅ Email summary completed")

if __name__ == "__main__":
    bot = EmailSummaryBot()
    bot.run()