from pydantic import BaseModel, ConfigDict, ValidationError
from typing import List, Dict, Any
import yaml
import os

class TelegramConfig(BaseModel):
    bot_token: str
    chat_id: str

class WebhookConfig(BaseModel):
    secret_token: str
    url_path: str = ""

class FastAPIConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    tls_keyfile: str = "key.pem"
    tls_certfile: str = "cert.pem"

class LoggingConfig(BaseModel):
    file: str = "bot.log"
    level: str = "INFO"

class AlertConfig(BaseModel):
    priority_filter: List[int] = [1]
    max_buffer_time: int = 300
    grouping_max_count: int = 10
    ignore_sids: List[int] = []
    ignore_msg: List[str] = []
    timezone: str = "UTC"
    rules_filter: List[str] = ["PT"]
    force_session_link: bool = False
    show_nad_source: bool = False

class Config(BaseModel):
    telegram: TelegramConfig
    webhook: WebhookConfig
    fastapi: FastAPIConfig = FastAPIConfig()
    logging: LoggingConfig = LoggingConfig()
    alert: AlertConfig = AlertConfig()
    supported_message_types: List[str] = ["alert"]

    model_config = ConfigDict(extra='ignore')

def deep_update(base_dict: Dict[str, Any], update_dict: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in update_dict.items():
        if isinstance(value, dict) and key in base_dict and isinstance(base_dict[key], dict):
            base_dict[key] = deep_update(base_dict[key], value)
        else:
            base_dict[key] = value
    return base_dict

def load_config(config_path: str = "config.yaml") -> Config:
    try:
        with open(config_path, 'r') as file:
            yaml_config = yaml.safe_load(file) or {}
    except FileNotFoundError:
        yaml_config = {}

    config_dict = Config(
        telegram=TelegramConfig(
            bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            chat_id=os.getenv("TELEGRAM_CHAT_ID", "")
        ),
        webhook=WebhookConfig(
            secret_token=os.getenv("WEBHOOK_SECRET_TOKEN", ""),
            url_path=""
        )
    ).model_dump()

    merged_config = deep_update(config_dict, yaml_config)

    if not merged_config["webhook"]["url_path"] and merged_config["webhook"]["secret_token"]:
        merged_config["webhook"]["url_path"] = f"/webhook/{merged_config['webhook']['secret_token']}"

    try:
        config = Config.model_validate(merged_config)
    except ValidationError as e:
        raise ValueError(f"Configuration validation error: {e}")

    missing_fields = []
    if not config.telegram.bot_token:
        missing_fields.append("TELEGRAM_BOT_TOKEN")
    if not config.telegram.chat_id:
        missing_fields.append("TELEGRAM_CHAT_ID")
    if not config.webhook.secret_token:
        missing_fields.append("WEBHOOK_SECRET_TOKEN")
    if not os.path.isfile(config.fastapi.tls_keyfile):
        missing_fields.append(f"TLS key file (path: {config.fastapi.tls_keyfile})")
    if not os.path.isfile(config.fastapi.tls_certfile):
        missing_fields.append(f"TLS certificate file (path: {config.fastapi.tls_certfile})")

    if missing_fields:
        raise ValueError(f"Missing required configuration: {', '.join(missing_fields)}. "
                         f"Please set these in environment variables, config.yaml, or ensure TLS files exist")

    return config

config = load_config()
