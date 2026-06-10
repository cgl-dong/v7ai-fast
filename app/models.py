from pydantic import BaseModel
from typing import Optional, Any


class Event(BaseModel):
    topic: str
    nonce: str
    time: int
    encrypted_data: str
    signature: str


class ChatMessage(BaseModel):
    id: Optional[str] = None
    content: Optional[str] = None


class MessageContent(BaseModel):
    text: Optional[dict] = None


class EventData(BaseModel):
    chat: Optional[dict] = None
    message: Optional[dict] = None


class SparkRequest(BaseModel):
    model: str
    temperature: float = 0.7
    messages: list[dict]


class SparkResponse(BaseModel):
    choices: list[dict]


class WoaMessageRequest(BaseModel):
    type: str = "text"
    receiver: dict
    content: dict
