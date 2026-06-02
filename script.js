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
}