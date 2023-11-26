import asyncio
import os.path
import unittest
from unittest import mock

import requests

from protocols.http_proxy.server import HttpProxyServerProtocol
from protocols.stream_utils import create_stream_reader_from_file
from protocols.tests.setup_http_server import SetupHttpServer


class TestHTTPProxyServer(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        async def test():
            self.server = await self.loop.create_server(
                lambda: HttpProxyServerProtocol(),
                "127.0.0.1",
                8080,
            )
            self.server_task = self.loop.create_task(self.server.serve_forever())

        self.loop.run_until_complete(test())

    def tearDown(self):
        async def stop_server():
            self.server_task.cancel()
            await self.server.wait_closed()

        self.loop.run_until_complete(stop_server())
        self.loop.close()

    def test_mock_open_connection(self):
        w = mock.AsyncMock(asyncio.StreamWriter)
        r = create_stream_reader_from_file(
            os.path.join(os.path.dirname(__file__), "../tests/fixtures", "http.bin")
        )

        with mock.patch(
            "asyncio.open_connection", return_value=[r, w]
        ) as mocked_open_connection:

            async def test():
                proxy_response_header = {
                    "Date": "Sun, 19 Nov 2023 14:21:13 GMT",
                    "Server": "Apache",
                    "Last-Modified": "Tue, 12 Jan 2010 13:48:00 GMT",
                    "ETag": '"51-47cf7e6ee8400"',
                    "Accept-Ranges": "bytes",
                    "Content-Length": "80",
                    "Cache-Control": "max-age=86400",
                    "Expires": "Mon, 20 Nov 2023 14:21:13 GMT",
                    "Connection": "Keep-Alive",
                    "Content-Type": "text/html",
                }
                proxy_response_body = """<html>
<meta http-equiv="refresh" content="0;url=http://www.baidu.com/">
</html>"""
                proxy_request_header = (
                    b"GET / HTTP/1.1\r\n"
                    b"Host: 127.0.0.1\r\n"
                    b"User-Agent: test\r\n"
                    b"Accept-Encoding: gzip, deflate\r\n"
                    b"Accept: */*\r\n\r\n"
                )

                response = await self.loop.run_in_executor(
                    None,
                    lambda: requests.get(
                        "http://127.0.0.1",
                        proxies={"http": "http://127.0.0.1:8080"},
                        headers={"User-Agent": "test"},
                    ),
                )
                self.assertEqual(200, response.status_code)
                self.assertEqual(proxy_response_header, response.headers)
                self.assertEqual(proxy_response_body, response.text)

                self.assertEqual(2, len(w.method_calls))
                self.assertEqual("write", w.method_calls[0][0])
                self.assertEqual((proxy_request_header,), w.method_calls[0][1])
                self.assertEqual("drain", w.method_calls[1][0])

            self.loop.run_until_complete(test())

            self.assertEqual(mocked_open_connection.call_count, 1)
            self.assertEqual(1, len(mocked_open_connection.call_args_list))
            self.assertEqual(
                ("127.0.0.1", 80), mocked_open_connection.call_args_list[0][0]
            )

    def test_https_forwarding(self):
        with SetupHttpServer(https=True):

            async def test():
                proxy_response_body = """Hello, World!"""
                response = await self.loop.run_in_executor(
                    None,
                    lambda: requests.get(
                        "https://127.0.0.1:8000",
                        proxies={"https": "http://127.0.0.1:8080"},
                        headers={"User-Agent": "test"},
                        verify=False,
                    ),
                )
                self.assertEqual(200, response.status_code)
                self.assertEqual(proxy_response_body, response.text)

            self.loop.run_until_complete(test())

    def test_http_forwarding(self):
        with SetupHttpServer():

            async def test():
                proxy_response_body = """Hello, World!"""
                response = await self.loop.run_in_executor(
                    None,
                    lambda: requests.get(
                        "http://127.0.0.1:8000",
                        proxies={"http": "http://127.0.0.1:8080"},
                        headers={"User-Agent": "test"},
                        verify=False,
                    ),
                )
                self.assertEqual(200, response.status_code)
                self.assertEqual(proxy_response_body, response.text)

            self.loop.run_until_complete(test())


if __name__ == "__main__":
    unittest.main()
