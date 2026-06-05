# auto_backup.py – مراقبة تغييرات الملفات وإنشاء نسخ احتياطية تلقائية
# ---------------------------------------------------------------
# المتطلبات: تثبيت مكتبة watchdog
#   pip install watchdog
# ---------------------------------------------------------------
# هذا السكربت يراقب مجلد المشروع (c:/Users/LAPTOP/OneDrive/Desktop/ماستر نت/imad1)
# عند حدوث أي تعديل (إنشاء، تعديل، حذف) على أي ملف داخل المجلد،
# يقوم بنسخ جميع ملفات المشروع إلى مجلد "backup" داخل نفس المسار مع
# اسم المجلد يحتوي على طابع زمني (YYYYMMDD_HHMMSS).
# الهدف: حفظ نسخة احتياطية تلقائية بعد كل تعديل لتجنب فقدان البيانات.
# ---------------------------------------------------------------
import os
import sys
import time
import shutil
import smtplib
from email.message import EmailMessage
from datetime import datetime
from pathlib import Path

# مسار المشروع
PROJECT_ROOT = Path(r"c:/Users/LAPTOP/OneDrive/Desktop/ماستر نت/imad1")
# مجلد النسخ الاحتياطية داخل المشروع
BACKUP_ROOT = PROJECT_ROOT / "backup"

# إعدادات البريد الإلكتروني (املأ القيم المناسبة)
EMAIL_HOST = "smtp.example.com"
EMAIL_PORT = 587
EMAIL_USER = "your_email@example.com"
EMAIL_PASS = "your_password"
EMAIL_RECIPIENT = "recipient@example.com"

# عدد النسخ الاحتياطية التي يجب الاحتفاظ بها
MAX_BACKUPS = 5

def retain_backups():
    """حافظ على آخر MAX_BACKUPS نسخة واحذف الأقدم"""
    try:
        backups = sorted([d for d in BACKUP_ROOT.iterdir() if d.is_dir()], reverse=True)
        old_backups = backups[MAX_BACKUPS:]
        for old in old_backups:
            shutil.rmtree(old)
            print(f"🗑️ حذف نسخة قديمة: {old}")
    except Exception as e:
        print(f"⚠️ فشل حذف النسخ القديمة: {e}")

def send_email_notification(subject, body):
    """إرسال بريد إلكتروني باستخدام إعدادات SMTP"""
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = EMAIL_USER
        msg["To"] = EMAIL_RECIPIENT
        msg.set_content(body)
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)
        print("📧 تم إرسال إشعار البريد الإلكتروني")
    except Exception as e:
        print(f"⚠️ فشل إرسال البريد الإلكتروني: {e}")

def create_timestamped_backup():
    """إنشاء نسخة احتياطية للملفات كلها داخل مجلد فرعي بالاسم timestamp"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_dir = BACKUP_ROOT / f"backup_{timestamp}"
    try:
        shutil.copytree(PROJECT_ROOT, dest_dir, ignore=shutil.ignore_patterns('backup'))
        print(f"✅ نسخ احتياطي تم إنشاؤه: {dest_dir}")
        # حذف النسخ القديمة بعد الإنشاء
        retain_backups()
        # إرسال إشعار بالبريد الإلكتروني
        subject = f"نسخة احتياطية جديدة – {timestamp}"
        body = f"تم إنشاء نسخة احتياطية جديدة في المسار:
{dest_dir}\n\nتم الاحتفاظ بآخر {MAX_BACKUPS} نسخ."
        send_email_notification(subject, body)
    except Exception as e:
        print(f"❌ فشل إنشاء النسخة الاحتياطية: {e}")

# ---------- مراقبة التغييرات باستخدام watchdog ----------
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:
    print("⚠️ مكتبة watchdog غير مثبتة. تشغيل: pip install watchdog")
    sys.exit(1)

class ChangeHandler(FileSystemEventHandler):
    def on_any_event(self, event):
        # نتجاهل أحداث داخل مجلد backup نفسه لتجنب حلقات لا نهائية
        if BACKUP_ROOT in Path(event.src_path).parents:
            return
        # طباعة معلومات الحدث (اختياري)
        print(f"🛎️ حدث: {event.event_type} – {event.src_path}")
        # بعد أي تعديل، نفعل النسخة الاحتياطية
        create_timestamped_backup()

def main():
    ensure_backup_dir()
    event_handler = ChangeHandler()
    observer = Observer()
    observer.schedule(event_handler, str(PROJECT_ROOT), recursive=True)
    observer.start()
    print(f"🚀 مراقبة التغييرات في: {PROJECT_ROOT}\n   النسخ الاحتياطية تُحفظ في: {BACKUP_ROOT}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    main()
