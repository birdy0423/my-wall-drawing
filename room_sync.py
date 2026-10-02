"""Ordered, bounded per-peer delivery. All operations run on one asyncio loop."""
import asyncio
import json
from contextlib import suppress

QUEUE_LIMIT = 256
SEND_TIMEOUT = 2.0
STORY_TIMEOUT = 60.0


class Peer:
    def __init__(self, hub, room, websocket):
        self.hub, self.room, self.websocket = hub, room, websocket
        self.queue = asyncio.Queue(maxsize=QUEUE_LIMIT)
        self.closed = False
        self.close_code = 1000
        self.task = asyncio.create_task(self._write())

    async def _write(self):
        try:
            while True:
                payload = await self.queue.get()
                try:
                    async with asyncio.timeout(SEND_TIMEOUT):
                        await self.websocket.send_text(payload)
                    self.hub.delivered += 1
                finally:
                    self.queue.task_done()
        except asyncio.CancelledError:
            raise
        except Exception:
            self.close_code = 1013
            self.hub.slow_or_failed += 1
        finally:
            self.closed = True
            self.hub.discard(self)
            while not self.queue.empty():
                self.queue.get_nowait()
                self.queue.task_done()
            with suppress(Exception, asyncio.CancelledError):
                async with asyncio.timeout(0.5):
                    await self.websocket.close(code=self.close_code)

    def enqueue(self, encoded):
        if self.closed:
            return
        try:
            self.queue.put_nowait(encoded)
        except asyncio.QueueFull:
            self.hub.slow_or_failed += 1
            self.close_code = 1013
            self.closed = True
            self.hub.discard(self)
            self.task.cancel()
            cleanup = asyncio.create_task(self.hub.leave(self))
            self.hub.cleanups.add(cleanup)
            cleanup.add_done_callback(self.hub.cleanups.discard)


class RoomHub:
    def __init__(self):
        self.rooms = {}
        self.writers = set()
        self.cleanups = set()
        self.delivered = 0
        self.slow_or_failed = 0

    def join(self, room, websocket):
        peer = Peer(self, room, websocket)
        self.rooms.setdefault(room, set()).add(peer)
        self.writers.add(peer.task)
        peer.task.add_done_callback(self.writers.discard)
        return peer

    def discard(self, peer):
        members = self.rooms.get(peer.room)
        if members is not None:
            members.discard(peer)
            if not members:
                self.rooms.pop(peer.room, None)

    async def leave(self, peer):
        peer.closed = True
        self.discard(peer)
        if peer.task is not asyncio.current_task():
            peer.task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await peer.task
        # Also covers cancellation before the writer ever started.
        while not peer.queue.empty():
            peer.queue.get_nowait()
            peer.queue.task_done()
        with suppress(Exception, asyncio.CancelledError):
            async with asyncio.timeout(0.5):
                await peer.websocket.close(code=peer.close_code)

    def send(self, peer, message):
        peer.enqueue(json.dumps(message, ensure_ascii=False))

    def broadcast(self, room, message, sender=None):
        encoded = json.dumps(message, ensure_ascii=False)
        for peer in tuple(self.rooms.get(room, ())):
            if peer.websocket is not sender:
                peer.enqueue(encoded)

    async def close(self):
        tasks = tuple(self.writers)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(*tuple(self.cleanups), return_exceptions=True)
        self.rooms.clear()


class StoryError(Exception):
    def __init__(self, code, message, status=502):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status

    def payload(self):
        return {"type": "error", "error": self.code, "detail": self.message}


class StoryJobs:
    def __init__(self):
        self.jobs = {}

    def start(self, room, generate):
        if room in self.jobs:
            raise StoryError("story_busy", "這個房間正在生成故事，請稍候再試。", 409)
        task = asyncio.create_task(self._run(room, generate))
        self.jobs[room] = task
        def completed(done):
            if self.jobs.get(room) is done:
                self.jobs.pop(room, None)
        task.add_done_callback(completed)
        return task

    async def _run(self, room, generate):
        try:
            async with asyncio.timeout(STORY_TIMEOUT):
                return await generate()
        except asyncio.TimeoutError:
            raise StoryError("story_timeout", "故事生成逾時，請稍後再試。", 504) from None
        except StoryError:
            raise
        except Exception:
            raise StoryError("story_failed", "故事生成失敗，請稍後再試。") from None
        finally:
            if self.jobs.get(room) is asyncio.current_task():
                self.jobs.pop(room, None)

    async def close(self):
        tasks = tuple(self.jobs.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.jobs.clear()
