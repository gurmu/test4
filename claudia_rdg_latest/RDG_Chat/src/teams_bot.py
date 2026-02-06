"""
Microsoft Teams Bot for ITSM Multi-Agent Assistant

Interfaces with the hybrid MultiAgentOrchestrator.  Supports multi-turn
conversations where final=false means the bot is waiting for the user
to reply (e.g., "Reply with 1 or 2").  Conversation state is tracked
in Cosmos DB + in-memory cache so it survives across Teams activities.
"""

from botbuilder.core import ActivityHandler, TurnContext, MessageFactory
from botbuilder.schema import Activity, ActivityTypes, ChannelAccount
from agents.multi_agent_orchestrator import MultiAgentOrchestrator
import logging

logger = logging.getLogger(__name__)


class ITSMTeamsBot(ActivityHandler):
    """Teams bot — delegates to the hybrid orchestrator on every turn."""

    def __init__(self):
        self.orchestrator = MultiAgentOrchestrator()
        logger.info("ITSM Teams Bot initialized (hybrid orchestrator)")

    async def on_message_activity(self, turn_context: TurnContext):
        """Handle incoming messages from Teams."""
        try:
            conversation_id = turn_context.activity.conversation.id

            # Build user message
            user_message = turn_context.activity.text or ""
            if turn_context.activity.attachments:
                names = [
                    a.name for a in turn_context.activity.attachments if a.name
                ]
                if names:
                    user_message += (
                        f"\n\nUser attached files: {', '.join(names)}."
                        " Attachments are not analyzed yet."
                    )

            if not user_message.strip():
                await turn_context.send_activity(
                    MessageFactory.text("Please enter a message so I can help you.")
                )
                return

            logger.info(
                f"Message from conv={conversation_id}: {user_message[:80]}..."
            )

            # Show typing indicator while processing
            await turn_context.send_activity(
                Activity(type=ActivityTypes.typing)
            )

            # Orchestrator handles KB search, LLM reasoning, invariant
            # enforcement, and multi-turn state — all in one call.
            response = await self.orchestrator.run_conversation(
                user_message, conversation_id
            )

            # Send plain-text response to Teams
            await turn_context.send_activity(MessageFactory.text(response))
            logger.info("Response sent to Teams")

        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            await turn_context.send_activity(
                MessageFactory.text(
                    "Sorry, I encountered an error processing your request. "
                    "Please try again or contact the help desk directly."
                )
            )

    async def on_members_added_activity(
        self, members_added: list[ChannelAccount], turn_context: TurnContext
    ):
        """Handle when bot is added to a conversation."""
        for member in members_added:
            if member.id != turn_context.activity.recipient.id:
                welcome = (
                    "Hello! I'm your ITSM Assistant. I can help with:\n\n"
                    "- IT support issues (VPN, login, network, software)\n"
                    "- Searching the ITSM Knowledge Base for solutions\n"
                    "- Creating incidents or callback requests\n\n"
                    "How can I help you today?"
                )
                await turn_context.send_activity(MessageFactory.text(welcome))
                logger.info("Welcome message sent")
