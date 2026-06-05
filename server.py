import http.server
import socketserver
import json
import os
from pathlib import Path

# إعدادات الخادم
PORT = 8000
DIRECTORY = r"c:/Users/LAPTOP/OneDrive/Desktop/ماستر نت/imad1"
DELIVERIES_FILE = os.path.join(DIRECTORY, "deliveries.json")

# تأكد من وجود ملف التسليمات
if not os.path.exists(DELIVERIES_FILE):
    with open(DELIVERIES_FILE, "w", encoding="utf-8") as f:
        json.dump({}, f)

class AutoSaveHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def log_message(self, format, *args):
        # إخفاء رسائل GET العادية لتنظيف الشاشة
        if args and "GET" in str(args[0]) and "/check/" in str(args[0]):
            return
        super().log_message(format, *args)

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors()
        self.end_headers()

    def _send_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_GET(self):
        # ─── نقطة فحص تسليم الطلب ───
        if self.path.startswith("/check/"):
            order_id = self.path.replace("/check/", "").strip()
            try:
                with open(DELIVERIES_FILE, "r", encoding="utf-8") as f:
                    deliveries = json.load(f)
                result = deliveries.get(str(order_id))
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self._send_cors()
                self.end_headers()
                if result:
                    self.wfile.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
                else:
                    self.wfile.write(b'{"status":"pending"}')
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b'{"status":"error"}')
            return
        super().do_GET()

    def do_POST(self):
        # ─── حفظ data.js ───
        if self.path == "/save":
            content_length = int(self.headers["Content-Length"])
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode("utf-8"))
                data_file = os.path.join(DIRECTORY, "data.js")
                with open(data_file, "w", encoding="utf-8") as f:
                    js_content = "var MN_SAVED_DATA = " + json.dumps(data, ensure_ascii=False, indent=2) + ";"
                    f.write(js_content)
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self._send_cors()
                self.end_headers()
                self.wfile.write(b'{"status": "success"}')
                print("✅ تم تحديث data.js بنجاح")
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f'{{"status": "error", "message": "{str(e)}"}}'.encode("utf-8"))

        # ─── استلام تسليم الكروت من البوت ───
        elif self.path == "/delivery":
            content_length = int(self.headers["Content-Length"])
            post_data = self.rfile.read(content_length)
            try:
                delivery = json.loads(post_data.decode("utf-8"))
                order_id = str(delivery.get("orderId", ""))
                if order_id:
                    with open(DELIVERIES_FILE, "r", encoding="utf-8") as f:
                        deliveries = json.load(f)
                    deliveries[order_id] = delivery
                    with open(DELIVERIES_FILE, "w", encoding="utf-8") as f:
                        json.dump(deliveries, f, ensure_ascii=False, indent=2)
                    print(f"✅ تم تسليم الكرت لطلب #{order_id}")
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self._send_cors()
                self.end_headers()
                self.wfile.write(b'{"status": "success"}')
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b'{"status": "error"}')

        else:
            self.send_response(404)
            self.end_headers()


def run_server():
    if not os.path.exists(DIRECTORY):
        print(f"⚠️ المسار غير موجود: {DIRECTORY}")
        return

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), AutoSaveHandler) as httpd:
        print("=" * 50)
        print("🚀 خادم ماستر نت يعمل!")
        print(f"👉 http://localhost:{PORT}")
        print("=" * 50)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nتم إيقاف الخادم.")


if __name__ == "__main__":
    run_server()


