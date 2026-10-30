from pydantic import BaseModel, Field


class Text(BaseModel):
    body: str = ""


class Message(BaseModel):
    id: str = Field(min_length=1, max_length=512)
    sender: str = Field(alias="from", pattern=r"^[0-9]{6,20}$")
    timestamp: int = Field(ge=0)
    type: str
    text: Text | None = None


class Metadata(BaseModel):
    phone_number_id: str = ""


class DeliveryStatus(BaseModel):
    id: str
    status: str
    timestamp: int = 0
    biz_opaque_callback_data: str | None = None
    errors: list[dict] = Field(default_factory=list)


class Value(BaseModel):
    messaging_product: str = ""
    metadata: Metadata = Field(default_factory=Metadata)
    messages: list[Message] = Field(default_factory=list)
    statuses: list[DeliveryStatus] = Field(default_factory=list)


class Change(BaseModel):
    field: str
    value: Value


class Entry(BaseModel):
    changes: list[Change] = Field(default_factory=list)


class Webhook(BaseModel):
    object: str
    entry: list[Entry] = Field(default_factory=list)
