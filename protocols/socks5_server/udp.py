import asyncio
import itertools
from asyncio import DatagramProtocol, StreamReader, Event, DatagramTransport
from typing import Tuple, Optional

from protocols.socks5_server.utils import unpack_address_port, pack_address_port


async def unpack_udp_header(reader: StreamReader):
    # +----+------+------+----------+----------+----------+
    # |RSV | FRAG | ATYP | DST.ADDR | DST.PORT |   DATA   |
    # +----+------+------+----------+----------+----------+
    # | 2  |  1   |  1   | Variable |    2     | Variable |
    # +----+------+------+----------+----------+----------+

    _ = await reader.read(2)
    frag = await reader.read(1)
    if frag != b"\x00":
        raise Exception("Received unsupported frag value", frag)

    address_type, dst_addr, dst_port = await unpack_address_port(reader)
    return dst_addr, dst_port, await reader.read()


def pack_udp_header(dst_addr, dst_port):
    rsv = b"\x00\x00"
    frag = b"\x00"
    return rsv + frag + pack_address_port(dst_addr, dst_port)


class UDPForwardingServer(DatagramProtocol):
    def __init__(self, host_port_limit: Tuple[str, int], stop_event: Event):
        self.host_port_limit = host_port_limit
        self.transport: DatagramTransport
        self.udp_client: Optional[UDPClient] = None
        self.stop_event = stop_event

    def write(self, data, port_addr):
        if not self.transport.is_closing():
            self.transport.sendto(data, port_addr)

    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr: Tuple[str, int]):
        if self.host_port_limit not in list(
            itertools.product(("0.0.0.0", "::", "0", addr[0]), (0, addr[1]))
        ):
            return
        reader: StreamReader = StreamReader()
        reader.feed_data(data)
        reader.feed_eof()

        loop = asyncio.get_event_loop()
        loop.create_task(self.handle_forwarding(reader, addr))

    async def handle_forwarding(self, reader: StreamReader, addr: Tuple[str, int]):
        dst_addr, dst_port, data = await unpack_udp_header(reader)
        if not self.udp_client:
            loop = asyncio.get_event_loop()
            task = loop.create_datagram_endpoint(
                lambda: UDPClient(
                    self,
                    client_addr=addr,
                ),
                local_addr=("0.0.0.0", 0),
            )
            _, self.udp_client = await asyncio.wait_for(task, 5)

        if self.udp_client:
            self.udp_client.write(data, (dst_addr, dst_port))

    def close(self):
        self.stop_event.set()
        self.transport.close()
        if self.udp_client:
            self.udp_client.close()

    def connection_lost(self, exc: Optional[Exception]) -> None:
        self.close()


class UDPClient(asyncio.DatagramProtocol):
    def __init__(
        self,
        local_udp,
        client_addr,
    ):
        self.udp_server = local_udp
        self.client_addr = client_addr
        self.transport: DatagramTransport

    def connection_made(self, transport) -> None:
        self.transport = transport

    def write(self, data, host_port):
        if not self.transport.is_closing():
            self.transport.sendto(data, host_port)

    def datagram_received(self, data: bytes, addr: Tuple[str, int]) -> None:
        header = pack_udp_header(*addr)
        self.udp_server.write(header + data, self.client_addr)

    def close(self):
        if not self.transport.is_closing():
            self.transport.close()

    def error_received(self, exc):
        self.close()

    def connection_lost(self, exc):
        super().connection_lost(exc)
        self.close()
