// وظيفة تحديث الساعة والترحيب
function updateClock() {
    const now = new Date();
    let hours = now.getHours();
    let minutes = now.getMinutes();
    let ampm = hours >= 12 ? 'مساءً' : 'صباحاً';
    
    // 1. تحديث الترحيب (صباح الخير / مساء الخير)
    const mainG = document.getElementById('main-greeting');
    if (mainG) {
        if (hours >= 5 && hours < 12) {
            mainG.innerHTML = "صباح الخير";
        } else {
            mainG.innerHTML = "مساء الخير";
        }
    }

    // 2. تنسيق الوقت ليظهر بشكل 12 ساعة
    let displayHours = hours % 12 || 12;
    let displayMinutes = minutes < 10 ? '0' + minutes : minutes;
    
    // 3. وضع الوقت في مكانه بالصفحة
    const clockEl = document.getElementById('clock');
    const ampmEl = document.getElementById('ampm');
    const dateEl = document.getElementById('full-date');

    if (clockEl) clockEl.innerHTML = displayHours + ':' + displayMinutes;
    if (ampmEl) ampmEl.innerHTML = ampm;

    // 4. تحديث التاريخ العربي
    if (dateEl) {
        const options = { weekday: 'long', month: 'long', day: 'numeric' };
        dateEl.innerHTML = now.toLocaleDateString('ar-EG', options);
    }

    // تكرار العملية كل ثانية
    setTimeout(updateClock, 1000);
}

// تشغيل الوظيفة فور تحميل الصفحة
window.addEventListener('DOMContentLoaded', updateClock);
const messages = [
    "إذا احتجت مساعدة توجه إلى الدعم الفني 🛠️",
    "لمعرفة الأسعار توجه إلى صفحة الباقات 💎",
    "أهلاً بك في شبكة ماستر نت - إنترنت أسرع وأقوى 🚀"
];

let msgIndex = 0;
const infoSpan = document.getElementById('sliding-info');

// هذه الوظيفة تغير النص داخل الشريط كل 20 ثانية (مع انتهاء لفة الشريط)
if (infoSpan) {
    setInterval(() => {
        msgIndex = (msgIndex + 1) % messages.length;
        infoSpan.innerText = messages[msgIndex];
    }, 20000);
// وظيفة نسخ كود الكارت مع رد فعل بصري
function copyCardCode() {
    const codeInput = document.getElementById('cardCodeDeliver');
    if (!codeInput) return;
    const code = codeInput.value.trim();
    if (!code) {
        alert('الرجاء إدخال كود الكارت أولاً');
        return;
    }
    navigator.clipboard.writeText(code).then(() => {
        showCopyFeedback(document.querySelector('.btn-secondary'));
    }).catch(err => {
        console.error('فشل النسخ:', err);
        alert('تعذّر نسخ النص، يرجى السماح للمتصفح بالوصول إلى الحافظة.');
    });
}

// رد فعل بصري عند النسخ
function showCopyFeedback(el) {
    const original = el.innerHTML;
    el.innerHTML = '<span style="color:#10b981;font-weight:800;">✅ تم النسخ</span>';
    el.classList.add('copied');
    setTimeout(() => {
        el.innerHTML = original;
        el.classList.remove('copied');
    }, 1800);
}
// تحميل مكتبة Google API وتفويض Gmail
function loadGapi() {
    return new Promise((resolve, reject) => {
        if (document.getElementById('gapi-js')) return resolve();
        const script = document.createElement('script');
        script.src = 'https://apis.google.com/js/api.js';
        script.id = 'gapi-js';
        script.onload = () => resolve();
        script.onerror = e => reject(e);
        document.body.appendChild(script);
    });
}

let gapiAuthInstance = null;
let gmailAccessToken = null;

// تهيئة عميل Gmail
async function initGmailClient() {
    await loadGapi();
    await new Promise((res, rej) => {
        window.gapi.load('client:auth2', { callback: res, onerror: rej, timeout: 5000, ontimeout: rej });
    });
    await window.gapi.client.init({
        clientId: '52671070430-jqm8co60ao2uev15s6f4rd892md4uolb.apps.googleusercontent.com',
        scope: 'https://www.googleapis.com/auth/gmail.readonly',
    });
    gapiAuthInstance = window.gapi.auth2.getAuthInstance();
    if (!gapiAuthInstance.isSignedIn.get()) {
        await gapiAuthInstance.signIn();
    }
    const user = gapiAuthInstance.currentUser.get();
    gmailAccessToken = user.getAuthResponse(true).access_token;
    console.log('تم الحصول على توكن Gmail');
    fetchGmailMessages();
}

// جلب رسائل Gmail غير المقروءة
async function fetchGmailMessages() {
    if (!gmailAccessToken) {
        console.warn('لم يتم تفويض Gmail بعد');
        return;
    }
    const query = 'is:unread label:inbox';
    const url = `https://www.googleapis.com/gmail/v1/users/me/messages?q=${encodeURIComponent(query)}&maxResults=5`;
    try {
        const resp = await fetch(url, { headers: { Authorization: `Bearer ${gmailAccessToken}` } });
        const data = await resp.json();
        if (!data.messages) {
            renderGmailMessages([]);
            return;
        }
        const msgs = await Promise.all(data.messages.map(async m => {
            const msgResp = await fetch(`https://www.googleapis.com/gmail/v1/users/me/messages/${m.id}?format=metadata&metadataHeaders=Subject&metadataHeaders=From&metadataHeaders=Date`, {
                headers: { Authorization: `Bearer ${gmailAccessToken}` }
            });
            const msgData = await msgResp.json();
            const hdr = msgData.payload.headers;
            return {
                id: m.id,
                subject: hdr.find(h => h.name === 'Subject')?.value || '(بدون موضوع)',
                from: hdr.find(h => h.name === 'From')?.value || '(غير معروف)',
                date: hdr.find(h => h.name === 'Date')?.value || ''
            };
        }));
        renderGmailMessages(msgs);
    } catch (e) {
        console.error('خطأ في جلب رسائل جيميل:', e);
    }
}

// عرض الرسائل في لوحة الجيميل
function renderGmailMessages(messages) {
    const panel = document.getElementById('gmailPanel');
    if (!panel) return;
    panel.innerHTML = '';
    if (messages.length === 0) {
        panel.innerHTML = '<p style="margin:0;padding:8px;">لا توجد رسائل غير مقروءة</p>';
        return;
    }
    messages.forEach(msg => {
        const item = document.createElement('div');
        item.style.padding = '8px';
        item.style.borderBottom = '1px solid #333';
        item.innerHTML = `<strong>${msg.subject}</strong><br><small>${msg.from}</small>`;
        panel.appendChild(item);
    });
}

// بدء التفويض عند تحميل الصفحة
window.addEventListener('DOMContentLoaded', initGmailClient);