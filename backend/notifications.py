"""
Notification service for DockMon
Handles sending alerts via Discord, Telegram, and Pushover
"""

import asyncio
import base64
import html
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import requests
import httpx
from database import DatabaseManager, NotificationChannel, AlertV2, NotificationRetry, AlertRuleV2
from event_logger import EventSeverity, EventCategory, EventType
from utils.keys import parse_composite_key
from blackout_manager import BlackoutManager
from auth.action_token_auth import generate_action_token

logger = logging.getLogger(__name__)

# V1 dataclasses AlertEvent and DockerEventAlert removed - V2 uses AlertV2 database model

class NotificationService:
    """Handles all notification channels and alert processing"""

    def __init__(self, db: DatabaseManager, event_logger=None):
        self.db = db
        self.event_logger = event_logger
        self.http_client = httpx.AsyncClient(timeout=30.0)

        # Retry queue management
        self._retry_task: Optional[asyncio.Task] = None
        self._retry_running = False

        # Rate limit tracking (channel_id -> retry_after_timestamp)
        self._rate_limited_channels: Dict[str, datetime] = {}

        # Initialize blackout manager
        self.blackout_manager = BlackoutManager(db)

    async def start_retry_loop(self):
        """Start the notification retry background task"""
        if self._retry_running:
            logger.warning("Notification retry loop already running")
            return

        self._retry_running = True
        self._retry_task = asyncio.create_task(self._retry_loop())
        logger.info("Notification retry loop started")

    async def stop_retry_loop(self):
        """Stop the notification retry background task"""
        self._retry_running = False

        if self._retry_task:
            self._retry_task.cancel()
            try:
                await self._retry_task
            except asyncio.CancelledError:
                pass

        logger.info("Notification retry loop stopped")

    def _is_rate_limited(self, channel_type: str) -> bool:
        """
        Check if channel is currently rate-limited

        Args:
            channel_type: Channel type (telegram, discord, slack, etc.)

        Returns:
            True if channel is rate-limited, False otherwise
        """
        if channel_type in self._rate_limited_channels:
            retry_after = self._rate_limited_channels[channel_type]
            if datetime.now(timezone.utc) < retry_after:
                return True
            else:
                # Rate limit expired, remove from dict
                del self._rate_limited_channels[channel_type]
        return False

    def _get_host_name(self, event) -> str:
        """Get host name from event (generic event object with host_id/host_name)"""
        if hasattr(event, 'host_name'):
            return event.host_name
        elif hasattr(event, 'host_id'):
            # Look up host name from host_id in database
            try:
                host = self.db.get_host(event.host_id)
                return host.name if host else 'Unknown Host'
            except Exception:
                return 'Unknown Host'
        else:
            return 'Unknown Host'

    # V1 methods removed: process_docker_event, _send_event_notification, send_alert,
    # _get_matching_rules, _should_send_alert, _send_rule_notifications, _send_to_channel,
    # _get_default_template, _format_message
    # V2 alert system (AlertEngine) handles all alert processing via send_alert_v2()

    async def _send_telegram(self, config: Dict[str, Any], message: str, event=None, action_url: str = '') -> bool:
        """Send notification via Telegram

        Uses HTML parse mode instead of Markdown for better compatibility.
        HTML is more forgiving with special characters in container/host names.

        Args:
            config: Telegram channel configuration
            message: Message text to send
            event: Optional event object (unused, for signature consistency)
            action_url: Optional action URL to include as inline button
        """
        try:
            # Support both 'token' and 'bot_token' for backward compatibility
            token = config.get('token') or config.get('bot_token')
            chat_id = config.get('chat_id')

            if not token or not chat_id:
                logger.error(f"Telegram config missing token or chat_id")
                return False

            url = f"https://api.telegram.org/bot{token}/sendMessage"

            # Escape HTML entities FIRST to prevent malformed HTML errors
            # This prevents issues with container names like <none>, JSON snippets, etc.
            html_message = html.escape(message)

            # Then convert Markdown-style formatting to HTML
            # Most templates use **bold** and `code`, convert these to HTML
            # Replace **bold** with <b>bold</b> (toggle on/off)
            parts = html_message.split('**')
            for i in range(1, len(parts), 2):
                if i < len(parts):
                    parts[i] = f'<b>{parts[i]}</b>'
            html_message = ''.join(parts)

            # Replace `code` with <code>code</code> (toggle on/off)
            parts = html_message.split('`')
            for i in range(1, len(parts), 2):
                if i < len(parts):
                    parts[i] = f'<code>{parts[i]}</code>'
            html_message = ''.join(parts)

            # Build payload - support topic ID format: "-1001234567890/42"
            payload = {
                'text': html_message,
                'parse_mode': 'HTML'
            }

            # Parse chat_id for topic support
            if '/' in str(chat_id):
                # Format: "-1001234567890/42" (channel_id/topic_id)
                channel_id_str, topic_id_str = str(chat_id).split('/', 1)
                try:
                    payload['chat_id'] = int(channel_id_str)
                    payload['message_thread_id'] = int(topic_id_str)
                    logger.debug(f"Sending to Telegram topic: channel={channel_id_str}, topic={topic_id_str}")
                except ValueError:
                    logger.error(f"Invalid Telegram chat_id format: '{chat_id}'. Expected format: '-1001234567890' or '-1001234567890/42' for topics")
                    return False
            else:
                # Regular chat (no topic)
                payload['chat_id'] = chat_id

            # Add inline keyboard button for action URL (v2.2.0+)
            if action_url:
                payload['reply_markup'] = {
                    'inline_keyboard': [[
                        {'text': 'Update Now', 'url': action_url}
                    ]]
                }

            response = await self.http_client.post(url, json=payload)
            response.raise_for_status()

            logger.info("Telegram notification sent successfully")
            return True

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                # Parse Retry-After header (seconds)
                retry_after = int(e.response.headers.get('Retry-After', 60))
                retry_timestamp = datetime.now(timezone.utc) + timedelta(seconds=retry_after)
                self._rate_limited_channels['telegram'] = retry_timestamp
                logger.warning(f"Telegram rate limited, retry after {retry_after}s")
            logger.error(f"Failed to send Telegram notification: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to send Telegram notification: {e}")
            return False

    async def _send_discord(self, config: Dict[str, Any], message: str, event=None, action_url: str = '') -> bool:
        """Send notification via Discord webhook

        Args:
            config: Discord channel configuration
            message: Message text to send
            event: Optional event object (unused, for signature consistency)
            action_url: Optional action URL to include as button
        """
        try:
            webhook_url = config.get('webhook_url')

            if not webhook_url:
                logger.error("Discord config missing webhook_url")
                return False

            # Convert markdown to Discord format
            discord_message = message.replace('`', '`').replace('**', '**')

            # Add action URL as link if provided (Discord webhook buttons require application)
            if action_url:
                discord_message += f"\n\n[Update Now]({action_url})"

            payload = {
                'content': discord_message,
                'username': 'DockMon',
                'avatar_url': 'https://cdn-icons-png.flaticon.com/512/919/919853.png'
            }

            response = await self.http_client.post(webhook_url, json=payload)
            response.raise_for_status()

            logger.info("Discord notification sent successfully")
            return True

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                # Parse Retry-After header (seconds)
                retry_after = int(e.response.headers.get('Retry-After', 60))
                retry_timestamp = datetime.now(timezone.utc) + timedelta(seconds=retry_after)
                self._rate_limited_channels['discord'] = retry_timestamp
                logger.warning(f"Discord rate limited, retry after {retry_after}s")
            logger.error(f"Failed to send Discord notification: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to send Discord notification: {e}")
            return False

    async def _send_pushover(self, config: Dict[str, Any], message: str,
                           event, action_url: str = '') -> bool:
        """Send notification via Pushover

        Args:
            config: Pushover channel configuration (app_token, user_key, url)
            message: Formatted message to send
            event: Alert title string or legacy event object
            action_url: Optional one-click action URL (e.g., for container updates)
        """
        try:
            app_token = config.get('app_token')
            user_key = config.get('user_key')

            if not app_token or not user_key:
                logger.error("Pushover config missing app_token or user_key")
                return False

            # Strip markdown for Pushover
            plain_message = re.sub(r'\*\*(.*?)\*\*', r'\1', message)  # Bold
            plain_message = re.sub(r'`(.*?)`', r'\1', plain_message)   # Code
            plain_message = re.sub(r'🚨', '', plain_message)  # Remove alert emoji

            # Determine priority based on event type
            priority = 0  # Normal
            # Determine priority based on event attributes
            if hasattr(event, 'new_state') and event.new_state in ['exited', 'dead']:
                priority = 1  # High priority for state failures
            elif hasattr(event, 'event_type') and event.event_type in ['die', 'oom', 'kill']:
                priority = 1  # High priority for critical Docker events

            # Handle both event objects (legacy) and strings (Alert v2)
            if isinstance(event, str):
                title = f"DockMon: {event}"
            else:
                title = f"DockMon: {event.container_name}"

            # Use action_url if provided, otherwise fall back to config URL
            url = action_url if action_url else config.get('url', '')
            url_title = 'Update Now' if action_url else 'Open DockMon'

            payload = {
                'token': app_token,
                'user': user_key,
                'message': plain_message,
                'title': title,
                'priority': priority,
                'url': url,
                'url_title': url_title
            }

            response = await self.http_client.post(
                'https://api.pushover.net/1/messages.json',
                data=payload
            )
            response.raise_for_status()

            logger.info("Pushover notification sent successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to send Pushover notification: {e}")
            return False

    async def _send_slack(self, config: Dict[str, Any], message: str, event=None, action_url: str = '') -> bool:
        """Send notification via Slack webhook

        Args:
            config: Slack channel configuration
            message: Message text to send
            event: Optional event object (for color determination)
            action_url: Optional action URL to include as button
        """
        try:
            webhook_url = config.get('webhook_url')

            if not webhook_url:
                logger.error("Slack config missing webhook_url")
                return False

            # Convert markdown to Slack format
            # Slack uses mrkdwn format which is similar to markdown but with some differences
            slack_message = message.replace('**', '*')  # Bold in Slack is single asterisk
            slack_message = slack_message.replace('`', '`')  # Code blocks remain the same

            # Determine color based on event type
            color = "#ff0000"  # Default red for critical
            if event and hasattr(event, 'new_state'):
                if event.new_state == 'running':
                    color = "#00ff00"  # Green for running
                elif event.new_state in ['stopped', 'paused']:
                    color = "#ffaa00"  # Orange for stopped/paused
            elif event and hasattr(event, 'event_type'):
                if event.event_type in ['start', 'unpause']:
                    color = "#00ff00"  # Green for recovery events
                elif event.event_type in ['stop', 'pause']:
                    color = "#ffaa00"  # Orange for controlled stops

            # Create rich Slack message with attachments
            attachment = {
                'color': color,
                'fallback': slack_message,
                'title': '🚨 DockMon Alert',
                'text': slack_message,
                'mrkdwn_in': ['text'],
                'footer': 'DockMon',
                'footer_icon': 'https://raw.githubusercontent.com/docker/compose/v2/logo.png'
            }

            # Add action button if URL provided (v2.2.0+)
            if action_url:
                attachment['actions'] = [{
                    'type': 'button',
                    'text': 'Update Now',
                    'url': action_url,
                    'style': 'primary'
                }]

            # Only include timestamp if event is provided
            if event and hasattr(event, 'timestamp') and event.timestamp:
                attachment['ts'] = int(event.timestamp.timestamp())

            payload = {
                'attachments': [attachment]
            }

            response = await self.http_client.post(webhook_url, json=payload)
            response.raise_for_status()

            logger.info("Slack notification sent successfully")
            return True

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                # Parse Retry-After header (seconds)
                retry_after = int(e.response.headers.get('Retry-After', 60))
                retry_timestamp = datetime.now(timezone.utc) + timedelta(seconds=retry_after)
                self._rate_limited_channels['slack'] = retry_timestamp
                logger.warning(f"Slack rate limited, retry after {retry_after}s")
            logger.error(f"Failed to send Slack notification: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to send Slack notification: {e}")
            return False

    async def _send_gotify(self, config: Dict[str, Any], message: str, event=None, title: str = "DockMon Alert", action_url: str = '') -> bool:
        """Send notification via Gotify

        Args:
            config: Gotify channel configuration
            message: Message text to send
            event: Optional event object (for priority determination)
            title: Notification title
            action_url: Optional action URL (added to message as Gotify doesn't support click actions)
        """
        try:
            # Validate required config fields
            server_url = config.get('server_url', '').strip()
            app_token = config.get('app_token', '').strip()

            if not server_url:
                logger.error("Gotify config missing server_url")
                return False

            if not app_token:
                logger.error("Gotify config missing app_token")
                return False

            # Validate server URL format
            if not server_url.startswith(('http://', 'https://')):
                logger.error(f"Gotify server_url must start with http:// or https://: {server_url}")
                return False

            # Strip markdown formatting for plain text
            plain_message = re.sub(r'\*\*(.*?)\*\*', r'\1', message)
            plain_message = re.sub(r'`(.*?)`', r'\1', plain_message)
            plain_message = re.sub(r'[🚨🔴🟢💀⚠️🏥✅🔄📢]', '', plain_message)  # Remove emojis

            # Add action URL to message (Gotify supports click URL via extras)
            extras = {}
            if action_url:
                extras['client::notification'] = {'click': {'url': action_url}}

            # Determine priority (0-10, default 5)
            priority = 5
            if event and hasattr(event, 'new_state') and event.new_state in ['exited', 'dead']:
                priority = 8  # High priority for critical states
            elif event and hasattr(event, 'event_type') and event.event_type in ['die', 'oom', 'kill']:
                priority = 8  # High priority for critical events

            # Build URL with proper path handling
            base_url = server_url.rstrip('/')
            url = f"{base_url}/message?token={app_token}"

            # Determine title: use event container name if available, otherwise use provided title
            notification_title = f"DockMon: {event.container_name}" if event and hasattr(event, 'container_name') else title

            # Create payload
            payload = {
                'title': notification_title,
                'message': plain_message,
                'priority': priority
            }
            if extras:
                payload['extras'] = extras

            # Send request with timeout
            response = await self.http_client.post(url, json=payload)
            response.raise_for_status()

            logger.info("Gotify notification sent successfully")
            return True

        except httpx.HTTPStatusError as e:
            logger.error(f"Gotify HTTP error {e.response.status_code}: {e}")
            return False
        except httpx.RequestError as e:
            logger.error(f"Gotify connection error: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to send Gotify notification: {e}")
            return False

    async def _send_ntfy(self, config: Dict[str, Any], message: str, event=None, title: str = "DockMon Alert", action_url: str = '') -> bool:
        """Send notification via ntfy (https://ntfy.sh or self-hosted)

        ntfy is a simple HTTP-based pub-sub notification service.
        API docs: https://docs.ntfy.sh/publish/

        Uses JSON API for proper Unicode/emoji support in titles.

        Config fields:
            server_url (required): Base URL (e.g., https://ntfy.sh or https://ntfy.example.com)
            topic (required): The notification topic/channel name
            access_token (optional): Bearer token for authenticated servers
            username (optional): Username for basic auth
            password (optional): Password for basic auth

        Args:
            config: ntfy channel configuration
            message: Message text to send
            event: Optional event object (for priority/tags)
            title: Notification title
            action_url: Optional action URL to include as button
        """
        try:
            # Validate required config fields
            server_url = config.get('server_url', '').strip()
            topic = config.get('topic', '').strip()

            if not server_url:
                logger.error("ntfy config missing server_url")
                return False

            if not topic:
                logger.error("ntfy config missing topic")
                return False

            # Validate server URL format
            if not server_url.startswith(('http://', 'https://')):
                logger.error(f"ntfy server_url must start with http:// or https://: {server_url}")
                return False

            # Determine priority (1-5: min, low, default, high, urgent)
            priority = 3  # default
            if event:
                if hasattr(event, 'new_state') and event.new_state in ['exited', 'dead']:
                    priority = 5  # urgent for critical states
                elif hasattr(event, 'event_type') and event.event_type in ['die', 'oom', 'kill']:
                    priority = 5  # urgent for critical events

            # Determine title
            notification_title = title
            if event and hasattr(event, 'container_name') and event.container_name:
                notification_title = f"DockMon: {event.container_name}"

            # Build JSON payload - handles Unicode/emoji properly (Issue #163)
            # https://docs.ntfy.sh/publish/#publish-as-json
            payload = {
                "topic": topic,
                "title": notification_title,
                "message": message,
                "priority": priority,
                "markdown": True,
            }

            # Add tags for critical events
            if event:
                tags = []
                if hasattr(event, 'event_type'):
                    if event.event_type in ['die', 'oom', 'kill']:
                        tags.append('warning')
                    elif event.event_type in ['start', 'restart']:
                        tags.append('white_check_mark')
                if tags:
                    payload['tags'] = tags

            # Add action button if URL provided
            if action_url:
                payload['actions'] = [
                    {
                        "action": "view",
                        "label": "Update Now",
                        "url": action_url
                    }
                ]

            # Build auth headers (only auth goes in headers, not content)
            headers = {}
            access_token = config.get('access_token', '').strip()
            username = config.get('username', '').strip()
            password = config.get('password', '').strip()

            if access_token:
                headers['Authorization'] = f'Bearer {access_token}'
            elif username and password:
                credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
                headers['Authorization'] = f'Basic {credentials}'

            # Send JSON request to server root (topic is in payload)
            url = server_url.rstrip('/')
            response = await self.http_client.post(url, json=payload, headers=headers)

            response.raise_for_status()

            logger.info("ntfy notification sent successfully")
            return True

        except httpx.HTTPStatusError as e:
            logger.error(f"ntfy HTTP error {e.response.status_code}: {e}")
            return False
        except httpx.RequestError as e:
            logger.error(f"ntfy connection error: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to send ntfy notification: {e}")
            return False

    async def _send_smtp(self, config: Dict[str, Any], message: str, event=None, title: str = "DockMon Alert", action_url: str = '') -> bool:
        """Send notification via SMTP (Email)

        Args:
            config: SMTP channel configuration
            message: Message text to send
            event: Optional event object
            title: Email subject prefix
            action_url: Optional action URL to include as button in email
        """
        try:
            # Import SMTP libraries (only when needed to avoid dependency issues)
            try:
                import aiosmtplib
                from email.mime.text import MIMEText
                from email.mime.multipart import MIMEMultipart
            except ImportError:
                logger.error("SMTP support requires 'aiosmtplib' package. Install with: pip install aiosmtplib")
                return False

            # Validate required config fields
            smtp_host = config.get('smtp_host', '').strip()
            smtp_port = config.get('smtp_port', 587)
            smtp_user = config.get('smtp_user', '').strip()
            smtp_password = config.get('smtp_password', '').strip()
            from_email = config.get('from_email', '').strip()
            to_email = config.get('to_email', '').strip()
            use_tls = config.get('use_tls', True)

            # Validate all required fields
            if not smtp_host:
                logger.error("SMTP config missing smtp_host")
                return False
            if smtp_user and not smtp_password:
                logger.error("SMTP config missing smtp_password (required when smtp_user is set)")
                return False
            if smtp_password and not smtp_user:
                logger.error("SMTP config missing smtp_user (required when smtp_password is set)")
                return False
            if not from_email:
                logger.error("SMTP config missing from_email")
                return False
            if not to_email:
                logger.error("SMTP config missing to_email")
                return False

            # Validate port range
            try:
                smtp_port = int(smtp_port)
                if smtp_port < 1 or smtp_port > 65535:
                    logger.error(f"SMTP port must be between 1-65535: {smtp_port}")
                    return False
            except (ValueError, TypeError):
                logger.error(f"Invalid SMTP port: {smtp_port}")
                return False

            # Validate email format (basic check)
            email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
            if not email_pattern.match(from_email):
                logger.error(f"Invalid from_email format: {from_email}")
                return False
            if not email_pattern.match(to_email):
                logger.error(f"Invalid to_email format: {to_email}")
                return False

            # Determine subject: use event container name if available, otherwise use provided title
            subject = f"DockMon Alert: {event.container_name}" if event and hasattr(event, 'container_name') else title

            # Create multipart email
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = from_email
            msg['To'] = to_email

            # Plain text version (strip markdown and emojis)
            plain_text = re.sub(r'\*\*(.*?)\*\*', r'\1', message)
            plain_text = re.sub(r'`(.*?)`', r'\1', plain_text)
            plain_text = re.sub(r'[🚨🔴🟢💀⚠️🏥✅🔄📢]', '', plain_text)

            # HTML version with basic styling (light theme for better email compatibility)
            html_text = message.replace('\n', '<br>')
            html_text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', html_text)
            html_text = re.sub(r'`(.*?)`', r'<code style="background:#f5f5f5;color:#333;padding:2px 6px;border-radius:3px;font-family:monospace;">\1</code>', html_text)

            # Build action button HTML if URL provided
            action_button_html = ''
            if action_url:
                action_button_html = f'''
        <div style="margin-top:20px;text-align:center;">
            <a href="{action_url}" style="display:inline-block;padding:12px 24px;background:#3b82f6;color:#ffffff;text-decoration:none;border-radius:6px;font-weight:500;font-size:14px;">Update Now</a>
        </div>'''

            html_body = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;background:#f9f9f9;color:#333;">
    <div style="max-width:600px;margin:20px auto;background:#ffffff;padding:24px;border-radius:8px;border:1px solid #e0e0e0;box-shadow:0 1px 3px rgba(0,0,0,0.1);">
        <div style="line-height:1.6;font-size:14px;">
            {html_text}
        </div>{action_button_html}
        <div style="margin-top:20px;padding-top:20px;border-top:1px solid #e0e0e0;font-size:12px;color:#666;">
            Sent by DockMon Container Monitoring
        </div>
    </div>
</body>
</html>"""

            # Attach both versions
            part1 = MIMEText(plain_text, 'plain', 'utf-8')
            part2 = MIMEText(html_body, 'html', 'utf-8')
            msg.attach(part1)
            msg.attach(part2)

            # Send email with proper connection handling
            # Port 587 uses STARTTLS, port 465 uses direct TLS/SSL
            if smtp_port == 587:
                smtp_kwargs = {
                    'hostname': smtp_host,
                    'port': smtp_port,
                    'start_tls': use_tls,  # Use STARTTLS for port 587
                    'timeout': 30
                }
            elif smtp_port == 465:
                smtp_kwargs = {
                    'hostname': smtp_host,
                    'port': smtp_port,
                    'use_tls': use_tls,  # Use direct TLS for port 465
                    'timeout': 30
                }
            else:
                # Other ports (like 25) - no encryption by default unless use_tls is True
                smtp_kwargs = {
                    'hostname': smtp_host,
                    'port': smtp_port,
                    'start_tls': use_tls if use_tls else False,
                    'timeout': 30
                }

            async with aiosmtplib.SMTP(**smtp_kwargs) as smtp:
                if smtp_user and smtp_password:
                    await smtp.login(smtp_user, smtp_password)
                else:
                    logger.debug("SMTP auth skipped - no credentials provided")
                await smtp.send_message(msg)

            logger.info(f"SMTP notification sent successfully to {to_email}")
            return True

        except aiosmtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP authentication failed: {e}")
            return False
        except aiosmtplib.SMTPException as e:
            logger.error(f"SMTP error: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to send SMTP notification: {e}")
            return False

    async def _send_teams(self, config: Dict[str, Any], message: str, event=None, action_url: str = '') -> bool:
        """Send notification via Microsoft Teams webhook

        Teams accepts a simple JSON payload with a 'text' field.
        Note: Microsoft is deprecating Office 365 Connectors, but this still works.

        Args:
            config: Teams channel configuration (webhook_url)
            message: Formatted message to send
            event: Optional event object (unused, for signature consistency)
            action_url: Optional action URL to append to message
        """
        try:
            webhook_url = config.get('webhook_url', '').strip()

            if not webhook_url:
                logger.error("Teams config missing webhook_url")
                return False

            # Validate URL format
            if not webhook_url.startswith(('http://', 'https://')):
                logger.error(f"Teams webhook_url must start with http:// or https://: {webhook_url}")
                return False

            # Teams accepts markdown in the text field
            teams_message = message

            # Append action URL as link if provided
            if action_url:
                teams_message += f"\n\n[Update Now]({action_url})"

            # Teams expects a simple payload with 'text' field
            payload = {"text": teams_message}

            response = await self.http_client.post(webhook_url, json=payload)
            response.raise_for_status()

            logger.info("Teams notification sent successfully")
            return True

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                retry_after = int(e.response.headers.get('Retry-After', 60))
                retry_timestamp = datetime.now(timezone.utc) + timedelta(seconds=retry_after)
                self._rate_limited_channels['teams'] = retry_timestamp
                logger.warning(f"Teams rate limited, retry after {retry_after}s")
            logger.error(f"Failed to send Teams notification: {e}")
            return False
        except httpx.RequestError as e:
            logger.error(f"Teams connection error: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to send Teams notification: {e}")
            return False

    async def _send_webhook(self, config: Dict[str, Any], message: str, event=None, title: str = "DockMon Alert", action_url: str = '') -> bool:
        """Send notification via webhook (HTTP POST/PUT)

        Allows users to integrate DockMon alerts with any custom endpoint or service.
        Supports JSON and form-encoded payloads, custom HTTP headers, and configurable methods.

        Args:
            config: Webhook configuration
                - url (required): Webhook endpoint URL
                - method (optional): HTTP method (POST/PUT, default: POST)
                - headers (optional): Custom HTTP headers dict
                - payload_format (optional): "json" or "form" (default: json)
            message: Formatted alert message (supports markdown)
            event: Optional event object (for additional context)
            title: Alert title (default: "DockMon Alert")
            action_url: Optional action URL to include in payload

        Returns:
            True if webhook delivered successfully (2xx response)
            False if delivery failed (triggers retry queue)

        Config Example:
            {
                "url": "https://my-service.com/alerts",
                "method": "POST",
                "headers": {
                    "Authorization": "Bearer token",
                    "X-Custom-Header": "value"
                },
                "payload_format": "json"
            }
        """
        try:
            # Validate required config
            url = config.get('url', '').strip()
            if not url:
                logger.error("Webhook config missing url")
                return False

            # Validate URL format (basic check)
            if not url.startswith(('http://', 'https://')):
                logger.error(f"Webhook URL must start with http:// or https://: {url}")
                return False

            # Get optional config with defaults
            method = config.get('method', 'POST').upper()
            headers = config.get('headers', {})
            payload_format = config.get('payload_format', 'json')

            # Build payload with structured data for easy parsing
            payload = {
                'title': title,
                'message': message,
                'timestamp': datetime.now(timezone.utc).isoformat() + 'Z'
            }

            # Add structured event context if available (v2.2.8+)
            # This provides machine-readable fields so receivers don't need to parse message text
            if event:
                # Extract standard fields using getattr for cleaner code
                for attr, key in [('container_name', 'container'), ('host_name', 'host'), ('host_id', 'host_id')]:
                    if value := getattr(event, attr, None):
                        payload[key] = value

                # Include rich context data (versions, digests, etc.) from alert events
                if context_json := getattr(event, 'event_context_json', None):
                    try:
                        payload['context'] = json.loads(context_json)
                    except (json.JSONDecodeError, TypeError):
                        pass

            # Add action URL if provided (v2.2.0+)
            if action_url:
                payload['action_url'] = action_url

            # Send request based on payload format
            if payload_format == 'json':
                response = await self.http_client.request(
                    method,
                    url,
                    json=payload,
                    headers=headers
                )
            else:  # form-encoded
                response = await self.http_client.request(
                    method,
                    url,
                    data=payload,
                    headers=headers
                )

            # Check for success (2xx status codes)
            response.raise_for_status()

            logger.info(f"Webhook notification sent successfully to {url}")
            return True

        except httpx.HTTPStatusError as e:
            logger.error(f"Webhook HTTP error {e.response.status_code}: {e}")
            return False
        except httpx.TimeoutException as e:
            logger.error(f"Webhook timeout: {e}")
            return False
        except httpx.ConnectError as e:
            logger.error(f"Webhook connection error: {e}")
            return False
        except httpx.RequestError as e:
            logger.error(f"Webhook request error: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to send webhook notification: {e}")
            return False

    # V1 methods test_channel() and process_suppressed_alerts() removed
    # Blackout window suppression now handled by AlertEngine in V2

    async def test_channel(self, channel_id: int) -> dict:
        """
        Test a notification channel by sending a test message

        Args:
            channel_id: ID of the notification channel to test

        Returns:
            dict with 'success' and optional 'error' keys
        """
        try:
            # Get the channel and extract data BEFORE async operations
            channel_type = None
            channel_config = None

            with self.db.get_session() as session:
                channel = session.query(NotificationChannel).filter_by(id=channel_id).first()
                if not channel:
                    return {"success": False, "error": f"Channel {channel_id} not found"}

                # Extract channel data while session is open
                channel_type = channel.type
                channel_config = channel.config

            # Session is now closed - safe for async notification sends
            # Create a test message
            test_message = "🧪 **DockMon Test Notification**\n\nThis is a test message from DockMon to verify your notification channel is configured correctly."

            # Create a mock event object for the send methods
            class TestEvent:
                container_name = "test-container"
                host_name = "test-host"
                timestamp = datetime.now(timezone.utc)
                new_state = "running"
                event_type = "test"

            test_event = TestEvent()

            # Send based on channel type
            success = False
            if channel_type == 'pushover':
                success = await self._send_pushover(channel_config, test_message, test_event)
            elif channel_type == 'telegram':
                success = await self._send_telegram(channel_config, test_message, test_event)
            elif channel_type == 'discord':
                success = await self._send_discord(channel_config, test_message, test_event)
            elif channel_type == 'slack':
                success = await self._send_slack(channel_config, test_message, test_event)
            elif channel_type == 'gotify':
                success = await self._send_gotify(channel_config, test_message, test_event)
            elif channel_type == 'ntfy':
                success = await self._send_ntfy(channel_config, test_message, test_event)
            elif channel_type == 'smtp':
                success = await self._send_smtp(channel_config, test_message, test_event)
            elif channel_type == 'webhook':
                success = await self._send_webhook(channel_config, test_message, test_event)
            elif channel_type == 'teams':
                success = await self._send_teams(channel_config, test_message, test_event)
            else:
                return {"success": False, "error": f"Unsupported channel type: {channel_type}"}

            if success:
                return {"success": True}
            else:
                return {"success": False, "error": "Failed to send test message (check logs for details)"}

        except Exception as e:
            logger.error(f"Error testing channel {channel_id}: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def send_alert_v2(self, alert, rule=None) -> bool:
        """
        Send notifications for Alert System v2

        Uses commitment point pattern to prevent duplicate notifications:
        - operation_committed flag tracks if notifications were successfully sent
        - Database updates happen AFTER notifications (commitment point)
        - If DB fails after notifications sent, we don't retry (users already notified)

        Args:
            alert: AlertV2 database object
            rule: Optional AlertRuleV2 object (if not provided, will be fetched)

        Returns:
            True if notification sent successfully to at least one channel
        """
        logger.info(f"send_alert_v2 START: alert.id={alert.id if alert else 'None'}, rule={rule.name if rule else 'None'}")

        operation_committed = False  # Track if notifications were sent successfully

        try:
            # Prevent duplicate notifications within 5 seconds (Docker sends kill/stop/die almost simultaneously)
            # This protects against rapid-fire notifications from the same event
            if hasattr(alert, 'notified_at') and alert.notified_at:
                time_since_notified = datetime.now(timezone.utc) - alert.notified_at.replace(tzinfo=timezone.utc if not alert.notified_at.tzinfo else None)
                if time_since_notified.total_seconds() < 5:
                    logger.info(f"Skipping duplicate notification for alert {alert.id} ({alert.title}) - last notified {time_since_notified.total_seconds():.1f}s ago")
                    return False

            # Get the rule if not provided
            if rule is None and alert.rule_id:
                rule = self.db.get_alert_rule_v2(alert.rule_id)

            if not rule:
                logger.warning(f"No rule found for alert {alert.id}, cannot send notification")
                return False

            # Parse notification channels from rule
            try:
                channel_ids = json.loads(rule.notify_channels_json) if rule.notify_channels_json else []
            except (json.JSONDecodeError, TypeError):
                logger.warning(f"Invalid notify_channels_json for rule {rule.id}")
                return False

            if not channel_ids:
                logger.warning(f"No notification channels configured for rule {rule.name} - notifications will not be sent")
                return False

            # Check blackout window
            is_blackout, window_name = self.blackout_manager.is_in_blackout_window()
            if is_blackout:
                logger.info(f"Suppressed alert '{alert.title}' during blackout window '{window_name}' - will re-evaluate when blackout ends")

                # Mark alert as suppressed (prevents retry loop)
                # Alert will be re-evaluated when blackout ends
                with self.db.get_session() as session:
                    alert_to_suppress = session.query(AlertV2).filter(AlertV2.id == alert.id).first()
                    if alert_to_suppress:
                        alert_to_suppress.suppressed_by_blackout = True
                        # Keep notified_at as NULL so it can be sent when blackout ends
                        session.commit()
                        logger.info(f"Marked alert {alert.id} as suppressed - condition will be verified when blackout window ends")

                return False

            # Get enabled channels
            channels = self.db.get_notification_channels(enabled_only=True)
            # Support both ID-based (integers) and type-based (strings like "discord") lookup
            channel_map_by_id = {ch.id: ch for ch in channels}
            channel_map_by_type = {ch.type: ch for ch in channels}

            success_count = 0
            total_channels = len(channel_ids)

            # Determine which template to use (priority: custom > category > global)
            template = self._get_template_for_alert_v2(alert, rule)

            # Get settings for action URL generation
            settings = self.db.get_settings()

            # Generate action URL for update_available alerts (v2.2.0+)
            # Priority: database value > env var
            from config.settings import AppConfig
            external_url = (settings.external_url if settings else None) or AppConfig.EXTERNAL_URL
            action_url = ''
            if alert.kind == 'update_available' and external_url:
                try:
                    # Extract host_id and container_id from scope_id
                    if alert.scope_type == 'container' and alert.scope_id:
                        host_id, container_id = parse_composite_key(alert.scope_id)

                        # Parse event_context for image info
                        current_image = ''
                        new_image = ''
                        if hasattr(alert, 'event_context_json') and alert.event_context_json:
                            try:
                                event_ctx = json.loads(alert.event_context_json)
                                current_image = event_ctx.get('current_image', '')
                                new_image = event_ctx.get('latest_image', '')
                            except json.JSONDecodeError:
                                pass

                        # Generate one-time action token
                        plaintext_token, _ = generate_action_token(
                            db=self.db,
                            action_type='container_update',
                            action_params={
                                'host_id': host_id,
                                'container_id': container_id,
                                'container_name': alert.container_name,
                                'host_name': alert.host_name,
                                'current_image': current_image,
                                'new_image': new_image
                            }
                        )

                        # Build action URL
                        base_url = external_url.rstrip('/')
                        action_url = f"{base_url}/quick-action?token={plaintext_token}"
                        logger.debug(f"Generated action URL for update_available alert {alert.id}")
                except Exception as e:
                    logger.warning(f"Failed to generate action URL for alert {alert.id}: {e}")

            # Format the message with alert variables
            message = self._format_message_v2(alert, rule, template, action_url=action_url)

            # Send to each configured channel
            for channel_id in channel_ids:
                # Try to find channel by ID first (integer), then by type (string)
                channel = None
                if isinstance(channel_id, int) and channel_id in channel_map_by_id:
                    channel = channel_map_by_id[channel_id]
                elif isinstance(channel_id, str) and channel_id in channel_map_by_type:
                    channel = channel_map_by_type[channel_id]
                else:
                    logger.warning(f"Notification channel '{channel_id}' not found or not enabled")
                    continue

                if channel:
                    # Check if channel is rate-limited
                    if self._is_rate_limited(channel.type):
                        logger.warning(f"Skipping {channel.type} - currently rate limited")
                        continue

                    try:
                        if channel.type == "telegram":
                            if await self._send_telegram(channel.config, message, action_url=action_url):
                                success_count += 1
                        elif channel.type == "discord":
                            if await self._send_discord(channel.config, message, action_url=action_url):
                                success_count += 1
                        elif channel.type == "slack":
                            if await self._send_slack(channel.config, message, action_url=action_url):
                                success_count += 1
                        elif channel.type == "pushover":
                            if await self._send_pushover(channel.config, message, alert.title, action_url=action_url):
                                success_count += 1
                        elif channel.type == "gotify":
                            if await self._send_gotify(channel.config, message, title=alert.title, action_url=action_url):
                                success_count += 1
                        elif channel.type == "ntfy":
                            if await self._send_ntfy(channel.config, message, title=alert.title, action_url=action_url):
                                success_count += 1
                        elif channel.type == "smtp":
                            if await self._send_smtp(channel.config, message, title=alert.title, action_url=action_url):
                                success_count += 1
                        elif channel.type == "webhook":
                            if await self._send_webhook(channel.config, message, event=alert, title=alert.title, action_url=action_url):
                                success_count += 1
                        elif channel.type == "teams":
                            if await self._send_teams(channel.config, message, action_url=action_url):
                                success_count += 1
                        else:
                            logger.warning(f"Unknown channel type '{channel.type}' for channel {channel.name}")
                    except Exception as e:
                        logger.error(f"Failed to send alert to channel {channel.name}: {e}")

            # Mark operation as committed if any notification succeeded
            if success_count > 0:
                operation_committed = True
                logger.info(f"Notifications sent successfully ({success_count} channels) - marking committed")

            # If all channels failed, queue for retry
            if success_count == 0 and total_channels > 0:
                self._queue_retry(alert.id, rule.id if rule else None, channel_ids, "All channels failed")

            # Update database (commitment point) - only if notifications were sent
            if operation_committed:
                with self.db.get_session() as session:
                    alert_to_update = session.query(AlertV2).filter(AlertV2.id == alert.id).first()
                    if alert_to_update:
                        alert_to_update.notified_at = datetime.now(timezone.utc)
                        alert_to_update.notification_count = (alert_to_update.notification_count or 0) + 1

                        # Auto-resolve alert if rule has auto_resolve enabled
                        if rule and rule.auto_resolve:
                            alert_to_update.state = 'resolved'
                            alert_to_update.resolved_at = datetime.now(timezone.utc)
                            logger.info(f"Auto-resolved alert '{alert.title}' after notification (rule has auto_resolve=True)")

                        session.commit()

            logger.info(f"Alert '{alert.title}' sent to {success_count}/{total_channels} channels")
            return operation_committed

        except Exception as e:
            if operation_committed:
                # Notifications already sent - don't rollback, just log error
                logger.error(f"Notifications sent but database update failed: {e}", exc_info=True)
                return True  # Consider it successful since notifications sent
            else:
                # Notifications not sent yet - safe to fail
                logger.error(f"Error sending alert v2 notification: {e}", exc_info=True)
                return False

    def _get_template_for_alert_v2(self, alert, rule):
        """Get the appropriate template for v2 alert based on priority"""
        # Priority 1: Custom template on the rule
        if rule.custom_template:
            return rule.custom_template

        # Priority 2: Category-specific template based on alert kind
        settings = self.db.get_settings()
        if settings:
            # Check if it's a metric alert
            if rule.metric and settings.alert_template_metric:
                return settings.alert_template_metric
            # Check if it's a state change alert
            elif rule.kind in ['container_stopped', 'container_restart', 'container_restarted'] and settings.alert_template_state_change:
                return settings.alert_template_state_change
            # Check if it's a health alert
            elif rule.kind in ['container_unhealthy', 'host_unhealthy', 'health_check_failed'] and settings.alert_template_health:
                return settings.alert_template_health
            # Check if it's an update alert
            elif rule.kind in ['update_completed', 'update_available', 'update_failed'] and settings.alert_template_update:
                return settings.alert_template_update
            # Priority 3: Global default template
            elif settings.alert_template:
                return settings.alert_template

        # Fallback: Built-in default template (kind-specific)
        return self._get_default_template_v2(rule.kind)

    def _get_default_template_v2(self, kind=None):
        """Get built-in default template for v2 alerts - with kind-specific fallbacks"""
        # Update alerts get a specialized template
        if kind in ['update_available', 'update_completed', 'update_failed']:
            return """🔄 **Container Update - {UPDATE_STATUS}**

**Container:** `{CONTAINER_NAME}`
**Host:** {HOST_NAME}
**Image:** {CURRENT_IMAGE}
**Current Digest:** {CURRENT_DIGEST}
**Latest Digest:** {LATEST_DIGEST}
**Changelog:** {CHANGELOG_URL}
**Time:** {TIMESTAMP}
**Rule:** {RULE_NAME}"""

        # Health check alerts (Docker native HEALTHCHECK and HTTP/HTTPS checks)
        if kind in ['container_unhealthy', 'container_healthy', 'health_check_failed']:
            return """🏥 **{SEVERITY} Alert: Health Check Failed**

**Container:** {CONTAINER_NAME}
**Host:** {HOST_NAME}
**Status:** {OLD_STATE} → {NEW_STATE}
{HEALTH_CHECK_URL}{ERROR_MESSAGE}{CONSECUTIVE_FAILURES}{RESPONSE_TIME}
**Time:** {TIMESTAMP}
**Rule:** {RULE_NAME}"""

        # State change alerts (stopped, started, paused, restarted, died, killed)
        if kind in ['container_stopped', 'container_started', 'container_paused', 'container_restart', 'container_restarted',
                    'container_died', 'container_killed']:
            return """🚨 **{SEVERITY} Alert: {KIND}**

**Container:** {CONTAINER_NAME}
**Host:** {HOST_NAME}
**State change:** {OLD_STATE} to {NEW_STATE}
**Exit code:** {EXIT_CODE}
**Time:** {TIMESTAMP}
**Rule:** {RULE_NAME}"""

        # Metric alerts (cpu, memory, disk, network, etc.)
        if kind in ['cpu_high', 'memory_high', 'disk_high', 'disk_low', 'network_high', 'cpu_low', 'memory_low']:
            return """🚨 **{SEVERITY} Alert: {KIND}**

**Container:** {CONTAINER_NAME}
**Host:** {HOST_NAME}
**Current Value:** {CURRENT_VALUE} (threshold: {THRESHOLD})
**Time:** {TIMESTAMP}
**Rule:** {RULE_NAME}"""

        # Generic fallback for all other alerts
        return """🚨 **{SEVERITY} Alert: {KIND}**

**{TITLE}**
{MESSAGE}

**Host:** {HOST_NAME}
**Current Value:** {CURRENT_VALUE} (threshold: {THRESHOLD})
**Time:** {TIMESTAMP}
**Rule:** {RULE_NAME}"""

    def _get_update_status(self, kind: str) -> str:
        """Map alert kind to human-readable update status"""
        status_map = {
            'update_available': 'Available',
            'update_completed': 'Succeeded',
            'update_failed': 'Failed',
        }
        return status_map.get(kind, '')

    def _format_exit_code(self, exit_code: int) -> str:
        """Format exit code to human-readable string"""
        try:
            code = int(exit_code)
            if code == 0:
                return "0 (Clean exit)"
            elif code == 137:
                return "137 (SIGKILL - Force killed / OOM)"
            elif code == 143:
                return "143 (SIGTERM - Graceful stop)"
            elif code == 130:
                return "130 (SIGINT - Interrupted)"
            elif code == 126:
                return "126 (Command cannot execute)"
            elif code == 127:
                return "127 (Command not found)"
            elif code == 128:
                return "128 (Invalid exit code)"
            elif 129 <= code <= 255:
                # Signal = code - 128
                signal = code - 128
                return f"{code} (Signal {signal})"
            elif 1 <= code <= 127:
                return f"{code} (Application error)"
            else:
                return str(code)
        except (ValueError, TypeError):
            return str(exit_code) if exit_code is not None else ''

    def _format_message_v2(self, alert, rule, template, action_url: str = ''):
        """Format message for v2 alert with variable substitution

        Args:
            alert: AlertV2 database object
            rule: AlertRuleV2 database object
            template: Message template string
            action_url: Optional URL for one-click action (e.g., update container)
        """
        # Get timezone offset from settings
        settings = self.db.get_settings()
        tz_offset_minutes = settings.timezone_offset if settings else 0

        # Create timezone object from offset
        local_tz = timezone(timedelta(minutes=tz_offset_minutes))

        # Convert UTC timestamps to local time
        first_seen_local = alert.first_seen.replace(tzinfo=timezone.utc).astimezone(local_tz) if alert.first_seen else datetime.now(timezone.utc)
        last_seen_local = alert.last_seen.replace(tzinfo=timezone.utc).astimezone(local_tz) if alert.last_seen else datetime.now(timezone.utc)

        # Build variable substitution map
        # Extract short container ID from composite scope_id
        if alert.scope_type == 'container' and alert.scope_id:
            try:
                _, container_id_short = parse_composite_key(alert.scope_id)
            except (ValueError, AttributeError):
                # Fallback if parsing fails (shouldn't happen with valid data)
                container_id_short = 'N/A'
        else:
            container_id_short = 'N/A'

        # For host-scoped alerts without host_name, extract from title (e.g., "Host Offline - Integration Test Host")
        host_name = alert.host_name
        if not host_name and alert.scope_type == 'host' and alert.title:
            # Try to extract from title format "Rule Name - Host Name"
            if ' - ' in alert.title:
                host_name = alert.title.split(' - ', 1)[1]

        variables = {
            # Basic entity info
            '{CONTAINER_NAME}': alert.container_name or 'N/A',
            '{CONTAINER_ID}': container_id_short,
            '{HOST_NAME}': host_name or 'N/A',
            '{HOST_ID}': alert.scope_id if alert.scope_type == 'host' else 'N/A',

            # Alert info
            '{SEVERITY}': alert.severity.upper(),
            '{KIND}': alert.kind,
            '{TITLE}': alert.title,
            '{MESSAGE}': alert.message,
            '{SCOPE_TYPE}': alert.scope_type.capitalize(),
            '{SCOPE_ID}': alert.scope_id,
            '{STATE}': alert.state,

            # Temporal info
            '{FIRST_SEEN}': first_seen_local.strftime('%Y-%m-%d %H:%M:%S'),
            '{LAST_SEEN}': last_seen_local.strftime('%Y-%m-%d %H:%M:%S'),
            '{TIMESTAMP}': last_seen_local.strftime('%Y-%m-%d %H:%M:%S'),
            '{TIME}': last_seen_local.strftime('%H:%M:%S'),
            '{DATE}': last_seen_local.strftime('%Y-%m-%d'),

            # Rule context
            '{RULE_NAME}': rule.name if rule else 'N/A',
            '{RULE_ID}': alert.rule_id or 'N/A',

            # Metrics (for metric-driven alerts)
            '{CURRENT_VALUE}': str(alert.current_value) if alert.current_value is not None else 'N/A',
            '{THRESHOLD}': str(alert.threshold) if alert.threshold is not None else 'N/A',

            # Update status (for update alerts)
            '{UPDATE_STATUS}': self._get_update_status(alert.kind),

            # Initialize state change variables (will be overridden if event_context_json exists)
            '{OLD_STATE}': '',
            '{NEW_STATE}': '',
            '{EXIT_CODE}': '',
            '{IMAGE}': '',
            '{EVENT_TYPE}': '',
            '{TRIGGERED_BY}': 'system',

            # Initialize update variables (will be overridden if event_context_json exists)
            '{CURRENT_IMAGE}': '',
            '{LATEST_IMAGE}': '',
            '{CURRENT_DIGEST}': '',
            '{LATEST_DIGEST}': '',
            '{PREVIOUS_IMAGE}': '',
            '{NEW_IMAGE}': '',
            '{ERROR_MESSAGE}': '',
            '{CHANGELOG_URL}': '',

            # Initialize health check variables (will be overridden if event_context_json exists)
            '{HEALTH_CHECK_URL}': '',
            '{CONSECUTIVE_FAILURES}': '',
            '{FAILURE_THRESHOLD}': '',
            '{RESPONSE_TIME}': '',

            # Action URL for notification links (v2.2.0+)
            '{ACTION_URL}': action_url if action_url else '',
        }

        # Optional labels
        if alert.labels_json:
            try:
                labels = json.loads(alert.labels_json)
                labels_str = ', '.join([f'{k}={v}' for k, v in labels.items()])
                variables['{LABELS}'] = labels_str
            except (json.JSONDecodeError, TypeError, AttributeError, KeyError):
                variables['{LABELS}'] = ''
        else:
            variables['{LABELS}'] = ''

        # Event-specific context (for state change and health check alerts)
        if hasattr(alert, 'event_context_json') and alert.event_context_json:
            try:
                event_context = json.loads(alert.event_context_json)

                # State transition info
                variables['{OLD_STATE}'] = event_context.get('old_state', '') or ''
                variables['{NEW_STATE}'] = event_context.get('new_state', '') or ''

                # Translate exit code to human-readable format
                exit_code = event_context.get('exit_code')
                if exit_code is not None:
                    exit_code_display = self._format_exit_code(exit_code)
                    variables['{EXIT_CODE}'] = exit_code_display
                else:
                    variables['{EXIT_CODE}'] = ''

                variables['{IMAGE}'] = event_context.get('image', '') or ''
                variables['{EVENT_TYPE}'] = event_context.get('event_type', '') or ''
                variables['{TRIGGERED_BY}'] = event_context.get('triggered_by', 'system') or 'system'

                # Container update variables
                # For update_available: current_image, latest_image, latest_digest, versions
                variables['{CURRENT_IMAGE}'] = event_context.get('current_image', '') or ''
                variables['{LATEST_IMAGE}'] = event_context.get('latest_image', '') or ''
                variables['{CURRENT_DIGEST}'] = event_context.get('current_digest', '') or ''
                variables['{LATEST_DIGEST}'] = event_context.get('latest_digest', '') or ''
                variables['{CURRENT_VERSION}'] = event_context.get('current_version', '') or ''
                variables['{LATEST_VERSION}'] = event_context.get('latest_version', '') or ''

                # For update_completed: previous_image, new_image
                # Map to CURRENT/LATEST for template consistency
                previous_img = event_context.get('previous_image', '') or ''
                new_img = event_context.get('new_image', '') or ''
                if previous_img and not variables['{CURRENT_IMAGE}']:
                    variables['{CURRENT_IMAGE}'] = previous_img
                if new_img and not variables['{LATEST_IMAGE}']:
                    variables['{LATEST_IMAGE}'] = new_img

                variables['{PREVIOUS_IMAGE}'] = previous_img
                variables['{NEW_IMAGE}'] = new_img

                # Changelog URL (v2.0.1+)
                changelog_url = event_context.get('changelog_url', '') or ''
                variables['{CHANGELOG_URL}'] = changelog_url if changelog_url else 'Not found'

                # Format error message with conditional display
                error_message = event_context.get('error_message', '') or ''
                if error_message:
                    variables['{ERROR_MESSAGE}'] = f"**Error:** {error_message}\n"
                else:
                    variables['{ERROR_MESSAGE}'] = ''

                # Health check specific variables
                health_check_url = event_context.get('health_check_url', '') or ''
                if health_check_url:
                    variables['{HEALTH_CHECK_URL}'] = f"**URL:** {health_check_url}\n"
                else:
                    variables['{HEALTH_CHECK_URL}'] = ''

                consecutive_failures = event_context.get('consecutive_failures')
                failure_threshold = event_context.get('failure_threshold')
                if consecutive_failures is not None and failure_threshold is not None:
                    variables['{CONSECUTIVE_FAILURES}'] = f"**Failures:** {consecutive_failures}/{failure_threshold} consecutive\n"
                else:
                    variables['{CONSECUTIVE_FAILURES}'] = ''

                variables['{FAILURE_THRESHOLD}'] = str(failure_threshold) if failure_threshold is not None else ''

                # Format response time with conditional display
                response_time = event_context.get('response_time_ms')
                if response_time is not None:
                    variables['{RESPONSE_TIME}'] = f"**Response Time:** {response_time}ms\n"
                else:
                    variables['{RESPONSE_TIME}'] = ''

                # Also check attributes for additional info if not directly available
                if not variables['{IMAGE}'] and 'attributes' in event_context:
                    attributes = event_context.get('attributes', {})
                    variables['{IMAGE}'] = attributes.get('image', '') or ''
            except Exception as e:
                logger.debug(f"Error parsing event context: {e}")

        # Replace all variables in template
        message = template
        for var, value in variables.items():
            message = message.replace(var, value)

        # Clean up any unused variables
        message = re.sub(r'\{[A-Z_]+\}', '', message)

        return message

    def _queue_retry(self, alert_id: str, rule_id: Optional[str], channel_ids: List, error_message: str):
        """
        Add failed notification to retry queue

        Args:
            alert_id: AlertV2 ID
            rule_id: AlertRuleV2 ID (optional)
            channel_ids: List of channel IDs that failed
            error_message: Error message from failure
        """
        try:
            with self.db.get_session() as session:
                # Check if retry already exists for this alert
                existing = session.query(NotificationRetry).filter(
                    NotificationRetry.alert_id == alert_id
                ).first()

                if existing:
                    # Update existing retry
                    existing.attempt_count = 0  # Reset attempt count for new failure
                    existing.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=60)
                    existing.error_message = error_message
                    logger.info(f"Updated existing retry entry for alert {alert_id}")
                else:
                    # Create new retry entry
                    retry = NotificationRetry(
                        alert_id=alert_id,
                        rule_id=rule_id,
                        attempt_count=0,
                        next_retry_at=datetime.now(timezone.utc) + timedelta(seconds=60),  # Retry in 1 minute
                        channel_ids_json=json.dumps(channel_ids),
                        error_message=error_message
                    )
                    session.add(retry)
                    logger.info(f"Queued notification retry for alert {alert_id}")

                session.commit()

        except Exception as e:
            logger.error(f"Failed to queue retry for alert {alert_id}: {e}", exc_info=True)

    async def _retry_loop(self):
        """Process retry queue every 60 seconds"""
        while self._retry_running:
            try:
                await self._process_retry_queue()
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in retry loop: {e}", exc_info=True)
                await asyncio.sleep(60)

    async def _process_retry_queue(self):
        """
        Retry failed notifications with exponential backoff

        Backoff schedule: [60s, 300s, 900s, 3600s, 21600s] (1m, 5m, 15m, 1h, 6h)
        Max 5 retries, then log permanent failure
        """
        try:
            # Exponential backoff schedule (in seconds)
            backoff_schedule = [60, 300, 900, 3600, 21600]  # 1m, 5m, 15m, 1h, 6h
            max_retries = 5

            # Extract retry data and close session BEFORE async operations
            retries_to_process = []
            with self.db.get_session() as session:
                now = datetime.now(timezone.utc)
                retries = session.query(NotificationRetry).filter(
                    NotificationRetry.next_retry_at <= now
                ).all()

                for retry in retries:
                    # Get alert and rule while session is open
                    alert = session.query(AlertV2).filter(AlertV2.id == retry.alert_id).first()
                    rule = None
                    if retry.rule_id:
                        rule = session.query(AlertRuleV2).filter(AlertRuleV2.id == retry.rule_id).first()

                    if alert:
                        try:
                            channel_ids = json.loads(retry.channel_ids_json)
                        except (json.JSONDecodeError, TypeError):
                            channel_ids = []

                        retries_to_process.append({
                            'retry_id': retry.id,
                            'alert': alert,
                            'rule': rule,
                            'channel_ids': channel_ids,
                            'attempt_count': retry.attempt_count
                        })

            # Session closed - safe for async notification sends
            for retry_data in retries_to_process:
                try:
                    # Attempt to send notification
                    success = await self.send_alert_v2(retry_data['alert'], retry_data['rule'])

                    with self.db.get_session() as session:
                        retry_entry = session.query(NotificationRetry).filter(
                            NotificationRetry.id == retry_data['retry_id']
                        ).first()

                        if not retry_entry:
                            continue

                        if success:
                            # Success - delete from queue
                            session.delete(retry_entry)
                            logger.info(f"Retry succeeded for alert {retry_data['alert'].id}, removed from queue")
                        else:
                            # Failed - increment attempt count
                            retry_entry.attempt_count += 1
                            retry_entry.last_attempt_at = datetime.now(timezone.utc)

                            if retry_entry.attempt_count >= max_retries:
                                # Max retries reached - delete and log permanent failure
                                session.delete(retry_entry)
                                logger.error(
                                    f"Permanent failure for alert {retry_data['alert'].id} "
                                    f"after {max_retries} attempts, removed from queue"
                                )
                            else:
                                # Calculate next retry time with exponential backoff
                                backoff_index = min(retry_entry.attempt_count, len(backoff_schedule) - 1)
                                backoff_seconds = backoff_schedule[backoff_index]
                                retry_entry.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)
                                logger.info(
                                    f"Retry {retry_entry.attempt_count}/{max_retries} failed for alert {retry_data['alert'].id}, "
                                    f"next attempt in {backoff_seconds}s"
                                )

                        session.commit()

                except Exception as e:
                    logger.error(f"Error processing retry for alert {retry_data['alert'].id}: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Error processing retry queue: {e}", exc_info=True)

    async def close(self):
        """Clean up resources"""
        await self.stop_retry_loop()
        await self.http_client.aclose()

    async def __aenter__(self):
        """Context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensure cleanup"""
        await self.close()
        return False

# V1 AlertProcessor class removed - V2 uses AlertEngine for state change monitoring