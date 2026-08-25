import http.server
import socketserver

class CORSHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        super().end_headers()
    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

class Server(http.server.ThreadingHTTPServer):
    allow_reuse_address = True

PORT = 9999
with Server(("127.0.0.1", PORT), CORSHandler) as httpd:
    print(f"CORS+PNA zip server on {PORT}", flush=True)
    httpd.serve_forever()
