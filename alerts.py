import asyncio
from typing import Dict, List, Optional, Callable, Tuple
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlparse, urlencode
from pydantic import BaseModel, ConfigDict
from loguru import logger
from config import config
from queues import MessageQueues
from telegram import escape_html

class GeoInfo(BaseModel):
    location: Optional[List[float]] = None
    country: Optional[str] = None
    city: Optional[str] = None
    asn: Optional[int] = None
    org: Optional[str] = None

class HostInfo(BaseModel):
    ip: Optional[str] = None
    port: Optional[int] = None
    mac: Optional[str] = None
    host_id: Optional[str] = None
    geo: Optional[GeoInfo] = None

class AlertInfo(BaseModel):
    s_id: Optional[int] = None
    s_msg: Optional[str] = None
    s_rev: Optional[int] = None
    s_cls: Optional[str] = None
    s_pr: Optional[int] = None
    s_g: Optional[int] = None
    ts: Optional[datetime] = None
    tx_id: Optional[int] = None
    to_client: Optional[bool] = None
    to_server: Optional[bool] = None
    payload: Optional[str] = None

class Alert(BaseModel):
    type: Optional[str] = "alert"
    flow_id: Optional[str] = None
    flow_url: Optional[str] = None
    ts_start: Optional[datetime] = None
    src: Optional[HostInfo] = None
    dst: Optional[HostInfo] = None
    alert: Optional[AlertInfo] = None
    proto: Optional[str] = None
    app_proto: Optional[str] = None

    model_config = ConfigDict(extra='ignore')

def get_priority_color(priority: int) -> str:
    return {1: "🟥", 2: "🟨", 3: "🟦"}.get(priority, "⬜")

def create_rule_filter() -> Callable[[str], bool]:
    if not config.alert.rules_filter:
        return lambda _: True

    specific_rules = {
        'PT': lambda msg: 'PT'+'security' in msg,
        'ET': lambda msg: msg.startswith('ET'),
    }

    def custom_rule(msg):
        return all(not check(msg) for check in specific_rules.values())

    active_rules = set(config.alert.rules_filter)

    def combined_filter(msg):
        for rule, check in specific_rules.items():
            if rule in active_rules and check(msg):
                return True
        if 'Custom' in active_rules and custom_rule(msg):
            return True
        return False

    return combined_filter

rule_filter = create_rule_filter()

def should_process_alert(alert_info: AlertInfo) -> bool:
    return rule_filter(alert_info.s_msg)

def should_ignore_alert(alert_info: AlertInfo) -> bool:
    if alert_info.s_id in config.alert.ignore_sids:
        return True
    return alert_info.s_msg and any(ignore_msg.lower() in alert_info.s_msg.lower() for ignore_msg in config.alert.ignore_msg)

def format_datetime(dt: datetime) -> str:
    if dt:
        tz = ZoneInfo(config.alert.timezone)
        return dt.replace(tzinfo=ZoneInfo('UTC')).astimezone(tz).strftime("%Y-%m-%d %H:%M:%S (%Z)")
    return "N/A"

def format_ip_port(alerts: List[Alert], attr: str) -> str:
    ips = set(getattr(getattr(a, attr), 'ip') for a in alerts if getattr(getattr(a, attr), 'ip'))
    ports = set(getattr(getattr(a, attr), 'port') for a in alerts if getattr(getattr(a, attr), 'port'))

    if len(ips) == 1:
        ip = ips.pop()
        if len(ports) == 1:
            return f"<code>{ip}:{ports.pop()}</code>"
        return f"<code>{ip}</code>"
    else:
        return f"<i>({len(ips)} different IP addresses)</i>"

def create_group_link(alerts: List[Alert]) -> str:
    if not alerts:
        return ""

    first_alert = alerts[0]
    parsed_url = urlparse(first_alert.flow_url)
    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"

    earliest_ts = min(a.ts_start for a in alerts if a.ts_start)
    unix_timestamp = int(earliest_ts.replace(tzinfo=ZoneInfo('UTC')).timestamp() * 1000)  # Convert to milliseconds

    sid = first_alert.alert.s_id if first_alert.alert else None
    flow_ids = [a.flow_id for a in alerts if a.flow_id]

    filter_conditions = []
    if sid is not None:
        filter_conditions.append(f"alert.sid == {sid}")

    if len(flow_ids) <= 10:
        flow_ids_str = ", ".join(f"'{flow_id}'" for flow_id in flow_ids)
        filter_conditions.append(f"id in [{flow_ids_str}]")

    filter_str = " && ".join(filter_conditions)

    params = {
        "from": unix_timestamp,
        "sources": "2",
        "filter": filter_str
    }

    query_string = urlencode(params)
    return f"{base_url}/#/alerts/list?{query_string}"

def get_domain_from_url(url: str) -> str:
    parsed_url = urlparse(url)
    return parsed_url.netloc

def format_alert_message(alerts: List[Alert]) -> str:
    first_alert = alerts[0]
    priority_color = get_priority_color(first_alert.alert.s_pr)
    protocol = first_alert.proto
    protocol_str = f"<b>Protocol:</b> <code>{protocol}</code>"
    if first_alert.app_proto:
        protocol_str += f" (<code>{first_alert.app_proto}</code>)"

    src_str = format_ip_port(alerts, 'src')
    dst_str = format_ip_port(alerts, 'dst')

    nad_source = urlparse(first_alert.flow_url).netloc

    message = f"{priority_color} <b>{escape_html(first_alert.alert.s_msg)}</b>"
    if len(alerts) > 1:
        message += f" ({len(alerts)} occurrences)"

    message += f"""
<b>Source:</b> {src_str}
<b>Destination:</b> {dst_str}
<b>Classification:</b> {escape_html(first_alert.alert.s_cls)}
{protocol_str}
<b>SID:</b> <code>{first_alert.alert.s_id}</code>
"""

    if len(alerts) == 1:
        message += f"<b>Timestamp:</b> {format_datetime(first_alert.alert.ts)}\n"
        if config.alert.force_session_link:
            link_text = "View Session in NAD"
            link_url = first_alert.flow_url
        else:
            link_text = "View All Alerts in NAD"
            link_url = create_group_link(alerts)
    else:
        earliest_ts = min(a.alert.ts for a in alerts if a.alert and a.alert.ts)
        latest_ts = max(a.alert.ts for a in alerts if a.alert and a.alert.ts)
        if earliest_ts == latest_ts:
            message += f"<b>Timestamp:</b> {format_datetime(earliest_ts)}\n"
        else:
            message += f"<b>Timestamp:</b> {format_datetime(earliest_ts)} - {format_datetime(latest_ts)}\n"
        link_text = "View All Alerts in NAD"
        link_url = create_group_link(alerts)

    nad_source_text = f" ({nad_source})" if config.alert.show_nad_source else ""
    message += f"<b>🔍 <a href=\"{link_url}\">{link_text}</a></b>{nad_source_text}"

    return message

def process_alerts(grouped_alerts: Dict[Tuple[int, str], List[Dict]]) -> str:
    valid_alerts = {
        key: [Alert(**alert_data) for alert_data in alerts]
        for key, alerts in grouped_alerts.items()
    }

    if not valid_alerts:
        return "No valid alerts to report."

    total_alerts = sum(len(alerts) for alerts in valid_alerts.values())
    unique_alerts = len(valid_alerts)

    if total_alerts == 1:
        header = "<b>🚨 New Alert:</b>\n\n"
    else:
        header = f"<b>🚨 {total_alerts} New Alerts ({unique_alerts} Unique):</b>\n\n"

    message = header

    for alerts in valid_alerts.values():
        message += format_alert_message(alerts) + "\n\n"

    return message.rstrip()

async def process_incoming_messages(message_queues: MessageQueues):
    while True:
        message = await message_queues.get_from_incoming()
        try:
            alert = Alert.model_validate(message)
            if (alert.alert and alert.alert.s_pr in config.alert.priority_filter and
                not should_ignore_alert(alert.alert) and
                should_process_alert(alert.alert)):
                await message_queues.add_to_buffer(alert.model_dump())
            else:
                logger.debug(f"Alert filtered out: SID {alert.alert.s_id if alert.alert else 'N/A'}, "
                             f"Priority {alert.alert.s_pr if alert.alert else 'N/A'}, "
                             f"Message: {alert.alert.s_msg if alert.alert else 'N/A'}")
        except Exception as e:
            logger.exception(f"Error processing message: {e}")
        finally:
            message_queues.incoming_queue.task_done()

async def check_and_process_buffer(message_queues: MessageQueues):
    while True:
        if await message_queues.should_process_buffer():
            buffer = await message_queues.clear_buffer()
            if buffer:
                message = process_alerts(buffer)
                await message_queues.add_to_outgoing(message)
                logger.info(f"Processed {sum(len(alerts) for alerts in buffer.values())} alerts "
                            f"({len(buffer)} unique) and prepared message for sending")
        await asyncio.sleep(1)
