import asyncio
from asyncio import StreamReader


def create_stream_reader_from_file(file: str) -> StreamReader:
    r = StreamReader()

    async def feed():
        await asyncio.sleep(0.01)
        with open(file, "rb") as f:
            r.feed_data(f.read())
            r.feed_eof()

    loop = asyncio.get_event_loop()
    loop.create_task(feed())

    return r
