import sys
import asyncio
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from loguru import logger
from config import config
from queues import MessageQueues
from alerts import process_incoming_messages, check_and_process_buffer
from telegram import telegram_sender, send_startup_message

logger.remove()
logger.add(config.logging.file, rotation="10 MB", level=config.logging.level)
logger.add(sys.stderr, level=config.logging.level)

message_queues = None

async def log_stats():
    while True:
        total, recent, time_diff, rate = message_queues.get_and_reset_message_stats()
        queue_in = message_queues.incoming_queue.qsize()
        queue_out = message_queues.outgoing_queue.qsize()
        buffer_size = sum(len(alerts) for alerts in message_queues.processed_buffer.values())

        logger.info(
            f"Handler: Received requests: {total:,} ({recent:,} in last {time_diff:.2f} seconds: {rate:.2f}/s) | "
            f"Queue sizes: in={queue_in:,}, out={queue_out:,}, buf={buffer_size:,}"
        )
        await asyncio.sleep(60)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global message_queues
    message_queues = MessageQueues(asyncio.get_running_loop())

    asyncio.create_task(process_incoming_messages(message_queues))
    asyncio.create_task(check_and_process_buffer(message_queues))
    asyncio.create_task(telegram_sender(message_queues))
    asyncio.create_task(log_stats())

    await send_startup_message()

    yield

app = FastAPI(lifespan=lifespan)

@app.post(config.webhook.url_path)
async def handle_incoming_alert(request: Request):
    try:
        data = await request.json()
        logger.debug(f"Received webhook data: {data}")

        message_type = data.get('type')
        if message_type not in config.supported_message_types:
            logger.warning(f"Unsupported message type: {message_type}")
            return {"status": "ERROR", "message": "Unsupported message type"}

        await message_queues.add_to_incoming(data)
        return {"status": "OK"}
    except Exception as e:
        logger.exception(f"Error processing incoming alert: {str(e)}")
        return {"status": "ERROR", "message": str(e)}

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=config.fastapi.host,
        port=config.fastapi.port,
        ssl_keyfile=config.fastapi.tls_keyfile,
        ssl_certfile=config.fastapi.tls_certfile,
        log_config=None
    )
