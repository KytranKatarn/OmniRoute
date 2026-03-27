"""Tiny CORS proxy — forwards requests with CORS headers added."""
import http.server
import urllib.request
import urllib.parse
import urllib.error
import json

class CORSProxyHandler(http.server.BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if parsed.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self._cors_headers()
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
            return

        target_url = params.get('url', [None])[0]
        if not target_url:
            self.send_response(400)
            self._cors_headers()
            self.end_headers()
            self.wfile.write(b'{"error":"Missing url parameter"}')
            return

        try:
            # Properly encode the URL — spaces and special chars in query string
            parts = urllib.parse.urlsplit(target_url)
            safe_query = urllib.parse.quote(parts.query, safe='=&+%')
            safe_path = urllib.parse.quote(parts.path, safe='/:@')
            safe_url = urllib.parse.urlunsplit((parts.scheme, parts.netloc, safe_path, safe_query, parts.fragment))

            req = urllib.request.Request(safe_url, headers={
                'User-Agent': 'KytranNews/1.0',
                'Accept': 'application/json, application/geo+json, */*'
            })
            resp = urllib.request.urlopen(req, timeout=30)
            body = resp.read()

            self.send_response(200)
            content_type = resp.headers.get('Content-Type', 'application/json')
            self.send_header('Content-Type', content_type)
            self._cors_headers()
            self.end_headers()
            self.wfile.write(body)
        except urllib.error.HTTPError as e:
            # Pass through upstream status and body
            body = e.read() if hasattr(e, 'read') else b''
            self.send_response(e.code)
            self.send_header('Content-Type', e.headers.get('Content-Type', 'application/json'))
            self._cors_headers()
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self.send_response(502)
            self.send_header('Content-Type', 'application/json')
            self._cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def _cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Max-Age', '86400')

    def log_message(self, format, *args):
        pass  # suppress logs

if __name__ == '__main__':
    server = http.server.HTTPServer(('0.0.0.0', 8080), CORSProxyHandler)
    print('CORS proxy running on :8080')
    server.serve_forever()
