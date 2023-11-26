import os.path
import ssl
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        response_content = b"Hello, World!"
        self.wfile.write(response_content)
        self.wfile.flush()


class SetupHttpServer:
    def __init__(self, port=8000, https=False):
        self.port = port
        self.https = https

    def __enter__(self):
        server = HTTPServer(("localhost", self.port), Handler)
        if self.https:
            keyfile = os.path.join(os.path.dirname(__file__), "./key.pem")
            certfile = os.path.join(os.path.dirname(__file__), "./cert.pem")

            server.socket = ssl.wrap_socket(
                server.socket, keyfile=keyfile, certfile=certfile, server_side=True
            )

        ip, port = server.server_address
        print(f"Listening on {str(ip)}:{port}")
        Thread(target=server.serve_forever).start()
        self.server = server
        return server

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.server.shutdown()
