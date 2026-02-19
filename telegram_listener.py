"""
Telegram Listener Module
Connects to Telegram and listens for trading signals from specified channels/groups.

Uses Telethon (Telegram MTProto API client) to read messages from channels
without requiring a bot account — works with a regular user account.
"""

import logging
import asyncio
from typing import Callable, Optional, List

from telethon import TelegramClient, events
from telethon.tl.types import Channel, Chat, User

logger = logging.getLogger(__name__)


class TelegramListener:
    """
    Listens to Telegram channels/groups for trading signals.

    Uses Telethon with a user account (API ID + Hash + phone number)
    to read messages from channels that the user is a member of.
    """

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        phone: str,
        session_name: str = "signal_bot",
        channel_ids: Optional[List[int]] = None,
        channel_usernames: Optional[List[str]] = None,
    ):
        """
        Initialize Telegram listener.

        Args:
            api_id: Telegram API ID (from my.telegram.org)
            api_hash: Telegram API Hash
            phone: Phone number for login
            session_name: Session file name (stores login state)
            channel_ids: List of channel/group numeric IDs to monitor
            channel_usernames: List of channel/group usernames to monitor
        """
        self.api_id = api_id
        self.api_hash = api_hash
        self.phone = phone
        self.session_name = session_name
        self.channel_ids = channel_ids or []
        self.channel_usernames = channel_usernames or []
        self.client: Optional[TelegramClient] = None
        self._on_signal_callback: Optional[Callable] = None
        self._resolved_entities = {}

    def on_signal(self, callback: Callable):
        """
        Register a callback for when a new signal message is received.

        Args:
            callback: Async function(sender_name: str, message_text: str)
        """
        self._on_signal_callback = callback

    async def start(self):
        """Connect to Telegram and start listening"""
        logger.info("Connecting to Telegram...")

        self.client = TelegramClient(
            self.session_name,
            self.api_id,
            self.api_hash,
        )

        await self.client.start(phone=self.phone)

        # Verify connection
        me = await self.client.get_me()
        logger.info(f"Logged in as: {me.first_name} ({me.phone})")

        # Resolve channel entities
        await self._resolve_channels()

        # Register message handler
        chats = list(self._resolved_entities.values()) or None

        @self.client.on(events.NewMessage(chats=chats))
        async def handler(event):
            await self._handle_message(event)

        logger.info("Telegram listener started. Waiting for signals...")

    async def _resolve_channels(self):
        """Resolve channel usernames/IDs to entities"""
        for username in self.channel_usernames:
            try:
                entity = await self.client.get_entity(username)
                name = getattr(entity, 'title', username)
                self._resolved_entities[name] = entity
                logger.info(f"Monitoring channel: {name} (@{username})")
            except Exception as e:
                logger.error(f"Could not resolve channel @{username}: {e}")

        for channel_id in self.channel_ids:
            try:
                entity = await self.client.get_entity(channel_id)
                name = getattr(entity, 'title', str(channel_id))
                self._resolved_entities[name] = entity
                logger.info(f"Monitoring channel: {name} (ID: {channel_id})")
            except Exception as e:
                logger.error(f"Could not resolve channel ID {channel_id}: {e}")

        if not self._resolved_entities:
            logger.warning(
                "No channels resolved! Will listen to ALL incoming messages. "
                "Set TELEGRAM_CHANNEL_IDS or TELEGRAM_CHANNEL_USERNAMES in config."
            )

    async def _handle_message(self, event):
        """Handle incoming message"""
        message = event.message
        text = message.text or message.message or ""

        if not text.strip():
            return

        # Get sender info
        sender_name = "Unknown"
        chat = await event.get_chat()
        if hasattr(chat, 'title'):
            sender_name = chat.title
        elif hasattr(chat, 'first_name'):
            sender_name = chat.first_name

        logger.debug(f"Message from [{sender_name}]: {text[:100]}...")

        # Forward to callback
        if self._on_signal_callback:
            try:
                await self._on_signal_callback(sender_name, text)
            except Exception as e:
                logger.error(f"Error in signal callback: {e}", exc_info=True)

    async def run_forever(self):
        """Run the listener until disconnected"""
        if not self.client:
            await self.start()

        logger.info("Telegram listener running. Press Ctrl+C to stop.")
        await self.client.run_until_disconnected()

    async def stop(self):
        """Disconnect from Telegram"""
        if self.client:
            await self.client.disconnect()
            logger.info("Telegram listener stopped.")

    async def list_dialogs(self):
        """List all chats/channels the user is part of (helper for setup)"""
        if not self.client:
            await self.start()

        print("\n  Your Telegram Channels/Groups:")
        print("  " + "=" * 50)

        async for dialog in self.client.iter_dialogs():
            entity = dialog.entity
            if isinstance(entity, (Channel, Chat)):
                entity_type = "Channel" if isinstance(entity, Channel) else "Group"
                username = getattr(entity, 'username', None)
                username_str = f" (@{username})" if username else ""
                print(f"  [{entity_type}] {dialog.name}{username_str}")
                print(f"    ID: {dialog.id}")
                print()

        print("  " + "=" * 50)
        print("  Use these IDs in TELEGRAM_CHANNEL_IDS config")
