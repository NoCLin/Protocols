import asyncio
import struct
from asyncio import StreamReader, StreamWriter, BaseTransport
from contextlib import closing
from typing import Optional, Coroutine, Any, Callable

from protocols.forward import relay_stream
from protocols.socks5_server.consts import (
    SOCKS5_VERSION,
    AuthenticationMethod,
    ResponseCode,
    AUTH_FAILED,
    AUTH_SUCCESS,
    AUTH_SUB_VERSION,
    Command,
    AddressType,
)
from protocols.socks5_server.udp import UDPForwardingServer
from protocols.socks5_server.utils import (
    unpack_data,
    unpack_address_port,
    generate_response,
)


class Socks5ProxyServerProtocol(asyncio.StreamReaderProtocol):
    def __init__(
        self,
        on_accept: Optional[Callable[[str, int], bool]] = None,
        on_auth=Optional[Callable[[str, str], bool]],
        on_connect=Optional[Callable[[str, int], bool]],
    ):
        self.reader = StreamReader()
        super().__init__(self.reader, self.handler)

        self.on_accept = on_accept
        self.on_auth = on_auth
        self.on_connect = on_connect

        self.allow_method = AuthenticationMethod.NO_AUTHENTICATION_REQUIRED
        assert self.allow_method in [
            AuthenticationMethod.NO_AUTHENTICATION_REQUIRED,
            AuthenticationMethod.USERNAME_PASSWORD,
        ]
        self.udp_server_task: Optional[
            Coroutine[Any, Any, tuple[BaseTransport, UDPForwardingServer]]
        ] = None
        self.udp_server: Optional[UDPForwardingServer] = None

    async def handler(self, reader: StreamReader, writer: StreamWriter):
        with closing(writer):
            await self._handler(reader, writer)

    def connection_lost(self, exc: Optional[Exception]) -> None:
        super().connection_lost(exc)

        if self.udp_server_task:
            # A UDP association terminates when the TCP connection that the UDP
            # ASSOCIATE request arrived on terminates.
            self.udp_server_task.close()
        if self.udp_server:
            self.udp_server.close()

    async def _handler(self, reader: StreamReader, writer: StreamWriter) -> None:
        # https://datatracker.ietf.org/doc/html/rfc1928
        addr = writer.get_extra_info("peername")
        if self.on_accept:
            if not self.on_accept(addr[0], addr[1]):
                return

        await self.handler_negotiation(reader, writer)
        # Read the client's request for a connection

        # +----+-----+-------+------+----------+----------+
        # |VER | CMD |  RSV  | ATYP | DST.ADDR | DST.PORT |
        # +----+-----+-------+------+----------+----------+
        # | 1  |  1  | X'00' |  1   | Variable |    2     |
        # +----+-----+-------+------+----------+----------+

        data = await reader.readexactly(3)
        version, cmd, _ = unpack_data(data, "!BBB")
        assert version == SOCKS5_VERSION

        address_type, dst_addr, dst_port = await unpack_address_port(reader)

        assert cmd in [Command.CONNECT.value, Command.UDP_ASSOCIATE.value]

        if cmd == Command.UDP_ASSOCIATE.value:
            await self.handler_udp_associate(
                reader=reader,
                writer=writer,
                dst_addr=dst_addr,
                dst_port=dst_port,
            )

        elif cmd == Command.CONNECT.value:
            await self.handler_connect(reader, writer, dst_addr, dst_port)

    async def handler_negotiation(self, reader, writer):
        # +----+----------+----------+
        # |VER | NMETHODS | METHODS  |
        # +----+----------+----------+
        # | 1  |    1     | 1 to 255 |
        # +----+----------+----------+

        data = await reader.readexactly(2)
        version, nmethods = unpack_data(data, "!BB")
        assert version == SOCKS5_VERSION

        methods = await reader.readexactly(nmethods)

        auth_method = (
            self.allow_method.value
            if self.allow_method.value in list(methods)
            else AuthenticationMethod.NO_ACCEPTABLE_METHODS
        )
        writer.write(struct.pack("!BB", version, self.allow_method.value))
        await writer.drain()
        if auth_method == AuthenticationMethod.NO_ACCEPTABLE_METHODS:
            return False

        # +----+--------+
        # |VER | METHOD |
        # +----+--------+
        # | 1  |   1    |
        # +----+--------+

        if self.allow_method == AuthenticationMethod.NO_AUTHENTICATION_REQUIRED:
            return True
        elif self.allow_method == AuthenticationMethod.USERNAME_PASSWORD:
            return self.handler_password_auth(reader, writer)

        return False

    async def handler_password_auth(self, reader, writer):
        # https://datatracker.ietf.org/doc/html/rfc1929

        # +----+------+----------+------+----------+
        # |VER | ULEN |  UNAME   | PLEN |  PASSWD  |
        # +----+------+----------+------+----------+
        # | 1  |  1   | 1 to 255 |  1   | 1 to 255 |
        # +----+------+----------+------+----------+

        sub_version = unpack_data(await reader.readexactly(1), "!B")[0]

        assert AUTH_SUB_VERSION == sub_version
        username_length = await reader.readexactly(1)
        username = await reader.readexactly(ord(username_length))
        password_length = await reader.readexactly(1)
        password = await reader.readexactly(ord(password_length))

        # delegate the verification
        authenticated = self.on_auth(username.decode(), password.decode())

        # +----+--------+
        # |VER | STATUS |
        # +----+--------+
        # | 1  |   1    |
        # +----+--------+
        code = AUTH_SUCCESS if authenticated else AUTH_FAILED
        response = struct.pack("!BB", AUTH_SUB_VERSION, code)  # Success
        writer.write(response)
        await writer.drain()
        return authenticated

    async def handler_connect(
        self,
        reader,
        writer,
        dst_addr,
        dst_port,
    ):
        remote_reader, remote_writer = await asyncio.open_connection(dst_addr, dst_port)
        # +----+-----+-------+------+----------+----------+
        # |VER | REP |  RSV  | ATYP | BND.ADDR | BND.PORT |
        # +----+-----+-------+------+----------+----------+
        # | 1  |  1  | X'00' |  1   | Variable |    2     |
        # +----+-----+-------+------+----------+----------+

        # TODO: send status after create connection
        response = generate_response(
            ResponseCode.SUCCEEDED,
            address_type=AddressType.IPV4_ADDRESS,
            bind_addr="0.0.0.0",
            bind_port=0,
        )
        writer.write(response)
        await writer.drain()

        await relay_stream((reader, writer), (remote_reader, remote_writer))

    async def handler_udp_associate(
        self,
        reader,
        writer,
        dst_addr,
        dst_port,
    ):
        stop_event = asyncio.Event()
        try:
            loop = asyncio.get_event_loop()

            self.udp_server_task = loop.create_datagram_endpoint(
                lambda: UDPForwardingServer((dst_addr, dst_port), stop_event),
                local_addr=("0.0.0.0", 0),
            )
            udp_server_transport, udp_server = await asyncio.wait_for(
                self.udp_server_task, 5
            )
        except Exception:
            response = generate_response(
                ResponseCode.GENERAL_FAILURE, AddressType.IPV4_ADDRESS, "0.0.0.0", 0
            )
            writer.write(response)
            await writer.drain()
            raise Exception("General socks server failure occurred")
        else:
            self.udp_server = udp_server
            bind_addr, bind_port = udp_server_transport.get_extra_info("sockname")

            response = generate_response(
                ResponseCode.SUCCEEDED, AddressType.IPV4_ADDRESS, bind_addr, bind_port
            )

            writer.write(response)
            await writer.drain()

            while not stop_event.is_set():
                try:
                    data = await asyncio.wait_for(reader.read(1), 1)
                except asyncio.TimeoutError:
                    continue

                if data == b"":
                    stop_event.set()
                    break


async def main():
    host, port = "127.0.0.1", 1080
    loop = asyncio.get_event_loop()
    server = await loop.create_server(
        lambda: Socks5ProxyServerProtocol(
            on_accept=lambda addr, port: True, on_connect=lambda addr, port: True
        ),
        host,
        port,
    )

    print(f"Serving on {host}:{port}")

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
