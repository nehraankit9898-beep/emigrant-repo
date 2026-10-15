"""Structured logging + sensitive-data redaction.

* Phone numbers (12-digit India / 10-digit) -> maskhe (91XXXXXX321)
* Query/param secrets (token=, secret=, signature=, verify_token=, hub.verify_token=) -> [redacted]
* Authorization: Bearer ... -> [redacted]
* Logs ek JSON line (production) ya plain text (development) me.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone

_PHONE = re.compile(r"(?<!\d)(\d{2})(\d{6,8})(\d{3})(?!\d)")
_SECRET_PARAM = re.compile(
    r"((?:hub\.)?(?:verify_)?token|secret|signature|api[_-]?key|password|key_secret|access_token)=([^&\s\"']+)",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.IGNORECASE)


def redact_text(text: str) -> str:
    if not text:
        return text
    text = _SECRET_PARAM.sub(lambda m: f"{m.group(1)}=[redacted]", text)
    text = _BEARER.sub(lambda m: f"{m.group(1)}[redacted]", text)
    text = _PHONE.sub(lambda m: f"{m.group(1)}{'X' * len(m.group(2))}{m.group(3)}", text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - bad format args
            message = str(record.msg)
        record.msg = redact_text(message)
        record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(json_output: bool = False, level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_output else logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    for name in ("", "app", "uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = [handler] if name in ("", "app") else []
        logger.propagate = name not in ("", "app")
        if name in ("", "app"):
            logger.setLevel(level)
    # uvicorn access logs me query string (token) aata hai — filter se redact
    logging.getLogger("uvicorn.access").addFilter(RedactingFilter())
    logging.getLogger("uvicorn.access").handlers = [handler]
    logging.getLogger("uvicorn.access").propagate = False
