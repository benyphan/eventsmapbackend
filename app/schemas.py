from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, ConfigDict, field_validator


# ---------- Users ----------

class UserCreate(BaseModel):
    name: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    password: str
    username: Optional[str] = None
    birth_date: Optional[datetime] = None
    gender: Optional[str] = None
    referral_code: Optional[str] = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    username: Optional[str] = None
    email: Optional[str]
    phone: Optional[str]
    bio: Optional[str]
    avatar_url: Optional[str]
    is_verified: bool
    role: str
    status: str
    messages_policy: str = "all"
    e2e_public_key: Optional[str] = None
    referral_code: Optional[str] = None
    referral_count: int = 0
    credits: int = 0
    active_decoration: Optional[str] = None
    active_decoration_name: Optional[str] = None
    active_decoration_emoji: Optional[str] = None
    gifts_visibility: str = "all"
    gifts_policy: str = "all"


class GiftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    from_user_id: str
    from_user_name: Optional[str] = None
    to_user_id: str
    item_id: str
    item_name: Optional[str] = None
    item_emoji: Optional[str] = None
    message: Optional[str] = None
    created_at: Optional[datetime] = None


class UserPublicOut(BaseModel):
    """Публичные данные пользователя — без email/телефона (приватность)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    username: Optional[str] = None
    bio: Optional[str]
    avatar_url: Optional[str]
    is_verified: bool
    messages_policy: str = "all"
    e2e_public_key: Optional[str] = None
    active_decoration: Optional[str] = None
    active_decoration_name: Optional[str] = None
    active_decoration_emoji: Optional[str] = None
    gifts_visibility: str = "all"
    gifts_policy: str = "all"
    gifts: List[GiftOut] = []


class UserLogin(BaseModel):
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class VerifyCodeIn(BaseModel):
    email: EmailStr
    code: str


class SendCodeOut(BaseModel):
    email: EmailStr
    dev_code: Optional[str] = None


class EmailIn(BaseModel):
    email: EmailStr


class ResendCodeIn(BaseModel):
    email: EmailStr
    purpose: str


class ResetPasswordIn(BaseModel):
    email: EmailStr
    code: str
    new_password: str


# ---------- Events ----------

class EventCriteriaIn(BaseModel):
    min_age: Optional[int] = None
    max_age: Optional[int] = None
    gender: Optional[str] = None
    nationality: Optional[str] = None
    subculture: Optional[str] = None
    interests: Optional[List[str]] = None


class EventCriteriaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    min_age: Optional[int] = None
    max_age: Optional[int] = None
    gender: Optional[str] = None
    nationality: Optional[str] = None
    subculture: Optional[str] = None
    interests: Optional[List[str]] = None


class EventCreate(BaseModel):
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    lat: float
    lng: float
    address: Optional[str] = None
    start_at: datetime
    end_at: Optional[datetime] = None
    visibility: str = "public"
    max_participants: Optional[int] = None
    criteria: Optional[EventCriteriaIn] = None
    tags: Optional[List[str]] = None


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_id: str
    title: str
    description: Optional[str]
    category: Optional[str]
    address: Optional[str]
    lat: Optional[float] = None
    lng: Optional[float] = None
    start_at: datetime
    end_at: Optional[datetime]
    visibility: str
    max_participants: Optional[int]
    status: str
    cover_image_url: Optional[str]
    moderation_note: Optional[str] = None
    owner_name: Optional[str] = None
    participant_count: Optional[int] = 0
    is_owner: Optional[bool] = False
    my_participant_status: Optional[str] = None
    distance_m: Optional[int] = None
    criteria: Optional[EventCriteriaOut] = None
    tags: Optional[List[str]] = None
    archived: Optional[bool] = False


# ---------- Participants ----------

class ParticipantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_id: str
    user_id: str
    user_name: Optional[str] = None
    avatar_url: Optional[str] = None
    status: str
    is_me: Optional[bool] = False
    requested_at: Optional[datetime] = None
    decided_at: Optional[datetime] = None


class ParticipantDecision(BaseModel):
    status: str  # approved | rejected


# ---------- Admin ----------

class ModerationDecision(BaseModel):
    status: str  # published | rejected

class UserBan(BaseModel):
    status: str  # banned | active


# ---------- Notifications ----------

class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    body: Optional[str]
    is_read: bool
    created_at: Optional[datetime]


# ---------- Posts ----------

class PostCreate(BaseModel):
    text: str


class PostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    text: str
    image_url: Optional[str] = None
    image_urls: Optional[List[str]] = None
    moderation_status: Optional[str] = "published"
    moderation_note: Optional[str] = None
    created_at: Optional[datetime]
    user_name: Optional[str] = None


class PostDecision(BaseModel):
    status: str  # published | rejected


# ---------- Friends ----------

class FriendRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    from_user_id: str
    to_user_id: str
    status: str
    created_at: Optional[datetime]
    from_user_name: Optional[str] = None
    to_user_name: Optional[str] = None
    from_user_avatar: Optional[str] = None
    to_user_avatar: Optional[str] = None


# ---------- Search ----------

class SearchResult(BaseModel):
    users: List["UserOut"] = []
    events: List["EventOut"] = []


# ---------- Chats / Messages (E2E) ----------

class ChatCreate(BaseModel):
    user_id: str  # собеседник для личного чата


class ChatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    is_group: bool
    title: Optional[str] = None
    event_id: Optional[str] = None
    member_count: int = 0
    other_user: Optional["UserPublicOut"] = None
    last_message: Optional["MessageOut"] = None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    chat_id: str
    sender_id: str
    sender_name: Optional[str] = None
    content_enc: Optional[str] = None  # base64 шифрованного содержимого
    created_at: Optional[datetime]


class MessageCreate(BaseModel):
    content_enc: str  # base64

    @field_validator("content_enc")
    @classmethod
    def content_not_too_long(cls, v: str) -> str:
        # ~5000 символов текста в base64 (примерно 6700 символов b64)
        if len(v) > 8000:
            raise ValueError("Сообщение слишком длинное (максимум 5000 символов)")
        return v


ChatOut.model_rebuild()
MessageOut.model_rebuild()
SearchResult.model_rebuild()


# ---------- Shop ----------

class ShopItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    emoji: Optional[str] = None
    description: Optional[str] = None
    item_type: str = "decoration"
    price: int = 0


class GiftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    from_user_id: str
    from_user_name: Optional[str] = None
    to_user_id: str
    item_id: str
    item_name: Optional[str] = None
    item_emoji: Optional[str] = None
    message: Optional[str] = None
    created_at: Optional[datetime] = None


class GiftSend(BaseModel):
    to_user_id: str
    message: Optional[str] = None


class ShopOut(BaseModel):
    credits: int
    active_decoration: Optional[str] = None
    owned_decorations: List[str] = []
    items: List[ShopItemOut] = []
    gifts_received: List[GiftOut] = []


class PurchaseOut(BaseModel):
    credits: int
    active_decoration: Optional[str] = None


ShopOut.model_rebuild()
GiftOut.model_rebuild()
UserPublicOut.model_rebuild()

