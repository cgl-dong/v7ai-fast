"""Pydantic schemas for request and response models."""
from pydantic import BaseModel
from typing import Optional


class EventSchema(BaseModel):
    topic: str
    nonce: str
    time: int
    encrypted_data: str
    signature: str


class MessageContentSchema(BaseModel):
    text: Optional[dict] = None


class EventDataSchema(BaseModel):
    chat: Optional[dict] = None
    message: Optional[dict] = None


class ChatCompletionRequest(BaseModel):
    model: str
    temperature: float = 0.7
    messages: list[dict]


class WoaMessageRequest(BaseModel):
    type: str = "text"
    receiver: dict
    content: dict
