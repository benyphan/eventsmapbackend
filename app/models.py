import uuid
import enum
from datetime import datetime

from sqlalchemy import (
    Column, String, Boolean, DateTime, ForeignKey, Enum, Integer,
    Text, LargeBinary, ARRAY, JSON
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from geoalchemy2 import Geography
from geoalchemy2.shape import to_shape

from app.database import Base


def gen_uuid():
    return str(uuid.uuid4())


class UserRole(str, enum.Enum):
    user = "user"
    moderator = "moderator"
    admin = "admin"


class UserStatus(str, enum.Enum):
    active = "active"
    banned = "banned"
    pending = "pending"


class EventVisibility(str, enum.Enum):
    public = "public"
    approval_required = "approval_required"
    invite_only = "invite_only"


class EventStatus(str, enum.Enum):
    draft = "draft"
    pending_moderation = "pending_moderation"
    published = "published"
    rejected = "rejected"
    cancelled = "cancelled"
    finished = "finished"


class ParticipantStatus(str, enum.Enum):
    requested = "requested"
    approved = "approved"
    rejected = "rejected"
    cancelled = "cancelled"


class ReportTargetType(str, enum.Enum):
    user = "user"
    event = "event"
    message = "message"


class ReportStatus(str, enum.Enum):
    open = "open"
    reviewed = "reviewed"
    dismissed = "dismissed"


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    phone = Column(String, unique=True, nullable=True)
    email = Column(String, unique=True, nullable=True)
    password_hash = Column(String, nullable=False)
    name = Column(String, nullable=False)
    username = Column(String, unique=True, index=True, nullable=True)  # тег @username
    birth_date = Column(DateTime, nullable=True)
    gender = Column(String, nullable=True)
    bio = Column(Text, nullable=True)
    avatar_url = Column(String, nullable=True)
    is_verified = Column(Boolean, default=False)
    role = Column(Enum(UserRole), default=UserRole.user)
    status = Column(Enum(UserStatus), default=UserStatus.active)
    messages_policy = Column(String, default="all")  # all | friends
    gifts_policy = Column(String, default="all")  # all | friends | none — кто видит полученные подарки
    gifts_visibility = Column(String, default="all")  # all | friends | nobody
    e2e_public_key = Column(Text, nullable=True)
    referral_code = Column(String, unique=True, index=True, nullable=True)
    referred_by_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    referral_count = Column(Integer, default=0)
    credits = Column(Integer, default=0)  # бонусные баллы (продвижение, плюшки)
    active_decoration = Column(String, nullable=True)  # id купленного украшения профиля
    created_at = Column(DateTime, default=datetime.utcnow)

    events = relationship("Event", back_populates="owner")
    posts = relationship("Post", back_populates="user")
    sent_friend_requests = relationship(
        "FriendRequest",
        foreign_keys="FriendRequest.from_user_id",
        back_populates="from_user",
    )
    received_friend_requests = relationship(
        "FriendRequest",
        foreign_keys="FriendRequest.to_user_id",
        back_populates="to_user",
    )


class Event(Base):
    __tablename__ = "events"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    owner_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String, nullable=True)
    location = Column(Geography(geometry_type="POINT", srid=4326), nullable=False)
    address = Column(String, nullable=True)
    start_at = Column(DateTime, nullable=False)
    end_at = Column(DateTime, nullable=True)
    visibility = Column(Enum(EventVisibility), default=EventVisibility.public)
    max_participants = Column(Integer, nullable=True)
    status = Column(Enum(EventStatus), default=EventStatus.pending_moderation)
    cover_image_url = Column(String, nullable=True)
    moderation_note = Column(String, nullable=True)
    tags = Column(ARRAY(String), default=list)
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="events")
    criteria = relationship("EventCriteria", back_populates="event", uselist=False)
    participants = relationship("EventParticipant", back_populates="event")

    @property
    def lat(self):
        if self.location is None:
            return None
        return to_shape(self.location).y

    @property
    def lng(self):
        if self.location is None:
            return None
        return to_shape(self.location).x

    @property
    def owner_name(self):
        return self.owner.name if self.owner else None

    @property
    def participant_count(self):
        return sum(
            1 for p in self.participants
            if p.status == ParticipantStatus.approved
        )


class EventCriteria(Base):
    __tablename__ = "event_criteria"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    event_id = Column(UUID(as_uuid=False), ForeignKey("events.id"), nullable=False)
    min_age = Column(Integer, nullable=True)
    max_age = Column(Integer, nullable=True)
    gender = Column(String, nullable=True)
    nationality = Column(String, nullable=True)
    subculture = Column(String, nullable=True)
    interests = Column(ARRAY(String), nullable=True)
    custom_rules = Column(JSON, nullable=True)

    event = relationship("Event", back_populates="criteria")


class EventParticipant(Base):
    __tablename__ = "event_participants"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    event_id = Column(UUID(as_uuid=False), ForeignKey("events.id"), nullable=False)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    status = Column(Enum(ParticipantStatus), default=ParticipantStatus.requested)
    requested_at = Column(DateTime, default=datetime.utcnow)
    decided_at = Column(DateTime, nullable=True)

    event = relationship("Event", back_populates="participants")
    user = relationship("User")


class Chat(Base):
    __tablename__ = "chats"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    event_id = Column(UUID(as_uuid=False), ForeignKey("events.id"), nullable=True)
    is_group = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ChatMember(Base):
    __tablename__ = "chat_members"

    chat_id = Column(UUID(as_uuid=False), ForeignKey("chats.id"), primary_key=True)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), primary_key=True)


class Message(Base):
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    chat_id = Column(UUID(as_uuid=False), ForeignKey("chats.id"), nullable=False)
    sender_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    content_enc = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_deleted = Column(Boolean, default=False)


class Report(Base):
    __tablename__ = "reports"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    reporter_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    target_type = Column(Enum(ReportTargetType), nullable=False)
    target_id = Column(UUID(as_uuid=False), nullable=False)
    reason = Column(String, nullable=True)
    status = Column(Enum(ReportStatus), default=ReportStatus.open)
    created_at = Column(DateTime, default=datetime.utcnow)


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    title = Column(String, nullable=False)
    body = Column(Text, nullable=True)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")


class Post(Base):
    __tablename__ = "posts"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    text = Column(Text, nullable=False)
    image_url = Column(String, nullable=True)
    image_urls = Column(ARRAY(String), default=list)
    moderation_status = Column(String, default="published")  # published | pending | rejected
    moderation_note = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="posts")


class FriendStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"


class FriendRequest(Base):
    __tablename__ = "friend_requests"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    from_user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    to_user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    status = Column(Enum(FriendStatus), default=FriendStatus.pending)
    created_at = Column(DateTime, default=datetime.utcnow)

    from_user = relationship("User", foreign_keys=[from_user_id], back_populates="sent_friend_requests")
    to_user = relationship("User", foreign_keys=[to_user_id], back_populates="received_friend_requests")


class VerifyCode(Base):
    __tablename__ = "verification_codes"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    email = Column(String, nullable=False, index=True)
    code = Column(String, nullable=False)
    purpose = Column(String, nullable=False)  # register | reset_password
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class PendingRegistration(Base):
    __tablename__ = "pending_registrations"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    password_hash = Column(String, nullable=False)
    birth_date = Column(DateTime, nullable=True)
    gender = Column(String, nullable=True)
    referred_by_id = Column(UUID(as_uuid=False), nullable=True)
    referral_code = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ShopItem(Base):
    __tablename__ = "shop_items"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    name = Column(String, nullable=False)
    emoji = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    item_type = Column(String, nullable=False, default="decoration")  # decoration | gift
    price = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Purchase(Base):
    __tablename__ = "purchases"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    item_id = Column(UUID(as_uuid=False), ForeignKey("shop_items.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    item = relationship("ShopItem")


class Gift(Base):
    __tablename__ = "gifts"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    from_user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    to_user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    item_id = Column(UUID(as_uuid=False), ForeignKey("shop_items.id"), nullable=False)
    message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    item = relationship("ShopItem")
    from_user = relationship("User", foreign_keys=[from_user_id])
    to_user = relationship("User", foreign_keys=[to_user_id])
