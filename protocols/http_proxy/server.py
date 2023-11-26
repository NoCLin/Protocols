import asyncio
import logging
from asyncio import StreamReader, StreamWriter
from contextlib import closing

import async_timeout

from protocols.forward import relay_stream
from protocols.http_proxy.parser import HttpRequest, extract_username_password

logger = logging.getLogger(__name__)


class HttpProxyServerProtocol(asyncio.StreamReaderProtocol):
    def __init__(self, on_accept=None, on_auth=None, on_connect=None):
        self.reader = StreamReader()
        super().__init__(self.reader, self.handler)

        self.on_accept = on_accept
        self.on_auth = on_auth
        self.on_connect = on_connect

    async def handler(self, reader: StreamReader, writer: StreamWriter):
        with closing(writer):
            await self._handler(reader, writer)

    async def _handler(self, reader: StreamReader, writer: StreamWriter) -> None:
        addr = writer.get_extra_info("peername")
        if self.on_accept:
            if not self.on_accept(addr):
                return

        data = await reader.readuntil(b"\r\n\r\n")

        request = HttpRequest(data)
        logger.debug(f"Request {request} from {addr!r}")

        if self.on_auth:
            credentials = request.headers["Proxy-Authorization"]
            username, password = extract_username_password(credentials)
            if not self.on_auth(username, password):
                return

        if self.on_connect:
            if not self.on_connect(request.host, request.port):
                return

        await self.forward(request, reader, writer)

    async def forward(self, request, reader, writer):
        try:
            async with async_timeout.timeout(30):
                if request.method == "CONNECT":
                    await self.forward_https(
                        request,
                        reader,
                        writer,
                    )
                else:
                    await self.forward_http(
                        request,
                        reader,
                        writer,
                    )

        except asyncio.TimeoutError:
            ...

    async def forward_https(
        self,
        request: HttpRequest,
        reader: StreamReader,
        writer: StreamWriter,
    ):
        remote_reader, remote_writer = await asyncio.open_connection(
            request.host, request.port
        )

        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        await relay_stream((reader, writer), (remote_reader, remote_writer))

    async def forward_http(
        self,
        request: HttpRequest,
        reader: StreamReader,
        writer: StreamWriter,
    ):
        remote_reader, remote_writer = await asyncio.open_connection(
            request.host, request.port
        )

        headers = b"\r\n".join(
            [f"{k}: {v}".encode() for k, v in request.headers_to_send.items()]
        )

        data = (
            f"{request.method} {request.path} {request.proto}".encode()
            + b"\r\n"
            + headers
            + b"\r\n\r\n"
        )

        remote_writer.write(data)
        await remote_writer.drain()
        await relay_stream((reader, writer), (remote_reader, remote_writer))


async def main():
    host, port = "127.0.0.1", 8080
    loop = asyncio.get_event_loop()
    server = await loop.create_server(
        lambda: HttpProxyServerProtocol(
            on_accept=lambda u: True, on_connect=lambda h, p: True
        ),
        host,
        port,
    )

    logger.info(f"Serving on {host}:{port}")

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig()
    logger.setLevel(logging.DEBUG)
    asyncio.run(main())
