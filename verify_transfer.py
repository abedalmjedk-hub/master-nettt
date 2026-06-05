# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║       🔄 ماستر نت - نظام التحقق التلقائي من التحويلات       ║
║       Gmail + JawwalPay + MQTT Auto-Verification            ║
╚══════════════════════════════════════════════════════════════╝

هذا السكريبت يقوم بـ:
1. مراقبة الجيميل لاستلام إشعارات تحويلات جوال بي
2. استخراج رقم المحوّل والمبلغ من الإيميل
3. مقارنتها مع الطلبات الواردة عبر MQTT
4. الموافقة أو الرفض تلقائياً

الإعداد الأول:
1. فعّل Gmail API من Google Cloud Console
2. حمّل credentials.json وضعه بجانب هذا الملف
3. شغّل: pip install -r requirements.txt
4. شغّل: python verify_transfer.py
"""

import os
import sys
import json
import re
import time
import base64
import threading
import logging
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

# ─── إعداد المسارات ───
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_FILE = os.path.join(SCRIPT_DIR, "credentials.json")
TOKEN_FILE = os.path.join(SCRIPT_DIR, "token.json")
LOG_FILE = os.path.join(SCRIPT_DIR, "transfer_log.txt")
CARDS_FILE = os.path.join(SCRIPT_DIR, "cards_pool.json")

# ─── إعداد اللوج ───
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-7s │ %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("MasterNet")

# ─── ألوان الكونسول ───
try:
    from colorama import init, Fore, Style
    init(autoreset=True)
    C_GREEN = Fore.GREEN
    C_RED = Fore.RED
    C_YELLOW = Fore.YELLOW
    C_CYAN = Fore.CYAN
    C_MAGENTA = Fore.MAGENTA
    C_WHITE = Fore.WHITE
    C_RESET = Style.RESET_ALL
    C_BOLD = Style.BRIGHT
except ImportError:
    C_GREEN = C_RED = C_YELLOW = C_CYAN = C_MAGENTA = C_WHITE = C_RESET = C_BOLD = ""

# ═══════════════════════════════════════════════════════════
# الإعدادات الرئيسية - عدّلها حسب حاجتك
# ═══════════════════════════════════════════════════════════

# رقم المحفظة (الي يستقبل التحويلات)
WALLET_NUMBER = "0599332956"

# وسيط MQTT
MQTT_BROKER = "broker.emqx.io"
MQTT_PORT = 1883
MQTT_TOPIC_ORDERS = "masternet/orders"
MQTT_TOPIC_DELIVERY = "masternet/delivery"  # + /{orderId}

# فترة فحص الجيميل (بالثواني)
GMAIL_CHECK_INTERVAL = 15

# الكلمات المفتاحية لتحديد إيميلات جوال بي
JAWWAL_PAY_SENDERS = [
    "jawwalpay",
    "jawwal",
    "paltel",
    "noreply@jawwal",
    "jawwal pay",
    "محفظة جوال",
]

JAWWAL_PAY_SUBJECTS = [
    "تحويل",
    "استلام",
    "وارد",
    "transfer",
    "received",
    "payment",
    "إيداع",
]

# الكلمات المفتاحية داخل نص الرسالة (للتعرف على إشعارات جوال بي)
JAWWAL_PAY_BODY_KEYWORDS = [
    "استلمت حركه تحويل اموال",
    "تحويل اموال بقيمة",
    "الرصيد الحالي",
    "المرجع",
]

# ═══════════════════════════════════════════════════════════
# مخزن البطاقات (cards_pool.json)
# ═══════════════════════════════════════════════════════════

def load_cards_pool():
    """تحميل مخزون البطاقات الجاهزة للتسليم"""
    if os.path.exists(CARDS_FILE):
        try:
            with open(CARDS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # إنشاء ملف افتراضي إذا لم يكن موجوداً
    default_pool = {
        "_تعليمات": "أضف بطاقاتك هنا. كل باقة لها قائمة بطاقات جاهزة. السكريبت يسحب أول بطاقة متاحة عند الموافقة.",
        "1": [
            {"username": "user_1day_001", "password": "pass001"},
            {"username": "user_1day_002", "password": "pass002"}
        ],
        "3": [
            {"username": "user_24h_001", "password": "pass001"},
            {"username": "user_24h_002", "password": "pass002"}
        ],
        "50": [
            {"username": "user_month_001", "password": "pass001"},
            {"username": "user_month_002", "password": "pass002"}
        ]
    }
    save_cards_pool(default_pool)
    return default_pool


def save_cards_pool(pool):
    """حفظ مخزون البطاقات"""
    with open(CARDS_FILE, "w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)


def get_card_from_pool(pkg_id, qty=1):
    """
    سحب بطاقة/بطاقات من المخزون.
    يرجع قائمة بطاقات أو None إذا لا يوجد مخزون كافي.
    """
    pool = load_cards_pool()
    pkg_key = str(pkg_id)

    if pkg_key not in pool or not isinstance(pool[pkg_key], list):
        return None

    available = pool[pkg_key]
    if len(available) < qty:
        return None

    # سحب البطاقات المطلوبة
    cards = available[:qty]
    pool[pkg_key] = available[qty:]
    save_cards_pool(pool)

    return cards


# ═══════════════════════════════════════════════════════════
# Gmail API
# ═══════════════════════════════════════════════════════════

def get_gmail_service():
    """إنشاء اتصال مع Gmail API"""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        print(f"\n{C_RED}❌ المكتبات غير مثبتة! شغّل الأمر التالي:{C_RESET}")
        print(f"{C_YELLOW}   pip install -r requirements.txt{C_RESET}\n")
        sys.exit(1)

    SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
    creds = None

    # تحقق من وجود token محفوظ
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    # إذا لا يوجد token صالح، اطلب تسجيل دخول
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None

        if not creds:
            if not os.path.exists(CREDENTIALS_FILE):
                print(f"\n{C_RED}❌ ملف credentials.json غير موجود!{C_RESET}")
                print(f"{C_YELLOW}   حمّله من Google Cloud Console وضعه في:{C_RESET}")
                print(f"   {C_CYAN}{SCRIPT_DIR}{C_RESET}\n")
                print(f"{C_WHITE}   خطوات الإعداد:{C_RESET}")
                print(f"   1. ادخل على https://console.cloud.google.com/")
                print(f"   2. أنشئ مشروع جديد")
                print(f"   3. فعّل Gmail API")
                print(f"   4. أنشئ OAuth 2.0 Client ID (Desktop App)")
                print(f"   5. حمّل credentials.json")
                print(f"   6. ضعه بجانب هذا الملف وشغّل السكريبت مرة ثانية\n")
                sys.exit(1)

            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        # حفظ التوكن للمرات القادمة
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def normalize_phone(phone_str):
    """تنسيق رقم الهاتف لتسهيل المقارنة"""
    if not phone_str:
        return ""
    # إزالة كل شيء عدا الأرقام
    digits = re.sub(r"[^\d]", "", str(phone_str))
    # التعامل مع الأرقام الفلسطينية بكل الصيغ
    if digits.startswith("00970"):
        digits = "0" + digits[5:]
    elif digits.startswith("970"):
        digits = "0" + digits[3:]
    elif digits.startswith("00972"):
        digits = "0" + digits[5:]
    elif digits.startswith("972"):
        digits = "0" + digits[3:]
    elif not digits.startswith("0") and len(digits) == 9:
        digits = "0" + digits
    return digits


def extract_transfer_info(email_body, email_subject=""):
    """
    استخراج رقم المحوّل والمبلغ واسم المرسل من نص إيميل جوال بي.

    الصيغة الحقيقية لإشعار جوال بي:
    "لقد استلمت حركه تحويل اموال بقيمة: ILS 1.00 من محمد هشام البحيصي . الرصيد الحالي: ILS 18.01 .المرجع :(2922134844261)"
    "لقد استلمت حركه تحويل اموال بقيمة: ILS 3.00 من 00970599441287 . الرصيد الحالي: ILS 26.01 .المرجع :(2922137009579)"

    المرسل قد يكون رقم هاتف أو اسم شخص.
    """
    text = f"{email_subject} {email_body}"

    # ─── استخراج المبلغ ───
    amount = None
    amount_patterns = [
        # الصيغة الحقيقية لجوال بي (الأولوية العليا)
        r"بقيمة[:\s]*ILS\s+(\d+(?:\.\d+)?)",
        r"بقيمة[:\s]*(\d+(?:\.\d+)?)\s*(?:شيكل|شيقل|₪|NIS|ILS)",
        r"ILS\s+(\d+(?:\.\d+)?)",
        r"مبلغ[:\s]+(\d+(?:\.\d+)?)\s*(?:شيكل|شيقل|₪|NIS|ILS)",
        r"(\d+(?:\.\d+)?)\s*(?:شيكل|شيقل|₪|NIS|ILS)",
    ]

    for pattern in amount_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                amount = float(match.group(1))
                if amount == int(amount):
                    amount = int(amount)
                break
            except ValueError:
                continue

    # ─── استخراج المرسل (رقم أو اسم) ───
    sender_phone = None
    sender_name = None
    reference = None

    # الصيغة الحقيقية: "من XXXX ." أو "من XXXX ."
    sender_match = re.search(
        r"من\s+(.+?)\s*\.\s*الرصيد",
        text,
        re.IGNORECASE
    )

    if sender_match:
        sender_raw = sender_match.group(1).strip()

        # تحقق إذا المرسل رقم هاتف
        digits_only = re.sub(r"[^\d]", "", sender_raw)
        if len(digits_only) >= 9:
            sender_phone = normalize_phone(digits_only)
            # تجاهل رقم المحفظة نفسها
            if sender_phone == normalize_phone(WALLET_NUMBER):
                sender_phone = None
        else:
            # المرسل اسم شخص وليس رقم
            sender_name = sender_raw

    # إذا لم نجد بالصيغة الأساسية، ابحث عن أرقام فلسطينية في النص
    if not sender_phone:
        phone_patterns = [
            r"(00970\d{9})",
            r"(\+970\d{9})",
            r"(05\d{8})",
            r"(009725\d{8})",
            r"(\+9725\d{8})",
        ]
        for pattern in phone_patterns:
            match = re.search(pattern, text)
            if match:
                normalized = normalize_phone(match.group(1))
                if normalized and normalized != normalize_phone(WALLET_NUMBER) and len(normalized) >= 9:
                    sender_phone = normalized
                    break

    # ─── استخراج رقم المرجع ───
    ref_match = re.search(r"المرجع\s*:\s*\(?\s*(\d+)\s*\)?", text)
    if ref_match:
        reference = ref_match.group(1)

    return sender_phone, amount, sender_name, reference


def get_email_body(service, msg_id):
    """جلب نص الرسالة كاملاً"""
    try:
        message = service.users().messages().get(
            userId="me", id=msg_id, format="full"
        ).execute()

        subject = ""
        sender = ""
        headers = message.get("payload", {}).get("headers", [])
        for h in headers:
            if h["name"].lower() == "subject":
                subject = h["value"]
            elif h["name"].lower() == "from":
                sender = h["value"]

        # استخراج النص من الأجزاء المختلفة
        body_text = ""
        payload = message.get("payload", {})

        def extract_text(part):
            text = ""
            mime = part.get("mimeType", "")
            if mime in ("text/plain", "text/html"):
                data = part.get("body", {}).get("data", "")
                if data:
                    decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                    # إزالة HTML tags
                    clean = re.sub(r"<[^>]+>", " ", decoded)
                    clean = re.sub(r"\s+", " ", clean).strip()
                    text += clean + " "
            for sub in part.get("parts", []):
                text += extract_text(sub)
            return text

        body_text = extract_text(payload)

        return subject, sender, body_text.strip()

    except Exception as e:
        logger.error(f"خطأ في جلب الرسالة {msg_id}: {e}")
        return "", "", ""


def is_jawwal_pay_email(subject, sender, body=""):
    """تحقق إذا كان الإيميل من جوال بي (عبر المرسل أو الموضوع أو نص الرسالة)"""
    sender_lower = sender.lower()
    subject_lower = subject.lower()
    body_lower = body.lower() if body else ""

    # تحقق من المرسل
    for keyword in JAWWAL_PAY_SENDERS:
        if keyword.lower() in sender_lower:
            return True

    # تحقق من الموضوع
    for keyword in JAWWAL_PAY_SUBJECTS:
        if keyword.lower() in subject_lower:
            return True

    # تحقق من نص الرسالة (الأكثر موثوقية)
    for keyword in JAWWAL_PAY_BODY_KEYWORDS:
        if keyword in body_lower or keyword in subject_lower:
            return True

    return False


# ═══════════════════════════════════════════════════════════
# MQTT Client
# ═══════════════════════════════════════════════════════════

class OrderManager:
    """إدارة الطلبات المعلقة والتحقق من التحويلات"""

    def __init__(self):
        self.pending_orders = {}  # {order_id: order_data}
        self.unmatched_transfers = []  # تحويلات وصلت بدون طلب مقابل
        self.processed_emails = set()  # لمنع معالجة نفس الإيميل مرتين
        self.lock = threading.Lock()
        self.mqtt_client = None

    def setup_mqtt(self):
        """إعداد اتصال MQTT"""
        try:
            import paho.mqtt.client as mqtt_lib
        except ImportError:
            print(f"{C_RED}❌ مكتبة paho-mqtt غير مثبتة!{C_RESET}")
            print(f"{C_YELLOW}   pip install paho-mqtt{C_RESET}")
            sys.exit(1)

        client_id = f"masternet_verifier_{int(time.time())}"
        self.mqtt_client = mqtt_lib.Client(
            client_id=client_id,
            callback_api_version=mqtt_lib.CallbackAPIVersion.VERSION2
        )

        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_message = self._on_message
        self.mqtt_client.on_disconnect = self._on_disconnect

        logger.info(f"{C_CYAN}📡 جاري الاتصال بوسيط MQTT: {MQTT_BROKER}:{MQTT_PORT}...{C_RESET}")

        try:
            self.mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            self.mqtt_client.loop_start()
        except Exception as e:
            logger.error(f"{C_RED}❌ فشل الاتصال بـ MQTT: {e}{C_RESET}")
            sys.exit(1)

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            logger.info(f"{C_GREEN}✅ تم الاتصال بـ MQTT بنجاح!{C_RESET}")
            client.subscribe(MQTT_TOPIC_ORDERS, qos=1)
            logger.info(f"{C_CYAN}📥 تم الاشتراك في قناة الطلبات: {MQTT_TOPIC_ORDERS}{C_RESET}")
        else:
            logger.error(f"{C_RED}❌ فشل الاتصال بـ MQTT. كود: {rc}{C_RESET}")

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):
        if rc != 0:
            logger.warning(f"{C_YELLOW}⚠️ انقطع اتصال MQTT. جاري إعادة الاتصال...{C_RESET}")

    def _on_message(self, client, userdata, msg):
        """معالجة الطلبات الواردة من الموقع"""
        try:
            order = json.loads(msg.payload.decode("utf-8"))
            order_id = str(order.get("id", ""))
            buyer_phone = normalize_phone(order.get("buyerPhone", ""))
            amount = order.get("amt", 0)
            pkg_id = str(order.get("pkgId", ""))
            pkg_name = order.get("pkgName", "")
            qty = order.get("qty", 1)

            if not order_id or not buyer_phone:
                logger.warning(f"{C_YELLOW}⚠️ طلب ناقص البيانات: {order}{C_RESET}")
                return

            logger.info(f"\n{C_BOLD}{C_MAGENTA}{'='*55}{C_RESET}")
            logger.info(f"{C_MAGENTA}📦 طلب جديد #{order_id}{C_RESET}")
            logger.info(f"   📱 رقم المحوّل: {C_CYAN}{buyer_phone}{C_RESET}")
            logger.info(f"   💰 المبلغ: {C_GREEN}{amount} شيكل{C_RESET}")
            logger.info(f"   📋 الباقة: {pkg_name} (x{qty})")
            logger.info(f"{C_MAGENTA}{'='*55}{C_RESET}\n")

            with self.lock:
                self.pending_orders[order_id] = {
                    "id": order_id,
                    "buyerPhone": buyer_phone,
                    "amt": amount,
                    "pkgId": pkg_id,
                    "pkgName": pkg_name,
                    "qty": qty,
                    "received_at": datetime.now().isoformat()
                }

            # فحص التحويلات الي وصلت قبل الطلب
            self._check_unmatched_transfers(order_id)

        except json.JSONDecodeError:
            logger.error(f"{C_RED}❌ رسالة MQTT غير صالحة: {msg.payload}{C_RESET}")
        except Exception as e:
            logger.error(f"{C_RED}❌ خطأ في معالجة الطلب: {e}{C_RESET}")

    def _check_unmatched_transfers(self, new_order_id):
        """تحقق إذا كان فيه تحويل سابق يطابق الطلب الجديد"""
        with self.lock:
            order = self.pending_orders.get(new_order_id)
            if not order:
                return

            matched_idx = None
            for idx, transfer in enumerate(self.unmatched_transfers):
                if self._is_match(order, transfer["phone"], transfer["amount"]):
                    matched_idx = idx
                    break

            if matched_idx is not None:
                transfer = self.unmatched_transfers.pop(matched_idx)
                match_info = transfer.get('phone') or transfer.get('name', '?')
                logger.info(f"{C_GREEN}🔗 تطابق مع تحويل سابق! المرسل: {match_info} المبلغ: {transfer['amount']}{C_RESET}")
                self._approve_order(new_order_id)

    def process_transfer(self, sender_phone, amount, sender_name=None, reference=None):
        """
        معالجة تحويل جديد ومقارنته مع الطلبات.
        يدعم حالتين:
        - المرسل رقم هاتف: مطابقة بالرقم + المبلغ
        - المرسل اسم فقط: مطابقة بالمبلغ فقط (إذا كان فيه طلب واحد بنفس المبلغ)
        """
        with self.lock:
            matched_order_id = None

            if sender_phone:
                # الحالة 1: المرسل رقم هاتف → مطابقة دقيقة بالرقم + المبلغ
                for order_id, order in self.pending_orders.items():
                    if self._is_match(order, sender_phone, amount):
                        matched_order_id = order_id
                        break
            else:
                # الحالة 2: المرسل اسم فقط → مطابقة بالمبلغ فقط
                # نوافق تلقائياً إذا كان فيه طلب واحد فقط بنفس المبلغ
                if amount:
                    matching_orders = [
                        (oid, o) for oid, o in self.pending_orders.items()
                        if float(o["amt"]) == float(amount)
                    ]
                    if len(matching_orders) == 1:
                        matched_order_id = matching_orders[0][0]
                        logger.info(f"{C_YELLOW}👤 المرسل اسم ({sender_name}) وليس رقم. تم المطابقة بالمبلغ فقط ({amount} شيكل){C_RESET}")
                    elif len(matching_orders) > 1:
                        logger.warning(f"{C_YELLOW}⚠️ المرسل اسم ({sender_name}) ويوجد {len(matching_orders)} طلبات بنفس المبلغ. يحتاج موافقة يدوية!{C_RESET}")
                        for oid, o in matching_orders:
                            logger.info(f"   طلب #{oid} │ 📱 {o['buyerPhone']} │ 💰 {o['amt']} شيكل")

            if matched_order_id:
                self._approve_order(matched_order_id)
            else:
                # حفظ التحويل للمقارنة لاحقاً
                transfer_entry = {
                    "phone": sender_phone,
                    "name": sender_name,
                    "amount": amount,
                    "reference": reference,
                    "time": datetime.now().isoformat()
                }
                self.unmatched_transfers.append(transfer_entry)

                identifier = sender_phone or sender_name or "غير معروف"
                logger.info(f"{C_YELLOW}⏳ تحويل بدون طلب مقابل. المرسل: {identifier} المبلغ: {amount}{C_RESET}")
                logger.info(f"   سيتم المطابقة تلقائياً عند وصول طلب مناسب")

                # تنظيف التحويلات القديمة (أكثر من ساعة)
                cutoff = (datetime.now() - timedelta(hours=1)).isoformat()
                self.unmatched_transfers = [
                    t for t in self.unmatched_transfers if t["time"] > cutoff
                ]

    def _is_match(self, order, sender_phone, amount):
        """تحقق من تطابق التحويل مع الطلب (بالرقم + المبلغ)"""
        if not sender_phone:
            return False
        phone_match = normalize_phone(order["buyerPhone"]) == normalize_phone(sender_phone)
        amount_match = float(order["amt"]) == float(amount) if amount else True
        return phone_match and amount_match

    def _approve_order(self, order_id):
        """الموافقة على الطلب (تم التحقق من التحويل)"""
        order = self.pending_orders.get(order_id)
        if not order:
            return

        # إرسال الموافقة عبر MQTT
        delivery_topic = f"{MQTT_TOPIC_DELIVERY}/{order_id}"
        response = {
            "status": "approved",
            "orderId": order_id,
            "message": "تم التحقق من التحويل بنجاح ✅"
        }

        self.mqtt_client.publish(delivery_topic, json.dumps(response), qos=1, retain=True)

        # حذف الطلب من القائمة المعلقة
        del self.pending_orders[order_id]

        logger.info(f"\n{C_BOLD}{C_GREEN}{'='*55}{C_RESET}")
        logger.info(f"{C_GREEN}✅ تمت الموافقة على الطلب #{order_id}{C_RESET}")
        logger.info(f"   📱 رقم العميل: {order['buyerPhone']}")
        logger.info(f"   💰 المبلغ: {order['amt']} شيكل")
        logger.info(f"   📋 الباقة: {order.get('pkgName', '?')}")
        logger.info(f"{C_GREEN}{'='*55}{C_RESET}\n")

    def reject_order(self, order_id, reason="لم يتم التحقق من التحويل"):
        """رفض الطلب"""
        if order_id not in self.pending_orders:
            return

        delivery_topic = f"{MQTT_TOPIC_DELIVERY}/{order_id}"
        response = {
            "status": "rejected",
            "reason": reason,
            "orderId": order_id
        }

        self.mqtt_client.publish(delivery_topic, json.dumps(response), qos=1, retain=True)

        order = self.pending_orders.pop(order_id, {})

        logger.info(f"\n{C_BOLD}{C_RED}{'='*55}{C_RESET}")
        logger.info(f"{C_RED}❌ تم رفض الطلب #{order_id}{C_RESET}")
        logger.info(f"   📱 رقم العميل: {order.get('buyerPhone', '?')}")
        logger.info(f"   📝 السبب: {reason}")
        logger.info(f"{C_RED}{'='*55}{C_RESET}\n")


# ═══════════════════════════════════════════════════════════
# المراقب الرئيسي
# ═══════════════════════════════════════════════════════════

def gmail_monitor(service, manager):
    """مراقبة الجيميل باستمرار للإيميلات الجديدة"""
    logger.info(f"{C_CYAN}📧 بدء مراقبة الجيميل... (كل {GMAIL_CHECK_INTERVAL} ثانية){C_RESET}")

    # بدء المراقبة من الآن فقط (تجاهل الإيميلات القديمة)
    last_check_time = int(time.time())

    while True:
        try:
            # البحث عن إيميلات جديدة بعد آخر فحص
            query = f"after:{last_check_time} is:unread"
            results = service.users().messages().list(
                userId="me", q=query, maxResults=10
            ).execute()

            messages = results.get("messages", [])

            if messages:
                logger.info(f"{C_WHITE}🔍 فحص {len(messages)} رسالة جديدة...{C_RESET}")

            for msg_info in messages:
                msg_id = msg_info["id"]

                # تجاهل الرسائل المعالجة مسبقاً
                if msg_id in manager.processed_emails:
                    continue

                manager.processed_emails.add(msg_id)

                # جلب تفاصيل الرسالة
                subject, sender, body = get_email_body(service, msg_id)

                if not subject and not body:
                    continue

                # تحقق إذا كانت من جوال بي (فحص المرسل + الموضوع + النص)
                if not is_jawwal_pay_email(subject, sender, body):
                    continue

                logger.info(f"\n{C_BOLD}{C_CYAN}{'─'*55}{C_RESET}")
                logger.info(f"{C_CYAN}📧 إيميل جوال بي جديد!{C_RESET}")
                logger.info(f"   📨 من: {sender}")
                logger.info(f"   📋 الموضوع: {subject}")

                # استخراج بيانات التحويل
                sender_phone, amount, sender_name, reference = extract_transfer_info(body, subject)

                if sender_phone:
                    logger.info(f"   📱 رقم المحوّل: {C_GREEN}{sender_phone}{C_RESET}")
                elif sender_name:
                    logger.info(f"   👤 اسم المحوّل: {C_YELLOW}{sender_name}{C_RESET} (بدون رقم)")

                logger.info(f"   💰 المبلغ: {C_GREEN}{amount} ILS{C_RESET}" if amount else f"   💰 المبلغ: {C_YELLOW}غير محدد{C_RESET}")

                if reference:
                    logger.info(f"   📎 المرجع: {reference}")

                logger.info(f"{C_CYAN}{'─'*55}{C_RESET}")

                if sender_phone or sender_name:
                    # معالجة التحويل
                    manager.process_transfer(sender_phone, amount, sender_name, reference)
                else:
                    logger.warning(f"   {C_YELLOW}⚠️ تعذر استخراج بيانات المحوّل من الإيميل{C_RESET}")
                    logger.info(f"   نص الرسالة (أول 200 حرف): {body[:200]}")

            # تحديث وقت آخر فحص
            last_check_time = int(time.time())

            # تنظيف قائمة الإيميلات المعالجة (أبقي آخر 500)
            if len(manager.processed_emails) > 500:
                manager.processed_emails = set(list(manager.processed_emails)[-200:])

        except Exception as e:
            logger.error(f"{C_RED}❌ خطأ في مراقبة الجيميل: {e}{C_RESET}")

        time.sleep(GMAIL_CHECK_INTERVAL)


def admin_console(manager):
    """واجهة إدارة نصية للتحكم يدوياً"""
    time.sleep(3)  # انتظار تشغيل النظام

    while True:
        try:
            print(f"\n{C_BOLD}{C_WHITE}╔══════════════════════════════════════════╗{C_RESET}")
            print(f"{C_WHITE}║  أوامر الإدارة:                          ║{C_RESET}")
            print(f"{C_WHITE}║  [1] عرض الطلبات المعلقة                 ║{C_RESET}")
            print(f"{C_WHITE}║  [2] موافقة يدوية على طلب                ║{C_RESET}")
            print(f"{C_WHITE}║  [3] رفض طلب يدوياً                      ║{C_RESET}")
            print(f"{C_WHITE}║  [4] عرض التحويلات بدون طلب              ║{C_RESET}")
            print(f"{C_WHITE}║  [5] عرض مخزون البطاقات                  ║{C_RESET}")
            print(f"{C_WHITE}║  [q] خروج                                ║{C_RESET}")
            print(f"{C_WHITE}╚══════════════════════════════════════════╝{C_RESET}")

            cmd = input(f"\n{C_CYAN}>> اختر أمر: {C_RESET}").strip()

            if cmd == "1":
                with manager.lock:
                    if not manager.pending_orders:
                        print(f"{C_GREEN}   ✅ لا توجد طلبات معلقة{C_RESET}")
                    else:
                        for oid, order in manager.pending_orders.items():
                            print(f"   #{oid} │ 📱 {order['buyerPhone']} │ 💰 {order['amt']} شيكل │ 📋 {order.get('pkgName','?')}")

            elif cmd == "2":
                oid = input(f"   أدخل رقم الطلب: #").strip()
                if oid in manager.pending_orders:
                    manager._approve_order(oid)
                else:
                    print(f"{C_RED}   ❌ طلب غير موجود{C_RESET}")

            elif cmd == "3":
                oid = input(f"   أدخل رقم الطلب: #").strip()
                reason = input(f"   سبب الرفض: ").strip() or "تم الرفض من قبل الإدارة"
                manager.reject_order(oid, reason)

            elif cmd == "4":
                with manager.lock:
                    if not manager.unmatched_transfers:
                        print(f"{C_GREEN}   ✅ لا توجد تحويلات بدون طلب{C_RESET}")
                    else:
                        for t in manager.unmatched_transfers:
                            identifier = t.get('phone') or t.get('name', '?')
                            ref = t.get('reference', '')
                            ref_str = f" │ 📎 {ref}" if ref else ""
                            print(f"   {identifier} │ 💰 {t['amount']} │ ⏰ {t['time']}{ref_str}")

            elif cmd == "5":
                pool = load_cards_pool()
                for pkg, cards in pool.items():
                    if pkg.startswith("_"):
                        continue
                    if isinstance(cards, list):
                        print(f"   باقة {pkg}: {C_GREEN}{len(cards)} بطاقة متاحة{C_RESET}")

            elif cmd.lower() == "q":
                print(f"{C_YELLOW}   👋 جاري الإيقاف...{C_RESET}")
                os._exit(0)

        except (EOFError, KeyboardInterrupt):
            pass
        except Exception as e:
            logger.error(f"خطأ في واجهة الإدارة: {e}")


# ═══════════════════════════════════════════════════════════
# التشغيل الرئيسي
# ═══════════════════════════════════════════════════════════

def main():
    print(f"""
{C_BOLD}{C_CYAN}╔══════════════════════════════════════════════════════════╗
║                                                          ║
║   🔄  ماستر نت - نظام التحقق التلقائي من التحويلات       ║
║   Gmail + JawwalPay + MQTT Auto-Verification             ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝{C_RESET}
    """)

    # 1. الاتصال بـ Gmail
    logger.info(f"{C_CYAN}📧 جاري الاتصال بـ Gmail API...{C_RESET}")
    gmail_service = get_gmail_service()
    logger.info(f"{C_GREEN}✅ تم الاتصال بـ Gmail بنجاح!{C_RESET}")

    # 2. إعداد مدير الطلبات وMQTT
    manager = OrderManager()
    manager.setup_mqtt()

    # 3. تحميل/إنشاء مخزون البطاقات
    pool = load_cards_pool()
    total_cards = sum(len(v) for k, v in pool.items() if isinstance(v, list))
    logger.info(f"{C_GREEN}🎫 مخزون البطاقات: {total_cards} بطاقة جاهزة{C_RESET}")

    if total_cards == 0:
        logger.warning(f"{C_YELLOW}⚠️ لا توجد بطاقات! أضف بطاقات في: {CARDS_FILE}{C_RESET}")

    # 4. تشغيل مراقب الجيميل في خيط منفصل
    gmail_thread = threading.Thread(target=gmail_monitor, args=(gmail_service, manager), daemon=True)
    gmail_thread.start()

    # 5. تشغيل واجهة الإدارة في الخيط الرئيسي
    logger.info(f"\n{C_GREEN}{'='*55}{C_RESET}")
    logger.info(f"{C_GREEN}🚀 النظام يعمل الآن! يراقب الجيميل و MQTT...{C_RESET}")
    logger.info(f"{C_GREEN}{'='*55}{C_RESET}")

    admin_console(manager)


if __name__ == "__main__":
    main()
