import logging

logger = logging.getLogger("signalpulse")
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(handler)
logger.setLevel(logging.INFO)


def log_event(event: str, **fields: object) -> None:
    """Log a structured event as ``event key=value key=value ...``."""
    parts = [event]
    parts.extend(f"{key}={value}" for key, value in fields.items())
    logger.info(" ".join(parts))