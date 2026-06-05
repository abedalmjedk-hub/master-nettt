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

# إعدادات حساب الجيميل (استخدم كلمة مرور التطبيق - App Password)
IMAP_EMAIL = "abedalmjedk@gmail.com"
IMAP_APP_PASSWORD = "emjb eeqn zldk deoh"

# وسيط MQTT
MQTT_BROKER = "broker.emqx.io"
MQTT_PORT = 1883
MQTT_TOPIC_ORDERS = "masternet/orders"
MQTT_TOPIC_DELIVERY = "masternet/delivery"  # + /{orderId}

# فترة فحص الجيميل (بالثواني)
GMAIL_CHECK_INTERVAL = 15

# الكلمات المفتاحية لتحديد إيميلات جوال بي
JAWWAL_PAY_SENDERS = [
    "noreply@jawwalpay.ps",
    "jawwalpay.ps",
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
# إدارة مخزن البطاقات من data.js
# ═══════════════════════════════════════════════════════════
import random
import string

def load_data_js():
    """تحميل البيانات من data.js"""
    data_file = os.path.join(SCRIPT_DIR, "data.js")
    if not os.path.exists(data_file):
        return None
    try:
        with open(data_file, "r", encoding="utf-8") as f:
            content = f.read()
        start_idx = content.find('{')
        end_idx = content.rfind('}')
        if start_idx != -1 and end_idx != -1:
            json_str = content[start_idx:end_idx+1]
            return json.loads(json_str)
    except Exception as e:
        logger.error(f"خطأ في قراءة data.js: {e}")
    return None

def save_data_js(data):
    """حفظ البيانات إلى data.js"""
    data_file = os.path.join(SCRIPT_DIR, "data.js")
    try:
        with open(data_file, "w", encoding="utf-8") as f:
            f.write("var MN_SAVED_DATA = " + json.dumps(data, ensure_ascii=False, indent=2) + ";")
    except Exception as e:
        logger.error(f"خطأ في حفظ data.js: {e}")

def get_cards_from_data_js(pkg_id, qty=1):
    """
    سحب بطاقات من data.js.
    يرجع (قائمة البطاقات، البيانات المحدثة)
    إذا لم تتوفر بطاقات، يتم توليدها عشوائياً.
    """
    data = load_data_js()
    if not data:
        # إذا لم يكن هناك ملف data.js، قم بإنشاء هيكل افتراضي
        data = {
            "version": "1.0",
            "savedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cardInventory": {"1": [], "3": [], "50": []},
            "orderLogs": [],
            "usedCards": [],
            "totalRevenue": 0,
            "pendingOrders": [],
            "approvedOrders": {},
            "rejectedOrders": {}
        }

    pkg_key = str(pkg_id)
    if "cardInventory" not in data:
        data["cardInventory"] = {"1": [], "3": [], "50": []}
    if pkg_key not in data["cardInventory"]:
        data["cardInventory"][pkg_key] = []

    available = data["cardInventory"][pkg_key]
    cards = []
    
    for _ in range(qty):
        if len(available) > 0:
            card = available.pop(0)
            was_in_inventory = True
        else:
            # توليد كارت عشوائي
            rand_user = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6)) + str(random.randint(100, 999))
            card = {"username": rand_user, "password": ""}
            was_in_inventory = False
            
        if isinstance(card, str):
            card = {"username": card, "password": ""}
            
        card["wasInInventory"] = was_in_inventory
        cards.append(card)
        
    data["cardInventory"][pkg_key] = available
    return cards, data


# ═══════════════════════════════════════════════════════════
# IMAP Gmail Reader
# ═══════════════════════════════════════════════════════════
import imaplib
import email
from email.header import decode_header

def connect_imap():
    """إنشاء اتصال مع الجيميل عبر IMAP"""
    if IMAP_EMAIL == "ضع_ايميلك_هنا@gmail.com" or IMAP_APP_PASSWORD == "ضع_كلمة_المرور_هنا":
        print(f"\n{C_RED}❌ يجب وضع الإيميل وكلمة مرور التطبيق (16 حرف) في السطر 74 في ملف verify_transfer.py!{C_RESET}")
        sys.exit(1)
        
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(IMAP_EMAIL, IMAP_APP_PASSWORD)
        return mail
    except Exception as e:
        print(f"\n{C_RED}❌ فشل الاتصال بالإيميل. تأكد من صحة الإيميل وكلمة مرور التطبيق: {e}{C_RESET}")
        sys.exit(1)


def normalize_phone(phone_str):
    """تنسيق رقم الهاتف لتسهيل المقارنة - يدعم الصيغ الدولية والمحلية"""
    if not phone_str:
        return ""
    # إزالة المسافات والشرطات والأقواس
    phone = re.sub(r"[\s\-\(\)\.]+", "", str(phone_str))
    # إزالة مفتاح الدولة الفلسطينية بأي صيغة
    # 00970 → 0
    if phone.startswith("00970"):
        phone = "0" + phone[5:]
    # +970 → 0
    elif phone.startswith("+970"):
        phone = "0" + phone[4:]
    # 970 (بدون صفر أو +) → 0
    elif phone.startswith("970") and len(phone) > 9:
        phone = "0" + phone[3:]
    return phone



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


def get_email_body(msg):
    """استخراج الموضوع والمرسل والنص من رسالة IMAP"""
    subject = ""
    if msg["Subject"]:
        subject_bytes, encoding = decode_header(msg["Subject"])[0]
        if isinstance(subject_bytes, bytes):
            subject = subject_bytes.decode(encoding or "utf-8", errors="ignore")
        else:
            subject = str(subject_bytes)

    sender = ""
    if msg.get("From"):
        sender_bytes, encoding = decode_header(msg.get("From"))[0]
        if isinstance(sender_bytes, bytes):
            sender = sender_bytes.decode(encoding or "utf-8", errors="ignore")
        else:
            sender = str(sender_bytes)

    body_text = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))
            if content_type in ("text/plain", "text/html") and "attachment" not in content_disposition:
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        text = payload.decode(charset, errors="ignore")
                        clean = re.sub(r"<[^>]+>", " ", text)
                        clean = re.sub(r"\s+", " ", clean).strip()
                        body_text += clean + " "
                except:
                    pass
    else:
        content_type = msg.get_content_type()
        if content_type in ("text/plain", "text/html"):
            try:
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or "utf-8"
                    text = payload.decode(charset, errors="ignore")
                    clean = re.sub(r"<[^>]+>", " ", text)
                    clean = re.sub(r"\s+", " ", clean).strip()
                    body_text = clean
            except:
                pass
    
    return subject, sender, body_text.strip()


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
        """الموافقة على الطلب (تم التحقق من التحويل) وسحب الكروت وإرسالها"""
        order = self.pending_orders.get(order_id)
        if not order:
            return

        pkg_id = order.get("pkgId", "1")
        qty = int(order.get("qty", 1))
        amt = float(order.get("amt", 0))
        pkg_name = order.get("pkgName", f"باقة {pkg_id}")
        buyer_phone = order.get("buyerPhone", "غير معروف")

        # سحب الكروت من data.js وتحديث الملف
        pulled_cards, full_data = get_cards_from_data_js(pkg_id, qty)
        
        # إرسال الموافقة عبر MQTT وتتضمن الكروت
        delivery_topic = f"{MQTT_TOPIC_DELIVERY}/{order_id}"
        
        # تجهيز الكروت للإرسال للعميل
        client_cards = [{"username": c["username"], "password": c["password"]} for c in pulled_cards]
        
        response = {
            "status": "approved",
            "orderId": order_id,
            "message": "تم التحقق من التحويل بنجاح ✅",
            "cards": client_cards
        }

        self.mqtt_client.publish(delivery_topic, json.dumps(response), qos=1, retain=True)

        # ─── إرسال للسيرفر المحلي أيضاً (الأكثر موثوقية) ───
        try:
            import urllib.request
            req = urllib.request.Request(
                "http://localhost:8000/delivery",
                data=json.dumps(response).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            urllib.request.urlopen(req, timeout=2)
            logger.info(f"{C_GREEN}✅ تم إرسال الكرت للسيرفر المحلي بنجاح{C_RESET}")
        except Exception as e:
            logger.warning(f"{C_YELLOW}⚠️ السيرفر المحلي غير متاح (شغّل server.py): {e}{C_RESET}")

        # حذف الطلب من القائمة المعلقة في الذاكرة
        del self.pending_orders[order_id]
        
        # ─── تحديث إحصائيات data.js ───
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # إضافة للأرباح
        full_data["totalRevenue"] = float(full_data.get("totalRevenue", 0)) + amt
        
        # إضافة لسجل الطلبات
        all_cards_text = " | ".join([f"{c['username']} (باس: {c['password']})" if c['password'] else c['username'] for c in pulled_cards])
        full_data["orderLogs"].insert(0, {
            "id": order_id,
            "package": pkg_name,
            "qty": qty,
            "amount": amt,
            "cardCode": all_cards_text,
            "timestamp": timestamp
        })
        
        # إضافة لقائمة الكروت المستخدمة
        for c in pulled_cards:
            full_data["usedCards"].insert(0, {
                "username": c["username"],
                "password": c["password"],
                "pkgId": pkg_id,
                "pkgName": pkg_name,
                "orderId": order_id,
                "buyerPhone": buyer_phone,
                "usedAt": timestamp,
                "wasInInventory": c["wasInInventory"]
            })
            
        # تحديث قائمة الطلبات الموافق عليها (للمزامنة مع اللوحة)
        if "approvedOrders" not in full_data: full_data["approvedOrders"] = {}
        full_data["approvedOrders"][order_id] = client_cards
        
        # إزالة الطلب من قائمة pendingOrders في الملف إذا كان موجوداً
        if "pendingOrders" in full_data:
            for pending in full_data["pendingOrders"]:
                if pending.get("id") == order_id:
                    pending["status"] = "approved"
        
        full_data["savedAt"] = timestamp
        save_data_js(full_data)

        logger.info(f"\n{C_BOLD}{C_GREEN}{'='*55}{C_RESET}")
        logger.info(f"{C_GREEN}✅ تمت الموافقة على الطلب #{order_id} وتم إرسال الكروت!{C_RESET}")
        logger.info(f"   📱 رقم العميل: {buyer_phone}")
        logger.info(f"   💰 المبلغ: {amt} شيكل")
        logger.info(f"   📋 الباقة: {pkg_name}")
        for idx, c in enumerate(pulled_cards):
            logger.info(f"   💳 كارت {idx+1}: {c['username']} {'(تم سحبه من المخزون)' if c['wasInInventory'] else '(توليد عشوائي)'}")
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
        
        # تحديث حالة الطلب في data.js
        full_data = load_data_js()
        if full_data:
            if "rejectedOrders" not in full_data: full_data["rejectedOrders"] = {}
            full_data["rejectedOrders"][order_id] = {"reason": reason}
            
            if "pendingOrders" in full_data:
                full_data["pendingOrders"] = [o for o in full_data["pendingOrders"] if o.get("id") != order_id]
            
            full_data["savedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_data_js(full_data)

        logger.info(f"\n{C_BOLD}{C_RED}{'='*55}{C_RESET}")
        logger.info(f"{C_RED}❌ تم رفض الطلب #{order_id}{C_RESET}")
        logger.info(f"   📱 رقم العميل: {order.get('buyerPhone', '?')}")
        logger.info(f"   📝 السبب: {reason}")
        logger.info(f"{C_RED}{'='*55}{C_RESET}\n")


# ═══════════════════════════════════════════════════════════
# المراقب الرئيسي
# ═══════════════════════════════════════════════════════════

def gmail_monitor(manager):
    """مراقبة الجيميل عبر IMAP للإيميلات الجديدة"""
    logger.info(f"{C_CYAN}📧 بدء مراقبة الجيميل عبر IMAP... (كل {GMAIL_CHECK_INTERVAL} ثانية){C_RESET}")

    mail = connect_imap()
    mail.select("inbox")

    # تسجيل آخر ID رسالة عند البدء لتجاهل الرسائل القديمة
    status0, all_msgs = mail.search(None, 'ALL')
    if status0 == "OK" and all_msgs[0]:
        all_ids = all_msgs[0].split()
        # تسجيل كل الرسائل الموجودة الآن كـ "قديمة"
        for mid in all_ids:
            manager.processed_emails.add(mid)
        logger.info(f"{C_CYAN}📧 تم تسجيل {len(all_ids)} رسالة قديمة - البوت سيراقب الرسائل الجديدة فقط{C_RESET}")

    while True:
        try:
            # إعادة الاتصال إذا انقطع
            try:
                mail.status("inbox", "(MESSAGES)")
            except:
                mail = connect_imap()
                mail.select("inbox")

            status, messages = mail.search(None, 'UNSEEN')
            if status == "OK" and messages[0]:
                msg_ids = messages[0].split()
                
                # طباعة رسالة فحص إذا كان هناك رسائل جديدة لم تعالج
                new_count = sum(1 for mid in msg_ids if mid not in manager.processed_emails)
                if new_count > 0:
                    logger.info(f"{C_WHITE}🔍 وصلت {new_count} رسالة جديدة!{C_RESET}")

                for msg_id in msg_ids:
                    if msg_id in manager.processed_emails:
                        continue

                    manager.processed_emails.add(msg_id)

                    res, msg_data = mail.fetch(msg_id, '(RFC822)')
                    if res == "OK":
                        raw_email = msg_data[0][1]
                        msg = email.message_from_bytes(raw_email)

                        subject, sender, body = get_email_body(msg)

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

            # تنظيف قائمة الإيميلات المعالجة (أبقي آخر 500)
            if len(manager.processed_emails) > 500:
                manager.processed_emails = set(list(manager.processed_emails)[-200:])

        except Exception as e:
            logger.error(f"{C_RED}❌ خطأ في مراقبة الجيميل: {e}{C_RESET}")
            try:
                mail = connect_imap()
                mail.select("inbox")
            except:
                pass

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

    # 1. لم نعد بحاجة للاتصال هنا، الاتصال يتم داخل المراقبة
    logger.info(f"{C_CYAN}📧 النظام يعمل الآن عبر IMAP مباشرة...{C_RESET}")

    # 2. إعداد مدير الطلبات وMQTT
    manager = OrderManager()
    manager.setup_mqtt()

    # 3. تحميل/إنشاء مخزون البطاقات من data.js (تأكيد وجود الملف)
    data = load_data_js()
    total_cards = 0
    if not data:
        save_data_js({
            "version": "1.0",
            "savedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cardInventory": {"1": [], "3": [], "50": []},
            "orderLogs": [],
            "usedCards": [],
            "totalRevenue": 0
        })
        logger.info(f"{C_GREEN}✅ تم إنشاء ملف data.js جديد لمخزون البطاقات{C_RESET}")
    else:
        inv = data.get("cardInventory", {})
        total_cards = sum(len(v) for v in inv.values() if isinstance(v, list))
        logger.info(f"{C_GREEN}✅ تم تحميل مخزون البطاقات (الإجمالي: {total_cards} بطاقة){C_RESET}")
    
    logger.info(f"{C_GREEN}🎫 مخزون البطاقات: {total_cards} بطاقة جاهزة{C_RESET}")

    if total_cards == 0:
        logger.warning(f"{C_YELLOW}⚠️ لا توجد بطاقات! أضف بطاقات في لوحة التحكم{C_RESET}")

    # 4. تشغيل مراقب الجيميل في خيط منفصل
    gmail_thread = threading.Thread(target=gmail_monitor, args=(manager,), daemon=True)
    gmail_thread.start()

    # 5. تشغيل واجهة الإدارة في الخيط الرئيسي
    logger.info(f"\n{C_GREEN}{'='*55}{C_RESET}")
    logger.info(f"{C_GREEN}🚀 النظام يعمل الآن! يراقب الجيميل و MQTT...{C_RESET}")
    logger.info(f"{C_GREEN}{'='*55}{C_RESET}")

    admin_console(manager)


if __name__ == "__main__":
    main()
