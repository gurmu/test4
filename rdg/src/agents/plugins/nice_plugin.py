"""
NICE inContact API Plugin (aiohttp)
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from semantic_kernel.functions import kernel_function

logger = logging.getLogger(__name__)


class NICEPlugin:
    """Semantic Kernel plugin for NICE inContact actions."""

    def __init__(self, api_url: str, timeout: int = 30):
        self._api_url = api_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    def _clean_phone(self, phone: str) -> str:
        cleaned = "".join(ch for ch in phone if ch.isdigit())
        return cleaned if len(cleaned) >= 10 else "9999999999"

    @kernel_function(name="create_callback", description="Create a callback in NICE inContact.")
    async def create_callback(
        self,
        skillId: str,
        phoneNumber: str,
        emailFrom: str,
        mediaType: str = "chat",
        emailBccAddress: str | None = None,
        firstName: str | None = None,
        lastName: str | None = None,
        priority: int = 5,
        notes: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "skillId": skillId,
            "mediaType": mediaType,
            "workItemQueueType": None,
            "isActive": True,
            "phoneNumber": self._clean_phone(phoneNumber),
            "emailFromEditable": True,
            "emailFrom": emailFrom,
            "emailBccAddress": emailBccAddress or emailFrom,
            "firstName": firstName,
            "lastName": lastName,
            "priority": priority,
            "targetAgentId": None,
            "notes": notes,
        }

        url = f"{self._api_url}/callback-queue"
        logger.info("NICE request: %s", url)

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
            "contactId": data.get("contactId"),
            "status": (data.get("data") or {}).get("status"),
            "message": data.get("message"),
            "full_response": data,
        }
