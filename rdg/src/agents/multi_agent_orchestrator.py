"""
Semantic Kernel multi-agent orchestration (GCC).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime

from semantic_kernel import Kernel
from semantic_kernel.agents.chat_completion.chat_completion_agent import ChatCompletionAgent
from semantic_kernel.agents.group_chat.agent_group_chat import AgentGroupChat
from semantic_kernel.agents.strategies import TerminationStrategy
from semantic_kernel.connectors.ai.open_ai.services.azure_chat_completion import (
    AzureChatCompletion,
)

from agents.config.agent_config import AgentConfig
from agents.plugins.itsm_search_plugin import ITSMSearchPlugin
from agents.plugins.ivanti_plugin import IvantiPlugin
from agents.plugins.nice_plugin import NICEPlugin
from agents.chat_history.cosmos_chat_history import CosmosDBChatHistory

logger = logging.getLogger(__name__)


@dataclass
class TicketRequest:
    subject: str
    description: str
    user_email: str
    phone_number: str
    user_first_name: str | None = None
    user_last_name: str | None = None
    additional_context: str | None = None


@dataclass
class TriageResult:
    priority: str
    category: str
    team: str
    status: str = "success"
    orchestrator_summary: str = ""
    timestamp: str | None = None

    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.utcnow().isoformat()


class FinalResolutionTerminationStrategy(TerminationStrategy):
    """Stop when orchestrator returns a final resolution JSON payload."""

    async def should_agent_terminate(self, agent: ChatCompletionAgent, history) -> bool:
        if agent.name != "Orchestrator":
            return False
        if not history:
            return False
        last = history[-1].content or ""
        return "\"final\": true" in last or "FINAL_RESOLUTION" in last


class MultiAgentOrchestrator:
    """Semantic Kernel AgentGroupChat orchestrator."""

    def __init__(self, config: AgentConfig | None = None):
        self.config = config or AgentConfig()
        self.config.validate()

        self._history_store = CosmosDBChatHistory(
            endpoint=self.config.cosmos_endpoint,
            key=self.config.cosmos_key,
            database_name=self.config.cosmos_database,
            container_name=self.config.cosmos_container,
        )

        self._orchestrator_agent = self._build_orchestrator_agent()
        self._itsm_agent = self._build_itsm_agent()
        self._ivanti_agent = self._build_ivanti_agent()
        self._nice_agent = self._build_nice_agent()

    def _build_kernel(self) -> Kernel:
        kernel = Kernel()
        service = AzureChatCompletion(
            service_id="chat",
            deployment_name=self.config.azure_openai_deployment,
            endpoint=self.config.azure_openai_endpoint,
            api_key=self.config.azure_openai_api_key,
            api_version=self.config.azure_openai_api_version,
        )
        kernel.add_service(service)
        return kernel

    def _build_orchestrator_agent(self) -> ChatCompletionAgent:
        kernel = self._build_kernel()
        instructions = (
            "You are the Orchestrator for an ITSM multi-agent system. "
            "Delegate to ITSM, Ivanti, and NICE agents as needed. "
            "Return a JSON object with keys: priority, category, team, summary, "
            "actions (array), final (bool). "
            "Set final=true ONLY when you have a complete resolution for the user. "
            "When final=true, include FINAL_RESOLUTION in the message."
        )
        return ChatCompletionAgent(
            name="Orchestrator",
            instructions=instructions,
            kernel=kernel,
            service=kernel.get_service("chat"),
        )

    def _build_itsm_agent(self) -> ChatCompletionAgent:
        kernel = self._build_kernel()
        kernel.add_plugin(
            ITSMSearchPlugin(
                endpoint=self.config.azure_search_endpoint,
                index_name=self.config.azure_search_index,
                api_key=self.config.azure_search_key,
                content_field=self.config.kb_content_field,
            ),
            plugin_name="itsm",
        )
        instructions = (
            "You are the ITSM agent. Use the itsm.search_kb tool to retrieve guidance. "
            "Return concise summaries and cite KB snippets in your response."
        )
        return ChatCompletionAgent(
            name="ITSM",
            instructions=instructions,
            kernel=kernel,
            service=kernel.get_service("chat"),
        )

    def _build_ivanti_agent(self) -> ChatCompletionAgent:
        kernel = self._build_kernel()
        kernel.add_plugin(IvantiPlugin(self.config.ivanti_api_url), plugin_name="ivanti")
        instructions = (
            "You are the Ivanti agent. Use ivanti.create_incident when asked to create an incident. "
            "Return the incident number and status."
        )
        return ChatCompletionAgent(
            name="Ivanti",
            instructions=instructions,
            kernel=kernel,
            service=kernel.get_service("chat"),
        )

    def _build_nice_agent(self) -> ChatCompletionAgent:
        kernel = self._build_kernel()
        kernel.add_plugin(NICEPlugin(self.config.nice_api_url), plugin_name="nice")
        instructions = (
            "You are the NICE agent. Use nice.create_callback to schedule callbacks. "
            "Return the contactId and status."
        )
        return ChatCompletionAgent(
            name="NICE",
            instructions=instructions,
            kernel=kernel,
            service=kernel.get_service("chat"),
        )

    async def run_ticket_triage(self, ticket: TicketRequest, conversation_id: str) -> TriageResult:
        chat = AgentGroupChat(
            agents=[self._orchestrator_agent, self._itsm_agent, self._ivanti_agent, self._nice_agent],
            termination_strategy=FinalResolutionTerminationStrategy(),
        )

        history = self._history_store.load(conversation_id)
        chat.chat_history = history

        user_message = (
            "Ticket:\n"
            f"Subject: {ticket.subject}\n"
            f"Description: {ticket.description}\n"
            f"Email: {ticket.user_email}\n"
            f"Phone: {ticket.phone_number}\n"
            f"Name: {ticket.user_first_name or ''} {ticket.user_last_name or ''}\n"
            f"Additional Context: {ticket.additional_context or ''}"
        )

        chat.chat_history.add_user_message(user_message)
        response = ""
        async for message in chat.invoke():
            response = message.content or ""

        self._history_store.append(conversation_id, "user", user_message)
        self._history_store.append(conversation_id, "assistant", response)

        try:
            payload = json.loads(response)
        except json.JSONDecodeError:
            payload = {"summary": response, "priority": "Unknown", "category": "Unknown", "team": "Unknown"}

        return TriageResult(
            priority=payload.get("priority", "Unknown"),
            category=payload.get("category", "Unknown"),
            team=payload.get("team", "Unknown"),
            orchestrator_summary=payload.get("summary", ""),
            status="success",
        )

    async def run_conversation(self, user_input: str, conversation_id: str) -> str:
        chat = AgentGroupChat(
            agents=[self._orchestrator_agent, self._itsm_agent, self._ivanti_agent, self._nice_agent],
            termination_strategy=FinalResolutionTerminationStrategy(),
        )

        history = self._history_store.load(conversation_id)
        chat.chat_history = history

        chat.chat_history.add_user_message(user_input)
        response = ""
        async for message in chat.invoke():
            response = message.content or ""

        self._history_store.append(conversation_id, "user", user_input)
        self._history_store.append(conversation_id, "assistant", response)

        return response


def run_ticket(ticket: TicketRequest, conversation_id: str) -> TriageResult:
    orchestrator = MultiAgentOrchestrator()
    return asyncio.run(orchestrator.run_ticket_triage(ticket, conversation_id))
