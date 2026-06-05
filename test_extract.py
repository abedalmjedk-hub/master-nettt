# -*- coding: utf-8 -*-
"""اختبار سريع لدالة استخراج بيانات التحويل"""
import re
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

WALLET_NUMBER = "0599332956"

def normalize_phone(phone_str):
    if not phone_str:
        return ""
    digits = re.sub(r"[^\d]", "", str(phone_str))
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
    text = f"{email_subject} {email_body}"

    amount = None
    amount_patterns = [
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

    sender_phone = None
    sender_name = None
    reference = None

    sender_match = re.search(
        r"من\s+(.+?)\s*\.\s*الرصيد",
        text,
        re.IGNORECASE
    )

    if sender_match:
        sender_raw = sender_match.group(1).strip()
        digits_only = re.sub(r"[^\d]", "", sender_raw)
        if len(digits_only) >= 9:
            sender_phone = normalize_phone(digits_only)
            if sender_phone == normalize_phone(WALLET_NUMBER):
                sender_phone = None
        else:
            sender_name = sender_raw

    if not sender_phone:
        phone_patterns = [
            r"(00970\d{9})",
            r"(\+970\d{9})",
            r"(05\d{8})",
        ]
        for pattern in phone_patterns:
            match = re.search(pattern, text)
            if match:
                normalized = normalize_phone(match.group(1))
                if normalized and normalized != normalize_phone(WALLET_NUMBER) and len(normalized) >= 9:
                    sender_phone = normalized
                    break

    ref_match = re.search(r"المرجع\s*:\s*\(?\s*(\d+)\s*\)?", text)
    if ref_match:
        reference = ref_match.group(1)

    return sender_phone, amount, sender_name, reference

# === الاختبارات ===
print("=" * 60)
print("🧪 اختبار استخراج بيانات التحويل من إشعارات جوال بي")
print("=" * 60)

# اختبار 1: المرسل رقم هاتف
msg1 = "لقد استلمت حركه تحويل اموال بقيمة: ILS 3.00 من 00970599441287 . الرصيد الحالي: ILS 26.01 .المرجع :(2922137009579)"
phone, amt, name, ref = extract_transfer_info(msg1)
print(f"\n📧 اختبار 1 (رقم هاتف):")
print(f"   النص: {msg1[:80]}...")
print(f"   📱 الرقم: {phone}")
print(f"   💰 المبلغ: {amt}")
print(f"   👤 الاسم: {name}")
print(f"   📎 المرجع: {ref}")
assert phone == "0599441287", f"❌ خطأ: الرقم المتوقع 0599441287 لكن جاء {phone}"
assert amt == 3, f"❌ خطأ: المبلغ المتوقع 3 لكن جاء {amt}"
assert name is None, f"❌ خطأ: الاسم المتوقع None لكن جاء {name}"
assert ref == "2922137009579", f"❌ خطأ: المرجع المتوقع 2922137009579 لكن جاء {ref}"
print("   ✅ نجح!")

# اختبار 2: المرسل اسم شخص
msg2 = "لقد استلمت حركه تحويل اموال بقيمة: ILS 1.00 من محمد هشام البحيصي . الرصيد الحالي: ILS 18.01 .المرجع :(2922134844261)"
phone2, amt2, name2, ref2 = extract_transfer_info(msg2)
print(f"\n📧 اختبار 2 (اسم شخص):")
print(f"   النص: {msg2[:80]}...")
print(f"   📱 الرقم: {phone2}")
print(f"   💰 المبلغ: {amt2}")
print(f"   👤 الاسم: {name2}")
print(f"   📎 المرجع: {ref2}")
assert phone2 is None, f"❌ خطأ: الرقم المتوقع None لكن جاء {phone2}"
assert amt2 == 1, f"❌ خطأ: المبلغ المتوقع 1 لكن جاء {amt2}"
assert name2 == "محمد هشام البحيصي", f"❌ خطأ: الاسم المتوقع 'محمد هشام البحيصي' لكن جاء '{name2}'"
assert ref2 == "2922134844261", f"❌ خطأ: المرجع المتوقع 2922134844261 لكن جاء {ref2}"
print("   ✅ نجح!")

print(f"\n{'=' * 60}")
print("✅ جميع الاختبارات نجحت!")
print(f"{'=' * 60}")
