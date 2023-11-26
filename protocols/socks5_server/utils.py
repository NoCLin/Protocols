import socket
import struct
from _socket import inet_pton
from asyncio import StreamReader
from typing import Optional

from protocols.socks5_server.consts import AddressType, ResponseCode, SOCKS5_VERSION


def unpack_data(data: bytes, fmt: str) -> tuple:
    values = struct.unpack(fmt, data)
    return values


def guess_type(addr: str) -> AddressType:
    try:
        inet_pton(socket.AF_INET, addr)
        return AddressType.IPV4_ADDRESS
    except OSError:
        pass

    try:
        inet_pton(socket.AF_INET6, addr)
        return AddressType.IPV6_ADDRESS
    except OSError:
        pass

    return AddressType.DOMAIN_NAME


async def unpack_address_port(reader: StreamReader) -> tuple[int, str, int]:
    address_type: int = unpack_data(await reader.read(1), "!B")[0]

    t = AddressType(address_type)

    if t == AddressType.IPV4_ADDRESS:
        b_address = await reader.readexactly(4)
        address = socket.inet_ntoa(b_address)
    elif t == AddressType.DOMAIN_NAME:
        domain_length = await reader.readexactly(1)
        b_domain = await reader.readexactly(ord(domain_length))
        address = b_domain.decode()
    elif t == AddressType.IPV6_ADDRESS:
        b_address = await reader.readexactly(16)
        address = socket.inet_ntop(socket.AF_INET6, b_address)
    else:
        raise ValueError(f"Invalid address type: {address_type}")

    data = await reader.readexactly(2)
    port = unpack_data(data, "!H")

    return address_type, address, port[0]


def pack_address_port(addr, port, address_type: Optional[AddressType] = None):
    if address_type is None:
        address_type = guess_type(addr)

    if address_type == AddressType.IPV4_ADDRESS:
        bind_addr_bytes = inet_pton(socket.AF_INET, addr)
    elif address_type == AddressType.IPV6_ADDRESS:
        bind_addr_bytes = inet_pton(socket.AF_INET6, addr)
    else:
        bind_addr_bytes = struct.pack("!H", len(addr)) + addr.encode()

    return (
        struct.pack("!B", address_type.value)
        + bind_addr_bytes
        + struct.pack("!H", port)
    )


def generate_response(
    code: ResponseCode, address_type: AddressType, bind_addr: str, bind_port: int
):
    # +----+-----+-------+------+----------+----------+
    # |VER | REP |  RSV  | ATYP | BND.ADDR | BND.PORT |
    # +----+-----+-------+------+----------+----------+
    # | 1  |  1  | X'00' |  1   | Variable |    2     |
    # +----+-----+-------+------+----------+----------+
    return struct.pack(
        "!BBB",
        SOCKS5_VERSION,
        code.value,
        0x00,
    ) + pack_address_port(bind_addr, bind_port, address_type=address_type)
