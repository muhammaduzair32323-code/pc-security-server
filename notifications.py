"""
notifications.py — Firebase FCM Push Notifications
===================================================
Sends push alerts to the owner's mobile app.
Uses Firebase Admin SDK with V1 API (service account).
"""

import os 
import json
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("notifications")

# Load firebase credentials from environment or file
_firebase_initialized = False

def _init_firebase():
    global _firebase_initialized
    if _firebase_initialized:
        return

    try:
        import firebase_admin
        from firebase_admin import credentials

        # Service account JSON stored as environment variable on Render
        sa_json = os.getenv("FIREBASE_SERVICE_ACCOUNT")
        if sa_json:
            sa_dict = json.loads(sa_json)
            cred = credentials.Certificate(sa_dict)
        else:
            # Local development — use the JSON file directly
            sa_path = Path(__file__).parent / "serviceAccountKey.json"
            cred = credentials.Certificate(str(sa_path))
        
        firebase_admin.initialize_app(cred)
        _firebase_initialized = True
        log.info("Firebase initialized.")

    except Exception as e:
        log.error(f"Firebase init failed: {e}")
    


def send_intruder_alert(
    fcm_token: str,
    device_name: str, 
    snapshot_url: str,
    timestamp: str,
    event_id: int,
) -> bool:
    """
    Send intruder detection push notification to mobile app.
    Returns True on success.
    """
    _init_firebase()
    try:
        from firebase_admin import messaging
        message = messaging.Message(
            token = fcm_token,
            notification = messaging.Notification(
                title = "⚠️ Intruder Detected!",
                body  = f"Unknown person tried to access {device_name}",
            ),
            data = {
                "type"         : "INTRUDER_ALERT",
                "event_id"     : str(event_id),
                "device_name"  : device_name,
                "snapshot_url" : snapshot_url,
                "timestamp"    : timestamp,
            },
            android = messaging.AndroidConfig(
                priority           = "high",
                notification       = messaging.AndroidNotification(
                    sound          = "default",
                    priority       = "max",
                    visibility     = "public",
                    channel_id     = "security_alerts",
                ),
            ),
        )

        response = messaging.send(message)
        log.info(f"Intruder alert sent: {response}")
        return True
    
    except Exception as e:
        log.error(f"Failed to send intruder alert: {e}")
        return False

def send_access_notification(
    fcm_token: str,
    device_name: str,
    person_name: str,
    role: str,
    timestamp: str,
    event_id: int,
) -> bool:
    """
    Send access notification for MONITORED users.
    Silent for OWNER and GUEST.
    """
    if role not in ("MONITORED",):
        return True     # no notification needed
    
    _init_firebase()
    try:
        from firebase_admin import messaging

        message = messaging.Message(
            token = fcm_token,
            notification = messaging.Notification(
                title = f"👁️ {person_name} accessed your PC",
                body  = f"{device_name} was accessed at {timestamp}",
            ),
            data = {
                "type"        : "MONITORED_ACCESS",
                "event_id"    : str(event_id),
                "person_name" : person_name,
                "device_name" : device_name,
                "timestamp"   : timestamp,
            },
        )

        response = messaging.send(message)
        log.info(f"Access notification sent: {response}")
        return True
    
    except Exception as e:
        log.error(f"Failed to send access notification: {e}")
        return False
    
def send_command_result(
    fcm_token: str,
    command: str,
    success: bool,
    device_name: str,
) -> bool:
    """Notify mobile that a remote command was executed."""
    _init_firebase()
    try:
        from firebase_admin import messaging

        status = "executed" if success else "failed"
        message = messaging.Message(
            token = fcm_token,
            notification = messaging.Notification(
                title = f"Command {status}",
                body  = f"{command} {status} on {device_name}",
            ),
            data = {
                "type"    : "COMMAND_RESULT",
                "command" : command,
                "success" : str(success),
            },
        )

        messaging.send(message)
        return True

    except Exception as e:
        log.error(f"Command result notification failed: {e}")
        return False

