import json
import logging

from sqlalchemy.orm import Session

from ..models import AdminAuditLog

logger = logging.getLogger(__name__)


def log_admin_action(
    db: Session,
    *,
    action: str,
    actor_attendant_id: int | None = None,
    entity_type: str = "system",
    entity_id: int | None = None,
    details: dict | str | None = None,
) -> None:
    if isinstance(details, dict):
        serialized_details = json.dumps(details, ensure_ascii=True, sort_keys=True)
    else:
        serialized_details = details

    db.add(
        AdminAuditLog(
            actor_attendant_id=actor_attendant_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=serialized_details,
        )
    )
    logger.info(
        "Admin audit action=%s actor=%s entity=%s entity_id=%s",
        action,
        actor_attendant_id,
        entity_type,
        entity_id,
    )
