# -*- coding: utf-8 -*-
import sys
import imaplib
import email
import re
from email.header import decode_header
sys.stdout.reconfigure(encoding='utf-8')

IMAP_EMAIL = "abedalmjedk@gmail.com"
IMAP_APP_PASSWORD = "emjb eeqn zldk deoh"

print("جاري الاتصال بالجيميل...")
mail = imaplib.IMAP4_SSL("imap.gmail.com")
mail.login(IMAP_EMAIL, IMAP_APP_PASSWORD)
mail.select("inbox")

# ابحث عن آخر 10 رسائل
status, messages = mail.search(None, 'ALL')
msg_ids = messages[0].split()
last_10 = msg_ids[-10:]  # آخر 10 رسائل

print(f"\nسيتم فحص آخر 10 رسائل:\n{'='*50}")

found = False
for msg_id in reversed(last_10):
    res, msg_data = mail.fetch(msg_id, '(RFC822)')
    if res != "OK":
        continue
    
    raw_email = msg_data[0][1]
    msg = email.message_from_bytes(raw_email)
    
    # استخراج المرسل
    from_raw = msg.get("From", "")
    subject_raw = msg.get("Subject", "")
    
    # فك تشفير الموضوع
    try:
        subject_bytes, encoding = decode_header(subject_raw)[0]
        if isinstance(subject_bytes, bytes):
            subject = subject_bytes.decode(encoding or "utf-8", errors="ignore")
        else:
            subject = str(subject_bytes)
    except:
        subject = subject_raw

    # فحص إذا كان من جوال بي
    is_jawwal = any(x in from_raw.lower() for x in ["jawwal", "jawwalpay"])
    
    print(f"المرسل: {from_raw}")
    print(f"الموضوع: {subject}")
    
    if is_jawwal:
        found = True
        print(">>> هذه رسالة جوال بي! <<<")
        
        # استخراج نص الرسالة
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() in ("text/plain", "text/html"):
                    try:
                        payload = part.get_payload(decode=True)
                        charset = part.get_content_charset() or "utf-8"
                        text = payload.decode(charset, errors="ignore")
                        clean = re.sub(r"<[^>]+>", " ", text)
                        clean = re.sub(r"\s+", " ", clean).strip()
                        body += clean + " "
                    except:
                        pass
        else:
            try:
                payload = msg.get_payload(decode=True)
                charset = msg.get_content_charset() or "utf-8"
                text = payload.decode(charset, errors="ignore")
                body = re.sub(r"<[^>]+>", " ", text)
                body = re.sub(r"\s+", " ", body).strip()
            except:
                pass
        
        print(f"\nنص الرسالة (أول 500 حرف):")
        print(body[:500])
        
        # محاولة استخراج الرقم والمبلغ
        phone_patterns = [
            r'من[:\s]+(\d{10,})',
            r'from[:\s]+(\d{10,})',
            r'(\d{10})',
            r'(\d{4}\s\d{3}\s\d{3})',
        ]
        amount_patterns = [
            r'ILS\s*([\d.]+)',
            r'(\d+\.?\d*)\s*ILS',
            r'بقيمة[:\s]*([\d.]+)',
            r'(\d+\.?\d*)\s*شيكل',
        ]
        
        print(f"\n--- نتائج الاستخراج ---")
        for p in phone_patterns:
            m = re.search(p, body)
            if m:
                print(f"رقم الهاتف المستخرج: {m.group(1)}")
                break
        else:
            print("رقم الهاتف: لم يُعثر عليه!")
            
        for p in amount_patterns:
            m = re.search(p, body)
            if m:
                print(f"المبلغ المستخرج: {m.group(1)} شيكل")
                break
        else:
            print("المبلغ: لم يُعثر عليه!")
        
        print('='*50)
        break
    
    print("-"*30)

if not found:
    print("\nلم يتم العثور على أي رسالة من جوال بي في آخر 10 رسائل!")
    print("تأكد أن الإيميل وصل لصندوق الوارد وليس Spam.")

mail.logout()
input("\nاضغط Enter للإغلاق...")
