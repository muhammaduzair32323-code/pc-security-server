"""
recognizer.py — Server-Side Person Lookup
==========================================
Lightweight version — no face_recognition on server.
PC does all face recognition locally and sends results here.
Server looks up person by name/embedding match from DB.
"""

import numpy as np
import logging
from sqlalchemy.orm import Session
from models import Person

log = logging.getLogger("recognizer")

MATCH_THRESHOLD = 0.45


def lookup_person_by_result(
    person_name: str,
    device_id: str,
    db: Session,
) -> dict:
    """
    Look up a person by name in the DB.
    Called when PC sends recognition result to server.
    """
    person = db.query(Person).filter(
        Person.device_id == device_id,
        Person.name == person_name,
        Person.is_active == True,
    ).first()

    if person:
        return {
            "matched"   : True,
            "person_id" : person.id,
            "name"      : person.name,
            "role"      : person.role,
            "photo_url" : person.photo_url,
        }

    return {
        "matched"   : False,
        "person_id" : None,
        "name"      : person_name,
        "role"      : "STRANGER",
        "photo_url" : None,
    }


def compare_embeddings(
    embedding1_str: str,
    embedding2_str: str,
) -> float:
    """
    Compare two stored embeddings.
    Returns Euclidean distance.
    """
    try:
        e1 = np.array([float(x) for x in embedding1_str.split(",")])
        e2 = np.array([float(x) for x in embedding2_str.split(",")])
        return float(np.linalg.norm(e1 - e2))
    except Exception:
        return 1.0


def find_person_by_embedding(
    embedding_str: str,
    device_id: str,
    db: Session,
) -> dict:
    """
    Find best matching person by comparing embeddings stored in DB.
    Used when PC sends an embedding instead of a name.
    No face_recognition library needed — pure numpy math.
    """
    persons = db.query(Person).filter(
        Person.device_id == device_id,
        Person.is_active == True,
        Person.embedding != None,
    ).all()

    if not persons:
        return _stranger()

    best_match    = None
    best_distance = float("inf")

    for person in persons:
        if not person.embedding:
            continue
        dist = compare_embeddings(embedding_str, person.embedding)
        if dist < best_distance:
            best_distance = dist
            best_match    = person

    if best_match and best_distance < MATCH_THRESHOLD:
        MAX_DIST   = 0.9
        confidence = round((1.0 - best_distance / MAX_DIST) * 100, 1)
        return {
            "matched"   : True,
            "person_id" : best_match.id,
            "name"      : best_match.name,
            "role"      : best_match.role,
            "confidence": confidence,
            "distance"  : best_distance,
        }

    return _stranger()


def embedding_to_str(embedding) -> str:
    """Convert numpy array to comma string for DB storage."""
    if hasattr(embedding, "tolist"):
        return ",".join(str(x) for x in embedding.tolist())
    return ",".join(str(x) for x in embedding)


def _stranger() -> dict:
    return {
        "matched"   : False,
        "person_id" : None,
        "name"      : "Unknown",
        "role"      : "STRANGER",
        "confidence": 0.0,
        "distance"  : 1.0,
    }
