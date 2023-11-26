import base64
from urllib.parse import urlparse

hopHeaders = {
    "Connection",
    "Keep-Alive",
    "Proxy-Authenticate",
    "Proxy-Authorization",
    "Te",
    "Trailers",
    "Transfer-Encoding",
    "Upgrade",
}


def parse_headers(lines):
    _MAXLINE = 65536
    _MAXHEADERS = 100
    headers = {}
    for line in lines[1:]:
        if len(line) > _MAXLINE:
            raise Exception("header line too long")
        if b":" in line:
            key, value = line.split(b":", 1)
            headers[key.strip().decode()] = value.strip().decode()

        if len(headers) > _MAXHEADERS:
            raise Exception("got more than %d headers" % _MAXHEADERS)
    return headers


def extract_username_password(credentials):
    authentication_type, encoded_credentials = credentials.strip().split(" ", 2)
    assert authentication_type == "Basic"
    decoded_credentials = base64.b64decode(encoded_credentials).decode("utf-8")
    username, password = decoded_credentials.split(":")
    return username, password


class HttpRequest:
    def __init__(self, raw: bytes):
        lines = raw.splitlines()
        self.first_line = lines[0].decode()

        self.method, self.target, self.proto = self.first_line.split(" ")

        if self.method == "CONNECT":
            host, port = self.target.split(":")
            self.host = host
            self.port = int(port)
            self.path = None
            self.url = None
        else:
            parsed_url = urlparse(self.target)
            self.host = parsed_url.hostname or ""
            self.port = parsed_url.port or 80
            self.path = parsed_url.path
            self.url = parsed_url.geturl()

        assert self.host
        assert self.port

        self.headers = parse_headers(lines)

        self.headers_to_send = {
            k: v
            for k, v in self.headers.items()
            if not (k.startswith("Proxy-") or k in hopHeaders)
        }

    def __str__(self):
        return str(
            dict(
                METHOD=self.method,
                Path=self.path,
                HOST=self.host,
                PORT=self.port,
            )
        )
