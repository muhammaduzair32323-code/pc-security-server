"""
models.py — Database Table Definitions
=======================================
Three tables:
  - devices    : registered PCs
  - persons    : enrolled faces (owner / guest / monitored)
  - events     : all security events (intruder, access, etc.)
"""

from sqlalchemy import (
    Column, Integer, String, Boolean,
    DateTime, Float, Text, ForeignKey
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class Device(Base):
    __tablename__ = "devices"

    id           = Column(Integer, primary_key=True, index=True)
    device_id    = Column(String, unique=True, index=True, nullable=False)
    device_name  = Column(String, nullable=False)
    owner_token  = Column(String, nullable=False)
    fcm_token    = Column(String)           # mobile app FCM token
    is_online    = Column(Boolean, default=False)
    is_locked    = Column(Boolean, default=False)
    last_seen    = Column(DateTime, server_default=func.now())
    created_at   = Column(DateTime, server_default=func.now())

    events       = relationship("Event", back_populates="device")

class Person(Base):
    __tablename__ = "persons"

    id           = Column(Integer, primary_key=True, index=True)
    device_id    = Column(String, ForeignKey("devices.device_id"))
    name         = Column(String, nullable=False)

    # Role: OWNER / GUEST / MONITORED
    role         = Column(String, default="GUEST")

    # Face embedding stored as comma-separated floats
    embedding    = Column(Text)

    # Profile photo URL (Cloudinary)
    photo_url    = Column(String)

    is_active    = Column(Boolean, default=True)
    enrolled_at  = Column(DateTime, server_default=func.now())
    enrolled_by  = Column(String, default="pc")  # "pc" or "mobile"

class Event(Base):
    __tablename__ = "events"

    id              = Column(Integer, primary_key=True, index=True)
    device_id       = Column(String, ForeignKey("devices.device_id"))
    event_type      = Column(String, nullable=False)
    timestamp       = Column(DateTime, server_default=func.now())
    hostname        = Column(String)
    ip_address      = Column(String)

    # Recognized person (if known)
    person_id       = Column(Integer, ForeignKey("persons.id"), nullable=True)
    person_name     = Column(String)
    person_role     = Column(String)

    # Recognition details
    confidence      = Column(Float)
    failed_attempts = Column(Integer, default=0)

    # Evidence files (Cloudinary URLs)
    snapshot_url    = Column(String)
    fresh_url       = Column(String)
    audio_url       = Column(String)

    # Remote command status
    command_sent    = Column(String)
    command_at      = Column(DateTime)

    # Notification
    notified        = Column(Boolean, default=False)

    device          = relationship("Device", back_populates="events")
    
                                
