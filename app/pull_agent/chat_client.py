import logging

logger = logging.getLogger(__name__)


def add_sys_manager_to_chat(system_name: str, manager_type: str) -> bool:
    """Stub. Replace with real API call when integrating."""
    logger.info(
        "add_sys_manager_to_chat called: system=%s, manager=%s",
        system_name, manager_type,
    )
    return True
