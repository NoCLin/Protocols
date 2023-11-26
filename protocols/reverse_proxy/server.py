import asyncio
import logging
from asyncio import StreamReader, StreamWriter
from contextlib import closing

from protocols.forward import relay_stream

logger = logging.getLogger(__name__)


class ReverseProxyProtocol(asyncio.StreamReaderProtocol):
    def __init__(self, target_host: str, target_port: int, on_accept=None):
        self.reader = StreamReader()
        super().__init__(self.reader, self.handler)

        self.on_accept = on_accept
        self.target_host = target_host
        self.target_port = target_port

    async def handler(self, reader: StreamReader, writer: StreamWriter):
        with closing(writer):
            await self._handler(reader, writer)

    async def _handler(self, reader: StreamReader, writer: StreamWriter) -> None:
        addr = writer.get_extra_info("peername")
        if self.on_accept:
            if not self.on_accept(addr):
                return
        await self.forward(reader, writer)

    async def forward(self, reader, writer):
        remote_reader, remote_writer = await asyncio.open_connection(
            self.target_host, self.target_port
        )

        await relay_stream((reader, writer), (remote_reader, remote_writer))


async def main():
    host, port = "127.0.0.1", 8000
    loop = asyncio.get_event_loop()
    server = await loop.create_server(
        lambda: ReverseProxyProtocol(target_host="1.1.1.1", target_port=80),
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
