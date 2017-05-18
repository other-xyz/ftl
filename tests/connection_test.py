# -*- coding: utf-8 -*-
from secrets import token_bytes
from zlib import crc32

import pytest

from asynch2 import create_connection


@pytest.fixture
def host():
    return 'http2.golang.org'


@pytest.mark.asyncio
async def test_put_multiple_frames(event_loop, host):
    # 4 MB of junk to exceed single frame maximum
    data = token_bytes(4 * 1024 * 1024)
    checksum = crc32(data)

    http2 = await create_connection(host, 443, loop=event_loop)
    stream_id = await http2.send_request('PUT', 'https', host, '/crc32')
    await http2.send_data(stream_id, data, end_stream=True)

    headers = await http2.read_headers(stream_id)
    assert headers[':status'] == '200'
    assert headers['content-type'] == 'text/plain'

    response = await http2.read_data(stream_id)
    assert response.decode() == f'bytes={len(data)}, CRC32={checksum:08x}'