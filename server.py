import http.server
import socketserver
import json
import os
from pathlib import Path

# إعدادات الخادم
PORT = 8000
DIRECTORY = r"c:/Users/LAPTOP/OneDrive/Desktop/ماستر نت/imad1"

class AutoSaveHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        # توجيه الخادم للعمل من مجلد المشروع
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def do_POST(self):
        # استقبال البيانات من المتصفح وحفظها في data.json تلقائياً
        if self.path == '/save':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            try:
                # تحويل البيانات المرسلة إلى JSON
                data = json.loads(post_data.decode('utf-8'))
                
                # كتابة البيانات داخل ملف data.json
                data_file = os.path.join(DIRECTORY, 'data.json')
                with open(data_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                
                # إرسال رد بنجاح العملية
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"status": "success"}')
                print("✅ تم حفظ التعديلات تلقائياً في data.json")
                
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f'{{"status": "error", "message": "{str(e)}"}}'.encode('utf-8'))
                print(f"❌ خطأ أثناء الحفظ: {e}")
        else:
            self.send_response(404)
            self.end_headers()

def run_server():
    # التأكد من المسار
    if not os.path.exists(DIRECTORY):
        print(f"⚠️ المسار غير موجود: {DIRECTORY}")
        return
        
    # منع رسائل الخطأ عند إعادة تشغيل الخادم
    socketserver.TCPServer.allow_reuse_address = True
    
    with socketserver.TCPServer(("", PORT), AutoSaveHandler) as httpd:
        print("="*50)
        print("🚀 خادم 'ماستر نت' يعمل بنجاح!")
        print(f"👉 اضغط على الرابط لفتح النظام: http://localhost:{PORT}")
        print("="*50)
        print("💡 أي تعديل تقوم به داخل النظام سيتم حفظه تلقائياً في ملف data.json")
        print("لإيقاف الخادم اضغط على Ctrl + C")
        print("="*50)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nتم إيقاف الخادم.")

if __name__ == "__main__":
    run_server()
