"""
Ivanti API Plugin (aiohttp)
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from semantic_kernel.functions import kernel_function

logger = logging.getLogger(__name__)


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
        payload = {
            "subject": subject,
            "symptom": symptom,
            "status": status,
            "impact": impact,
            "category": category,
            "service": service,
            "owner_team": owner_team,
        }

        url = f"{self._api_url}/incidents"
        logger.info("Ivanti request: %s", url)

        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            async with session.post(url, json=payload) as response:
                text = await response.text()
                if response.status >= 400:
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
