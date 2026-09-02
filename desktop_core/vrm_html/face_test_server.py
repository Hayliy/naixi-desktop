import http.server, socketserver, os, sys

ROOT = r"D:\naixi_desktop\desktop_core\vrm_html"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9922

MIME = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.mjs': 'application/javascript; charset=utf-8',
    '.wasm': 'application/wasm',
    '.task': 'application/octet-stream',
    '.json': 'application/json; charset=utf-8',
    '.jpg': 'image/jpeg',
    '.png': 'image/png',
}

class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)
    def do_POST(self):
        if self.path == '/__faceresult':
            n = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(n).decode('utf-8', 'replace')
            with open(os.path.join(ROOT, 'face_result.json'), 'w', encoding='utf-8') as f:
                f.write(body)
            self.send_response(200); self.end_headers(); self.wfile.write(b'ok')
        else:
            self.send_response(404); self.end_headers()
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()
    def guess_type(self, path):
        return MIME.get(os.path.splitext(path)[1].lower(), 'application/octet-stream')
    def log_message(self, fmt, *a):
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % a))
        sys.stderr.flush()

socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("127.0.0.1", PORT), H) as httpd:
    print(f"serving {ROOT} on {PORT}", flush=True)
    httpd.serve_forever()
