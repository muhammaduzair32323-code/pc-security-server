"""
server/main.py — FastAPI Backend Server
========================================
All endpoints for the PC Security System.

Endpoints:
  POST /device/register     → PC registers itself
  POST /device/heartbeat    → PC sends online status
  GET  /device/status       → mobile checks PC status
  POST /enroll              → upload face + assign role
  POST /recognize           → PC sends frame for recognition
  POST /event               → PC uploads evidence bundle
  POST /command             → mobile sends remote command
  GET  /events              → mobile fetches event history
  GET  /events/{id}         → single event detail
  WS   /ws/{device_id}      → persistent WebSocket command channel
"""

import os
import json
import logging
import asyncio
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv

from fastapi import (
    FastAPI, Depends, HTTPException,
    WebSocket, WebSocketDisconnect,
    UploadFile, File, Form, Header,
)
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from database import engine, get_db, Base
from models import Device, Person, Event
from storage import upload_image, upload_audio, upload_face_photo
from notifications import (
    send_intruder_alert,
    send_access_notification,
    send_command_result,
)
from recognizer import recognize_face, embedding_to_str

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("server")

# Create all tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title      = "PC Security API",
    version    = "1.0.0",
    description= "AI-based PC Security System — Backend Server",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["*"],
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

# ── Active WebSocket connections ──────────────────────────────
# device_id → WebSocket
active_connections: dict[str, WebSocket] = {}

DEVICE_TOKEN = os.getenv("DEVICE_TOKEN", "pcsecurity_device_token_2026")


# ── Auth helper ───────────────────────────────────────────────

def verify_token(x_device_token: str = Header(...)) -> str:
    if x_device_token != DEVICE_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid device token")
    return x_device_token


# ── Health check ──────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "PC Security Server running", "version": "1.0.0"}

@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat()}


# ── Device endpoints ──────────────────────────────────────────

@app.post("/device/register")
def register_device(
    device_id:   str = Form(...),
    device_name: str = Form(...),
    db:          Session = Depends(get_db),
    _:           str = Depends(verify_token),
):
    """PC registers itself on first boot."""
    device = db.query(Device).filter(
        Device.device_id == device_id
    ).first()

    if not device:
        device = Device(
            device_id   = device_id,
            device_name = device_name,
            owner_token = DEVICE_TOKEN,
            is_online   = True,
            last_seen   = datetime.now(),
        )
        db.add(device)
        db.commit()
        db.refresh(device)
        log.info(f"New device registered: {device_name} ({device_id})")
    else:
        device.is_online  = True
        device.last_seen  = datetime.now()
        db.commit()
        log.info(f"Device reconnected: {device_name}")

    return {"status": "registered", "device_id": device_id}


@app.post("/device/heartbeat")
def heartbeat(
    device_id: str = Form(...),
    is_locked: bool = Form(False),
    db:        Session = Depends(get_db),
    _:         str = Depends(verify_token),
):
    """PC sends heartbeat every 30 seconds."""
    device = db.query(Device).filter(
        Device.device_id == device_id
    ).first()

    if device:
        device.is_online  = True
        device.is_locked  = is_locked
        device.last_seen  = datetime.now()
        db.commit()

    return {"status": "ok"}


@app.get("/device/status/{device_id}")
def device_status(
    device_id: str,
    db:        Session = Depends(get_db),
):
    """Mobile app polls this to check PC status."""
    device = db.query(Device).filter(
        Device.device_id == device_id
    ).first()

    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Consider offline if no heartbeat in 60 seconds
    last_seen  = device.last_seen
    now        = datetime.now()
    seconds    = (now - last_seen).total_seconds() if last_seen else 999
    is_online  = seconds < 60

    return {
        "device_id"  : device.device_id,
        "device_name": device.device_name,
        "is_online"  : is_online,
        "is_locked"  : device.is_locked,
        "last_seen"  : str(device.last_seen),
    }


# ── Enrollment endpoint ───────────────────────────────────────

@app.post("/enroll")
async def enroll_person(
    device_id:    str        = Form(...),
    name:         str        = Form(...),
    role:         str        = Form("GUEST"),
    embedding_str: str       = Form(...),
    photo:        Optional[UploadFile] = File(None),
    db:           Session    = Depends(get_db),
    _:            str        = Depends(verify_token),
):
    """
    Enroll a person from PC or mobile.
    PC sends the embedding string (already computed locally).
    Server stores it + optional photo to Cloudinary.
    Role: OWNER / GUEST / MONITORED
    """
    if role not in ("OWNER", "GUEST", "MONITORED"):
        raise HTTPException(
            status_code=400,
            detail="Role must be OWNER, GUEST or MONITORED"
        )

    photo_url = ""
    if photo:
        photo_bytes = await photo.read()
        photo_url   = upload_face_photo(photo_bytes, name, device_id)

    person = Person(
        device_id   = device_id,
        name        = name,
        role        = role,
        embedding   = embedding_str,
        photo_url   = photo_url,
        enrolled_by = "pc",
    )
    db.add(person)
    db.commit()
    db.refresh(person)

    log.info(f"Enrolled: {name} as {role} for device {device_id}")
    return {
        "status"   : "enrolled",
        "person_id": person.id,
        "name"     : name,
        "role"     : role,
        "photo_url": photo_url,
    }

# ── Recognition endpoint ──────────────────────────────────────

@app.post("/recognize")
async def recognize(
    device_id:    str = Form(...),
    embedding_str: str = Form(...),
    db:           Session = Depends(get_db),
    _:            str = Depends(verify_token),
):
    """
    PC sends face embedding string → server finds matching person.
    No image processing on server — pure DB lookup.
    """
    from recognizer import find_person_by_embedding
    result = find_person_by_embedding(embedding_str, device_id, db)
    return result


# ── Event endpoint ────────────────────────────────────────────

@app.post("/event")
async def receive_event(
    device_id:       str        = Form(...),
    event_type:      str        = Form(...),
    timestamp:       str        = Form(...),
    hostname:        str        = Form(""),
    ip_address:      str        = Form(""),
    failed_attempts: int        = Form(0),
    person_name:     str        = Form("Unknown"),
    person_role:     str        = Form("STRANGER"),
    confidence:      float      = Form(0.0),
    snapshot:        Optional[UploadFile] = File(None),
    fresh:           Optional[UploadFile] = File(None),
    audio:           Optional[UploadFile] = File(None),
    db:              Session    = Depends(get_db),
    _:               str        = Depends(verify_token),
):
    """
    PC uploads evidence bundle after intruder detection.
    Stores files to Cloudinary, saves event to DB,
    sends push notification to mobile.
    """
    # Upload files to Cloudinary
    ts           = timestamp.replace(":", "-").replace(".", "-")
    snapshot_url = ""
    fresh_url    = ""
    audio_url    = ""

    if snapshot:
        snapshot_bytes = await snapshot.read()
        snapshot_url   = upload_image(
            snapshot_bytes, f"snapshot_{device_id}_{ts}"
        )

    if fresh:
        fresh_bytes = await fresh.read()
        fresh_url   = upload_image(
            fresh_bytes, f"fresh_{device_id}_{ts}"
        )

    if audio:
        audio_bytes = await audio.read()
        audio_url   = upload_audio(
            audio_bytes, f"audio_{device_id}_{ts}"
        )

    # Save event to DB
    event = Event(
        device_id       = device_id,
        event_type      = event_type,
        timestamp       = datetime.fromisoformat(timestamp),
        hostname        = hostname,
        ip_address      = ip_address,
        person_name     = person_name,
        person_role     = person_role,
        confidence      = confidence,
        failed_attempts = failed_attempts,
        snapshot_url    = snapshot_url,
        fresh_url       = fresh_url,
        audio_url       = audio_url,
        notified        = False,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    log.info(f"Event saved: [{event_type}] id={event.id}")

    # Send push notification if intruder or monitored
    device = db.query(Device).filter(
        Device.device_id == device_id
    ).first()

    if device and device.fcm_token:
        if event_type == "INTRUDER_DETECTED":
            sent = send_intruder_alert(
                fcm_token   = device.fcm_token,
                device_name = device.device_name,
                snapshot_url= snapshot_url or fresh_url,
                timestamp   = timestamp,
                event_id    = event.id,
            )
        elif event_type == "MONITORED_ACCESS":
            sent = send_access_notification(
                fcm_token   = device.fcm_token,
                device_name = device.device_name,
                person_name = person_name,
                role        = person_role,
                timestamp   = timestamp,
                event_id    = event.id,
            )
        else:
            sent = False

        if sent:
            event.notified = True
            db.commit()

    return {
        "status"      : "received",
        "event_id"    : event.id,
        "snapshot_url": snapshot_url,
        "fresh_url"   : fresh_url,
        "audio_url"   : audio_url,
    }


# ── Events history ────────────────────────────────────────────

@app.get("/events/{device_id}")
def get_events(
    device_id: str,
    limit:     int     = 50,
    db:        Session = Depends(get_db),
):
    """Mobile app fetches event history."""
    events = db.query(Event).filter(
        Event.device_id == device_id
    ).order_by(
        Event.id.desc()
    ).limit(limit).all()

    return [
        {
            "id"            : e.id,
            "event_type"    : e.event_type,
            "timestamp"     : str(e.timestamp),
            "person_name"   : e.person_name,
            "person_role"   : e.person_role,
            "confidence"    : e.confidence,
            "failed_attempts": e.failed_attempts,
            "snapshot_url"  : e.snapshot_url,
            "fresh_url"     : e.fresh_url,
            "audio_url"     : e.audio_url,
            "command_sent"  : e.command_sent,
            "notified"      : e.notified,
        }
        for e in events
    ]


@app.get("/event/{event_id}")
def get_event(
    event_id: int,
    db:       Session = Depends(get_db),
):
    """Single event detail."""
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


# ── Command endpoint ──────────────────────────────────────────

@app.post("/command")
async def send_command(
    device_id: str = Form(...),
    command:   str = Form(...),
    db:        Session = Depends(get_db),
    _:         str = Depends(verify_token),
):
    """
    Mobile sends a command to the PC.
    Commands: LOCK / SHUTDOWN / APPROVE / DENY
    Delivered via WebSocket if PC is connected.
    """
    if command not in ("LOCK", "SHUTDOWN", "APPROVE", "DENY"):
        raise HTTPException(
            status_code=400,
            detail="Command must be LOCK, SHUTDOWN, APPROVE or DENY"
        )

    # Try to deliver via WebSocket first (instant)
    ws = active_connections.get(device_id)
    delivered = False

    if ws:
        try:
            await ws.send_text(json.dumps({
                "type"   : "COMMAND",
                "command": command,
            }))
            delivered = True
            log.info(f"Command {command} delivered via WebSocket to {device_id}")
        except Exception as e:
            log.warning(f"WebSocket delivery failed: {e}")
            active_connections.pop(device_id, None)

    # Log command in DB
    device = db.query(Device).filter(
        Device.device_id == device_id
    ).first()

    if device:
        if command == "LOCK":
            device.is_locked = True
        elif command == "APPROVE":
            device.is_locked = False
        db.commit()

    return {
        "status"   : "delivered" if delivered else "queued",
        "command"  : command,
        "device_id": device_id,
        "via"      : "websocket" if delivered else "polling",
    }


# ── FCM token update ──────────────────────────────────────────

@app.post("/device/fcm-token")
def update_fcm_token(
    device_id: str = Form(...),
    fcm_token: str = Form(...),
    db:        Session = Depends(get_db),
    _:         str = Depends(verify_token),
):
    """Mobile app registers its FCM token for push notifications."""
    device = db.query(Device).filter(
        Device.device_id == device_id
    ).first()

    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    device.fcm_token = fcm_token
    db.commit()
    log.info(f"FCM token updated for device {device_id}")
    return {"status": "updated"}


# ── WebSocket ─────────────────────────────────────────────────

@app.websocket("/ws/{device_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    device_id: str,
    db:        Session = Depends(get_db),
):
    """
    Persistent WebSocket connection from PC.
    PC connects on boot and stays connected.
    Commands from mobile are pushed through here instantly.
    """
    await websocket.accept()
    active_connections[device_id] = websocket
    log.info(f"WebSocket connected: {device_id}")

    # Mark device online
    device = db.query(Device).filter(
        Device.device_id == device_id
    ).first()
    if device:
        device.is_online = True
        device.last_seen = datetime.now()
        db.commit()

    try:
        while True:
            # Keep connection alive — wait for messages
            data = await websocket.receive_text()
            log.info(f"WebSocket message from {device_id}: {data}")

    except WebSocketDisconnect:
        active_connections.pop(device_id, None)
        log.info(f"WebSocket disconnected: {device_id}")

        # Mark offline
        if device:
            device.is_online = False
            db.commit()
