from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .lib.admin_auth import require_admin_session

router = APIRouter()


class NotificationRequest(BaseModel):
    message: str
    user_id: int


@router.get("/notifications", include_in_schema=False)
async def get_notifications(
    admin_email: str = Depends(require_admin_session),
):
    return {
        "notifications": [
            {
                "id": "1",
                "message": "The new admin console has been deployed.",
                "created_at": "2026-07-17T10:30:00Z",
                "read": False,
            }
        ]
    }


@router.post("/notifications", include_in_schema=False)
async def create_notification(
    notification: NotificationRequest,
    admin_email: str = Depends(require_admin_session),
):
    return {
        "status": "success",
        "message": "Notification created",
        "notification_id": "temp-id",
    }


@router.post("/notifications/{notification_id}/read", include_in_schema=False)
async def mark_notification_read(
    notification_id: str,
    admin_email: str = Depends(require_admin_session),
):
    return {"status": "success", "message": f"Notification {notification_id} marked as read"}