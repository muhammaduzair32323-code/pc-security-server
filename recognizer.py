"""
recognizer.py — Server-Side Face Recognition
=============================================
Receives a face frame from the PC, compares it against
ALL enrolled persons in the database for that device.

Returns: name, role, confidence of best match
         or STRANGER if no match found.
"""

import numpy as np
import face_recognition
import logging
import io
from PIL import Image
from sqlalchemy.orm import Session
from models import Person

log = logging.getLogger("recognizer")

MATCH_THRESHOLD = 0.45


def recognize_face(
    image_bytes: bytes,
    device_id: str,
    db: Session,
) -> dict:
    """
    Compare incoming face image against all enrolled persons.

    Args:
        image_bytes: JPEG image bytes from PC
        device_id:   which device is requesting
        db:          database session

    Returns:
        dict with keys:
          - matched: bool
          - person_id: int or None
          - name: str
          - role: OWNER/GUEST/MONITORED/STRANGER
          - confidence: float 0-100
    """
    # Load all active persons for this device
    persons = db.query(Person).filter(
        Person.device_id == device_id,
        Person.is_active == True,
        Person.embedding != None,
    ).all()

    if not persons:
        log.warning(f"No enrolled persons for device {device_id}")
        return _stranger_result()

    # Decode image
    try:
        img   = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        frame = np.array(img)
    except Exception as e:
        log.error(f"Image decode failed: {e}")
        return _stranger_result()

    # Detect face
    face_locations = face_recognition.face_locations(frame, model="hog")
    if not face_locations:
        log.warning("No face detected in submitted image.")
        return _stranger_result()

    # Use largest face
    largest = max(
        face_locations,
        key=lambda l: (l[2] - l[0]) * (l[1] - l[3])
    )

    encodings = face_recognition.face_encodings(frame, [largest])
    if not encodings:
        return _stranger_result()

    live_encoding = encodings[0]

    # Compare against all enrolled persons
    best_match      = None
    best_distance   = float("inf")

    for person in persons:
        try:
            stored = np.array(
                [float(x) for x in person.embedding.split(",")]
            )
            distance = float(np.linalg.norm(live_encoding - stored))

            builtin = face_recognition.compare_faces(
                [stored], live_encoding, tolerance=MATCH_THRESHOLD
            )[0]

            if builtin and distance < MATCH_THRESHOLD:
                if distance < best_distance:
                    best_distance = distance
                    best_match    = person

        except Exception as e:
            log.warning(f"Error comparing person {person.id}: {e}")
            continue

    if best_match:
        MAX_DIST   = 0.9
        confidence = round((1.0 - best_distance / MAX_DIST) * 100, 1)
        log.info(
            f"Match: {best_match.name} ({best_match.role}) "
            f"distance={best_distance:.4f} confidence={confidence}%"
        )
        return {
            "matched"   : True,
            "person_id" : best_match.id,
            "name"      : best_match.name,
            "role"      : best_match.role,
            "confidence": confidence,
            "distance"  : best_distance,
        }

    log.info(f"No match found — STRANGER. Best distance={best_distance:.4f}")
    return _stranger_result()


def embedding_to_str(embedding: np.ndarray) -> str:
    """Convert numpy embedding to comma-separated string for DB storage."""
    return ",".join(str(x) for x in embedding.tolist())


def str_to_embedding(embedding_str: str) -> np.ndarray:
    """Convert stored string back to numpy array."""
    return np.array([float(x) for x in embedding_str.split(",")])


def _stranger_result() -> dict:
    return {
        "matched"   : False,
        "person_id" : None,
        "name"      : "Unknown",
        "role"      : "STRANGER",
        "confidence": 0.0,
        "distance"  : 1.0,
    }