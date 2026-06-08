"""
storage.py — Cloudinary File Upload
====================================
Uploads intruder images and audio to Cloudinary.
Returns public URLs stored in the database.
"""

import os
import cloudinary
import cloudinary.uploader
import logging
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("storage")

cloudinary.config(
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key    = os.getenv("CLOUDINARY_API_KEY"),
    api_secret = os.getenv("CLOUDINARY_API_SECRET"),
    secure     = True,
)

def upload_image(
    file_bytes: bytes,
    filename: str,
    folder: str = "pc_security/images",
) -> str:
    """
    Upload JPEG image bytes to Cloudinary.
    Returns the secure public URL.
    """
    try:
        result = cloudinary.uploader.upload(
            file_bytes,
            public_id      = filename,
            folder         = folder,
            resource_type  = "image",
            format         = "jpg",
            overwrite      = True,
        )
        url = result.get("secure_url", "")
        log.info(f"Image uploaded: {url}")
        return url
    except Exception as e:
        log.error(f"Image upload failed: {e}")
        return ""
    
def upload_audio(
    file_bytes: bytes,
    filename: str,
    folder: str = "pc_security/audio",
) -> str:
    """
    Upload WAV audio bytes to Cloudinary.
    Returns the secure public URL.
    """
    try:
        result = cloudinary.uploader.upload(
            file_bytes,
            public_id     = filename,
            folder        = folder,
            resource_type = "video",   # Cloudinary uses "video" for audio too
            format        = "wav",
            overwrite     = True,
        )
        url = result.get("secure_url", "")
        log.info(f"Audio uploaded: {url}")
        return url
    except Exception as e:
        log.error(f"Audio upload failed: {e}")
        return ""
    
def upload_face_photo(
    file_bytes: bytes,
    person_name: str,
    device_id: str,
) -> str:
    """Upload enrollment face photo."""
    filename = f"{device_id}_{person_name}_{__import__('time').time()}"
    return upload_image(
        file_bytes,
        filename,
        folder="pc_security/faces",
    )

