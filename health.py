#!/usr/bin/env python3
# minimal http server so render sees a healthy web service
# and uptimerobot has a url to ping.
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ.get("PORT", "8080"))

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"death\n")
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()
    def log_message(self, *a):
        pass

if __name__ == "__main__":
    HTTPServer(("0.0.0.0", PORT), H).serve_forever()
