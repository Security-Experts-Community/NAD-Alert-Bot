import asyncio
import time
from typing import Dict, Any, List, Tuple
from collections import defaultdict
from config import config
import sys
from urllib.parse import urlparse

class MessageQueues:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        if sys.version_info < (3, 10):
            self.incoming_queue = asyncio.Queue(loop=self.loop)
            self.outgoing_queue = asyncio.Queue(loop=self.loop)
        else:
            self.incoming_queue = asyncio.Queue()
            self.outgoing_queue = asyncio.Queue()
        self.processed_buffer: Dict[Tuple[int, str], List[Dict[str, Any]]] = defaultdict(list)
        self.buffer_lock = asyncio.Lock()
        self.first_valid_alert_time = 0
        self.total_received_messages = 0
        self.last_log_time = time.time()
        self.messages_since_last_log = 0

    async def add_to_incoming(self, message: Dict[str, Any]):
        await self.incoming_queue.put(message)
        self.total_received_messages += 1
        self.messages_since_last_log += 1

    async def get_from_incoming(self):
        return await self.incoming_queue.get()

    async def add_to_outgoing(self, message: str):
        await self.outgoing_queue.put(message)

    async def get_from_outgoing(self):
        return await self.outgoing_queue.get()

    async def add_to_buffer(self, alert: Dict[str, Any]):
        async with self.buffer_lock:
            sid = alert['alert']['s_id']
            nad_source = urlparse(alert['flow_url']).netloc
            key = (sid, nad_source)
            if not self.processed_buffer:
                self.first_valid_alert_time = self.loop.time()
            self.processed_buffer[key].append(alert)

    async def clear_buffer(self):
        async with self.buffer_lock:
            buffer = self.processed_buffer
            self.processed_buffer = defaultdict(list)
            self.first_valid_alert_time = 0
        return buffer

    async def should_process_buffer(self) -> bool:
        async with self.buffer_lock:
            current_time = self.loop.time()
            return (len(self.processed_buffer) >= config.alert.grouping_max_count or
                    (self.processed_buffer and current_time - self.first_valid_alert_time >= config.alert.max_buffer_time))

    def get_and_reset_message_stats(self):
        current_time = time.time()
        time_diff = current_time - self.last_log_time
        messages = self.messages_since_last_log
        rate = messages / time_diff if time_diff > 0 else 0

        stats = (self.total_received_messages, messages, time_diff, rate)

        self.last_log_time = current_time
        self.messages_since_last_log = 0

        return stats

message_queues = None
