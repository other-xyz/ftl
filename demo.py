# -*- coding: utf-8 -*-
"""This file demonstrates usage of ftl and serves as a very basic functionality
test. It makes requests to https://http2.golang.org which provides a number of
simple HTTP/2 endpoints to play with.
"""
import asyncio
import logging
import signal
import zlib
from argparse import ArgumentParser
from pathlib import Path

from ftl import create_connection
from ftl.stream import StreamConsumedError


HOST = 'http2.golang.org'


def _print_headers(headers):
    for k, v in headers.items():
        print(f'{k}:\t{v}')


def print_headers(headers):
    print('∨∨∨∨ HEADERS ∨∨∨∨')
    _print_headers(headers)
    print('∧∧∧∧ HEADERS ∧∧∧∧\n')


def print_data(data, stream_id=None):
    print(f'∨∨∨∨ DATA [{stream_id}] ∨∨∨∨')
    print(data.decode())
    print(f'∧∧∧∧ DATA [{stream_id}] ∧∧∧∧\n')


def print_trailers(trailers):
    print('∨∨∨∨ TRAILERS ∨∨∨∨')
    _print_headers(trailers)
    print('∧∧∧∧ TRAILERS ∧∧∧∧\n')


async def clockstream(http2):
    stream_id = await http2.send_request('GET', '/clockstream', end_stream=True)

    response = await http2.read_response(stream_id)
    print_headers(response.headers)

    signal.signal(
        signal.SIGINT,
        lambda s, f: asyncio.ensure_future(http2.reset_stream(stream_id)),
    )

    print(f'∨∨∨∨ DATA [{stream_id}] ∨∨∨∨')
    async for frame in http2.stream_frames(stream_id):
        print(frame.decode(), end='')
    print(f'∧∧∧∧ DATA [{stream_id}] ∧∧∧∧\n')


async def crc32(http2, data):
    size = len(data)
    cksum = zlib.crc32(data)
    print(f'CRC32 computed locally ({size} bytes): {cksum:08x}\n')

    stream_id = await http2.send_request('PUT', '/crc32')
    await http2.send_data(stream_id, data, end_stream=True)

    response = await http2.read_response(stream_id)
    print_headers(response.headers)
    data = await http2.read_data(stream_id)
    print_data(data, stream_id)
    trailers = await response.trailers()
    print_trailers(trailers)


async def echo(http2, data):
    stream_id = await http2.send_request('PUT', '/ECHO')
    await http2.send_data(stream_id, data, end_stream=True)

    response = await http2.read_response(stream_id)
    print_headers(response.headers)
    data = await http2.read_data(stream_id)
    print_data(data, stream_id)
    trailers = await response.trailers()
    print_trailers(trailers)


async def reqinfo(http2):
    stream_id = await http2.send_request(
        'GET',
        '/reqinfo',
        additional_headers=[('foo', 'bar')],
        end_stream=True,
    )

    response = await http2.read_response(stream_id)
    print_headers(response.headers)
    data = await http2.read_data(stream_id)
    print_data(data, stream_id)
    trailers = await response.trailers()
    print_trailers(trailers)


async def serverpush(http2):
    parent_id = await http2.send_request('GET', '/serverpush', end_stream=True)

    response = await http2.read_response(parent_id)
    print_headers(response.headers)

    pushed = await http2.get_pushed_stream_ids(parent_id)
    print(f'{len(pushed)} streams pushed: {pushed}')
    stream_data = {s_id: b'' for s_id in pushed}
    stream_data[parent_id] = b''

    while len(stream_data) > 0:
        for s_id in list(stream_data.keys()):
            while True:
                # Consume all immediately available data from each stream
                try:
                    frame = http2.read_frame_nowait(s_id)
                except StreamConsumedError as e:
                    data = stream_data.pop(e.stream_id)
                    print(f'Stream {e.stream_id} ended; received {len(data)} bytes')
                    break

                if frame is None:
                    break
                stream_data[s_id] += frame

        # Buffered data consumed; sleep to allow more to arrive
        await asyncio.sleep(0.01)


async def main(args, loop):
    http2 = await create_connection(HOST, 443, loop=loop)

    if args.endpoint == 'clockstream':
        await clockstream(http2)
    elif args.endpoint == 'crc32':
        path = Path(args.input).expanduser()
        with path.open(mode='rb') as f:
            data = f.read()
        await crc32(http2, data)
    elif args.endpoint == 'echo':
        data = args.input.encode()
        await echo(http2, data)
    elif args.endpoint == 'reqinfo':
        await reqinfo(http2)
    elif args.endpoint == 'serverpush':
        await serverpush(http2)


if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument(
        '-v',
        '--verbose',
        action='store_true',
        help='display debug output',
    )
    parser.add_argument(
        'endpoint',
        nargs='?',
        default='reqinfo',
        type=str,
        choices=['clockstream', 'crc32', 'echo', 'reqinfo', 'serverpush'],
        help='demo endpoint to use',
    )
    parser.add_argument(
        'input',
        nargs='?',
        default=None,
        type=str,
        help='input for endpoints that require it',
    )

    args = parser.parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)
    logging.getLogger('hpack.hpack').setLevel(logging.WARNING)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(main(args, loop))
