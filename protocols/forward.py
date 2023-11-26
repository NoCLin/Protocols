import asyncio
from asyncio import StreamReader, StreamWriter, Event
from contextlib import closing
from typing import Tuple

StreamPair = Tuple[StreamReader, StreamWriter]


async def forward_stream(reader: StreamReader, writer: StreamWriter, event: Event):
    while not event.is_set():
        try:
            data = await asyncio.wait_for(reader.read(1024), 2)
        except asyncio.TimeoutError:
            continue
        if data == b"":
            event.set()
            break

        writer.write(data)
        await writer.drain()


async def relay_stream(local_stream: StreamPair, remote_stream: StreamPair):
    local_reader, local_writer = local_stream
    remote_reader, remote_writer = remote_stream

    close_event = asyncio.Event()
    with closing(remote_writer):
        with closing(local_writer):
            await asyncio.gather(
                forward_stream(local_reader, remote_writer, close_event),
                forward_stream(remote_reader, local_writer, close_event),
            )
