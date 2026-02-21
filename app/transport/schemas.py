# app/transport/schemas.py
from pydantic import BaseModel, Field

class ChatIn(BaseModel):
    chat_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=2000)
    message_id: str | None = Field(default=None, max_length=128)


class MediaIn(BaseModel):
    chat_id: str
    message_id: str | None = None


class ChatOut(BaseModel):
    reply: str
    step: str
    lead_id: str