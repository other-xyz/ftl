# -*- coding: utf-8 -*-
import asyncio
import logging
from collections import namedtuple
from typing import List
from typing import Optional
from typing import Tuple

from multidict import MultiDict

from asynch2.errors import StreamClosedError


logger = logging.getLogger(__name__)


DataFrame = namedtuple('DataFrame', ('data', 'flow_controlled_length'))


class HTTP2Stream:

    def __init__(self, stream_id, *, loop=None):
        loop = loop or asyncio.get_event_loop()

        self._id = stream_id
        self._closed = False

        self._data_frames = asyncio.Queue(loop=loop)

        self._request_headers = None
        self._response_headers = asyncio.Future(loop=loop)
        self._response_trailers = asyncio.Future(loop=loop)

        self._window_open = asyncio.Event(loop=loop)
        self._pushed_streams_available = asyncio.Event(loop=loop)

    # Properties

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def id(self) -> int:
        return self._id

    @property
    def pushed_streams_available(self) -> asyncio.Event:
        return self._pushed_streams_available

    @property
    def request(self) -> MultiDict:
        return self._request_headers

    @property
    def window_open(self) -> asyncio.Event:
        return self._window_open

    # Helpers

    def close(self):
        if self.closed:
            return
        self._closed = True
        self._window_open.clear()
        self._data_frames.put_nowait(None)  # Wake up any waiting consumers
        if not self._response_trailers.done():
            self._response_trailers.set_result(MultiDict())

    # State manipulation by HTTP2Protocol

    def receive_data(self, data: bytes, flow_controlled_length: int):
        frame = DataFrame(
            data=data,
            flow_controlled_length=flow_controlled_length,
        )
        self._data_frames.put_nowait(frame)

    def receive_promise(self, headers: List[Tuple[str, str]]):
        self._request_headers = MultiDict(headers)

    def receive_response(self, headers: List[Tuple[str, str]]):
        self._response_headers.set_result(MultiDict(headers))

    def receive_trailers(self, trailers: List[Tuple[str, str]]):
        self._response_trailers.set_result(MultiDict(trailers))

    # Readers

    async def read_frame(self) -> DataFrame:
        """Read a single frame from the local buffer.

        If no frames are available but the stream is still open, waits until
        more frames arrive. Otherwise, raises StreamClosedError.

        When a stream is closed, a single `None` is added to the data frame
        Queue to wake up any waiting `read_frame` coroutines.
        """
        if self._data_frames.qsize() == 0 and self.closed:
            raise StreamClosedError
        frame = await self._data_frames.get()
        self._data_frames.task_done()
        if frame is None:
            raise StreamClosedError
        return frame

    def read_frame_nowait(self) -> Optional[DataFrame]:
        """Read a single frame from the local buffer immediately.

        If no frames are available but the stream is still open, returns None.
        Otherwise, raises StreamClosedError.
        """
        try:
            frame = self._data_frames.get_nowait()
        except asyncio.QueueEmpty:
            if self.closed:
                raise StreamClosedError
            return None
        self._data_frames.task_done()
        if frame is None:
            raise StreamClosedError
        return frame

    async def read_headers(self) -> MultiDict:
        return await self._response_headers

    async def read_trailers(self) -> MultiDict:
        return await self._response_trailers
