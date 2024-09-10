import asyncio
from typing import Dict
import httpx
from loguru import logger
from config import config
from queues import MessageQueues

TELEGRAM_API_URL = f'https://api.telegram.org/bot{config.telegram.bot_token}'
TELEGRAM_SEND_INTERVAL = 5  # seconds

tg_escape_chars = {
    "<": "&lt;",
    ">": "&gt;",
}

def escape_html(msg: str) -> str:
    return ''.join(tg_escape_chars.get(ch, ch) for ch in msg)

async def send_telegram_message(message: str, max_retries: int = 3) -> Dict:
    url = f"{TELEGRAM_API_URL}/sendMessage"
    data = {
        "chat_id": config.telegram.chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=data)
                response.raise_for_status()
                logger.debug(f"Telegram API request: {url}")
                logger.debug(f"Telegram API response: {response.text}")
                return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Attempt {attempt + 1}/{max_retries} failed to send message to Telegram: {str(e)}")
            logger.debug(f"Failed request data: {data}")
            logger.debug(f"Error response: {e.response.text if e.response else 'No response'}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
            else:
                raise

async def send_startup_message():
    startup_message = "🚀 NAD bot has started."
    try:
        await send_telegram_message(startup_message)
        logger.info("Startup message sent to Telegram successfully")
    except Exception as e:
        logger.error(f"Failed to send startup message to Telegram: {e}")

async def telegram_sender(message_queues: MessageQueues):
    last_send_time = 0
    while True:
        message = await message_queues.get_from_outgoing()
        try:
            current_time = asyncio.get_event_loop().time()
            time_since_last_send = current_time - last_send_time
            if time_since_last_send < TELEGRAM_SEND_INTERVAL:
                await asyncio.sleep(TELEGRAM_SEND_INTERVAL - time_since_last_send)

            logger.info(f"Sending message to Telegram:\n{message}")
            await send_telegram_message(message)
            last_send_time = asyncio.get_event_loop().time()
            logger.info("Successfully sent prepared message to Telegram")
        except Exception as e:
            logger.exception(f"Failed to send prepared message to Telegram: {e}")
        finally:
            message_queues.outgoing_queue.task_done()
