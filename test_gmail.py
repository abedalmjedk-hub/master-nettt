# -*- coding: utf-8 -*-
import sys
import imaplib
sys.stdout.reconfigure(encoding='utf-8')

IMAP_EMAIL = "abedalmjedk@gmail.com"
IMAP_APP_PASSWORD = "emjb eeqn zldk deoh"

print("جاري الاتصال بالجيميل...")

try:
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(IMAP_EMAIL, IMAP_APP_PASSWORD)
    mail.select("inbox")
    
    status, messages = mail.search(None, 'ALL')
    total = len(messages[0].split()) if messages[0] else 0
    
    status2, unread = mail.search(None, 'UNSEEN')
    unread_count = len(unread[0].split()) if unread[0] else 0
    
    mail.logout()
    
    print("✅ تم الاتصال بالجيميل بنجاح!")
    print(f"الايميل: {IMAP_EMAIL}")
    print(f"اجمالي الرسائل: {total}")
    print(f"الرسائل غير المقروءة: {unread_count}")
    print("كل شيء يعمل! البوت جاهز.")

except imaplib.IMAP4.error as e:
    print(f"فشل الاتصال: {e}")
    print("تأكد من:")
    print("   1. ان كلمة المرور صحيحة (App Password)")
    print("   2. ان IMAP مفعل في اعدادات الجيميل")
    print("      جيميل > الاعدادات > عرض كل الاعدادات > اعادة التوجيه وPOP/IMAP > تمكين IMAP")

except Exception as e:
    print(f"خطا: {e}")

input("\nاضغط Enter للاغلاق...")
