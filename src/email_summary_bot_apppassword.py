#!/usr/bin/env python3
"""
Email AI Summary Bot - Simplified Version
"""

import os
import json
import imaplib
import email
from email.header import decode_header
from anthropic import Anthropic
import requests
from datetime import datetime

# Anthropic client
client = Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))

def get_gmail_creds():
    """Načítaj Gmail credentials"""
    try:
        creds_json = os.getenv("GMAIL_CREDENTIALS")
        print(f"[DEBUG] GMAIL_CREDENTIALS env var exists: {bool(creds_json)}")
        
        if not creds_json:
            raise ValueError("GMAIL_CREDENTIALS nie je nastavené!")
        
        creds = json.loads(creds_json)
        print(f"[DEBUG] Parsed JSON: type={creds.get('type')}, email={creds.get('email')}")
        
        return creds
    except json.JSONDecodeError as e:
        print(f"❌ JSON Parse Error: {e}")
        raise
    except Exception as e:
        print(f"❌ Error loading credentials: {e}")
        raise

def connect_gmail(email_addr, app_password):
    """Pripoj sa k Gmailu"""
    try:
        print(f"[DEBUG] Connecting to Gmail as {email_addr}...")
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(email_addr, app_password)
        mail.select("INBOX")
        print("[DEBUG] Connected successfully!")
        return mail
    except imaplib.IMAP4.error as e:
        print(f"❌ IMAP Error: {e}")
        raise

def get_unread_emails(mail, max_results=5):
    """Získaj nešpecifikované emaily"""
    try:
        status, messages = mail.search(None, "UNSEEN")
        
        if status != "OK":
            print(f"❌ Search failed: {status}")
            return []
        
        message_ids = messages[0].split()[:max_results]
        print(f"[DEBUG] Found {len(message_ids)} unread emails")
        
        emails = []
        for msg_id in message_ids:
            try:
                status, msg_data = mail.fetch(msg_id, "(RFC822)")
                if status == "OK":
                    msg = email.message_from_bytes(msg_data[0][1])
                    
                    # Extract info
                    subject = decode_header(msg.get("Subject", "No Subject"))[0][0]
                    if isinstance(subject, bytes):
                        subject = subject.decode('utf-8', errors='ignore')
                    
                    from_addr = msg.get("From", "Unknown")
                    
                    # Get body
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
                    
                    emails.append({
                        'subject': subject,
                        'from': from_addr,
                        'body': body[:1000]
                    })
            except Exception as e:
                print(f"⚠️ Error parsing email {msg_id}: {e}")
                continue
        
        return emails
    except Exception as e:
        print(f"❌ Error getting unread emails: {e}")
        return []

def summarize_emails(emails):
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

def send_telegram(message):
    """Pošli správu do Telegramu"""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print("❌ Telegram config missing!")
        return False
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'Markdown'
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print("✅ Telegram sent")
            return True
        else:
            print(f"❌ Telegram error: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Telegram exception: {e}")
        return False

def main():
    print(f"\n🤖 Email Summary Bot started at {datetime.now()}")
    
    try:
        # 1. Load credentials
        print("\n[STEP 1] Loading Gmail credentials...")
        creds = get_gmail_creds()
        email_addr = creds.get("email")
        app_password = creds.get("app_password")
        
        if not email_addr or not app_password:
            raise ValueError("Missing email or app_password in GMAIL_CREDENTIALS")
        
        # 2. Connect to Gmail
        print("\n[STEP 2] Connecting to Gmail...")
        mail = connect_gmail(email_addr, app_password)
        
        # 3. Get unread emails
        print("\n[STEP 3] Fetching unread emails...")
        emails = get_unread_emails(mail, max_results=5)
        mail.close()
        mail.logout()
        
        if not emails:
            print("📭 No unread emails")
            send_telegram("📭 Žiadne nové emaily.")
            return
        
        print(f"✅ Got {len(emails)} emails")
        
        # 4. Summarize
        print("\n[STEP 4] Summarizing with Claude...")
        summary = summarize_emails(emails)
        
        # 5. Send to Telegram
        print("\n[STEP 5] Sending to Telegram...")
        message = f"""📧 **Email Summary** - {datetime.now().strftime('%Y-%m-%d %H:%M')}

{summary}

---
*Bot spustený o 20:00*"""
        
        send_telegram(message)
        print("\n✅ Done!")
        
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        send_telegram(f"❌ Bot Error: {str(e)}")

if __name__ == "__main__":
    main()