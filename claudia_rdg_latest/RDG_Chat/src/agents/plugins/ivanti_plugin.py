"""
Ivanti API Plugin (aiohttp)

JSON Serialization Fix:
- All parameters are explicitly converted to plain Python strings
  before building the HTTP payload.
- AzureChatCompletion objects, FunctionResult wrappers, and any other
  Semantic Kernel types are safely converted via _to_plain_str().
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from semantic_kernel.functions import kernel_function

logger = logging.getLogger(__name__)


def _to_plain_str(value: Any) -> str:
    """
    Convert *any* value to a plain Python str.

    Handles Semantic Kernel objects (AzureChatCompletion results,
    FunctionResult, ChatMessageContent, etc.) that are NOT JSON-
    serializable by extracting their text representation first.
    """
    if value is None:
        return ""
    # Already a plain str → fast path
    if type(value) is str:
        return value
    # If it has a .value or .content attribute (SK wrapper types), unwrap
    for attr in ("value", "content", "result"):
        inner = getattr(value, attr, None)
        if inner is not None and isinstance(inner, str):
            return inner
    # Fall back to str()
    return str(value)


class IvantiPlugin:
    """Semantic Kernel plugin for Ivanti incident actions."""

    def __init__(self, api_url: str, timeout: int = 30):
        self._api_url = api_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    @kernel_function(name="create_incident", description="Create an incident in Ivanti ITSM.")
    async def create_incident(
        self,
        subject: str,
        symptom: str,
        impact: str,
        category: str,
        service: str,
        owner_team: str,
        status: str = "Logged",
    ) -> dict[str, Any]:
        """
        Create incident in Ivanti ITSM.

        IMPORTANT: Every parameter is forced to a plain Python string before
        the JSON payload is built, preventing serialization errors when
        Semantic Kernel passes wrapped objects.
        """
        # ---- Robust type conversion ----
        try:
            subject_str = _to_plain_str(subject)
            symptom_str = _to_plain_str(symptom)
            impact_str = _to_plain_str(impact)
            category_str = _to_plain_str(category)
            service_str = _to_plain_str(service)
            owner_team_str = _to_plain_str(owner_team)
            status_str = _to_plain_str(status) or "Logged"
        except Exception as e:
            logger.error(f"Type conversion error: {e}")
            return {"success": False, "error": f"Invalid parameter types: {e}"}

        # ---- Validate all are real strings ----
        for param_name, param_value in [
            ("subject", subject_str),
            ("symptom", symptom_str),
            ("impact", impact_str),
            ("category", category_str),
            ("service", service_str),
            ("owner_team", owner_team_str),
        ]:
            if not isinstance(param_value, str):
                return {
                    "success": False,
                    "error": f"{param_name} must be a string, got {type(param_value)}",
                }

        # ---- Build plain-dict payload (guaranteed JSON-safe) ----
        payload = {
            "subject": subject_str,
            "symptom": symptom_str,
            "status": status_str,
            "impact": impact_str,
            "category": category_str,
            "service": service_str,
            "owner_team": owner_team_str,
        }

        url = f"{self._api_url}/incidents"
        logger.info("Ivanti request: %s  payload_keys=%s", url, list(payload.keys()))

        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.post(url, json=payload) as response:
                    text = await response.text()
                    if response.status >= 400:
                        logger.error("Ivanti HTTP %s: %s", response.status, text[:500])
                        return {"success": False, "status_code": response.status, "error": text}
                    try:
                        data = await response.json()
                    except Exception:
                        data = {"raw": text}

            return {
                "success": True,
                "incident_id": data.get("incident_id"),
                "incident_number": (data.get("data") or {}).get("IncidentNumber"),
                "message": data.get("message"),
                "full_response": data,
            }
        except Exception as e:
            logger.error(f"Ivanti API call failed: {e}")
            return {"success": False, "error": str(e)}
