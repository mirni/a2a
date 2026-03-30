"""a2a-messaging: Agent-to-Agent messaging and negotiation.

Provides inter-agent messaging, threaded conversations, price negotiation,
and end-to-end message encryption via X25519 + AES-256-GCM.
"""

from .api import MessagingAPI
from .crypto import MessageCrypto
from .models import EncryptionMetadata, Message, MessageType
from .storage import MessageStorage

__all__ = [
    "EncryptionMetadata",
    "Message",
    "MessageCrypto",
    "MessageStorage",
    "MessageType",
    "MessagingAPI",
]

__version__ = "0.3.0"
