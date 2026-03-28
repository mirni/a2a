"""a2a-messaging: Agent-to-Agent messaging and negotiation.

Provides inter-agent messaging, threaded conversations, and price negotiation.
"""

from .api import MessagingAPI
from .models import Message, MessageType
from .storage import MessageStorage

__all__ = [
    "Message",
    "MessageStorage",
    "MessageType",
    "MessagingAPI",
]

__version__ = "0.2.0"
