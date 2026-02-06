"""
Microsoft Teams Bot for ITSM Multi-Agent Assistant
"""

from botbuilder.core import ActivityHandler, TurnContext, MessageFactory
from botbuilder.schema import ChannelAccount
from agents.multi_agent_orchestrator import MultiAgentOrchestrator
import logging

logger = logging.getLogger(__name__)


class ITSMTeamsBot(ActivityHandler):
    """Teams bot that interfaces with the ITSM orchestrator"""
    
    def __init__(self):
        self.orchestrator = MultiAgentOrchestrator()
        logger.info("ITSM Teams Bot initialized")
    
    async def on_message_activity(self, turn_context: TurnContext):
        """Handle incoming messages from Teams"""
        try:
            # Get conversation ID
            conversation_id = turn_context.activity.conversation.id
            
            # Get user message
            user_message = turn_context.activity.text
            if turn_context.activity.attachments:
                attachment_names = [
                    a.name for a in turn_context.activity.attachments if a.name
                ]
                if attachment_names:
                    user_message += (
                        f"\n\nUser attached files: {', '.join(attachment_names)}."
                        " Attachments are not analyzed yet."
                    )
            logger.info(f"Received message: {user_message[:50]}...")
            
            # Process with orchestrator
            response = await self.orchestrator.run_conversation(user_message, conversation_id)
            
            # Send response back to Teams
            await turn_context.send_activity(MessageFactory.text(response))
            logger.info("Response sent to Teams")
            
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            await turn_context.send_activity(
                MessageFactory.text(f"Sorry, I encountered an error: {str(e)}")
            )
    
    async def on_members_added_activity(
        self, members_added: list[ChannelAccount], turn_context: TurnContext
    ):
        """Handle when bot is added to a conversation"""
        for member in members_added:
            if member.id != turn_context.activity.recipient.id:
                welcome_message = (
                    "Hello! I'm your ITSM Assistant. I can help with:\n\n"
                    "• IT support issues (VPN, login, network, tickets)\n"
                    "How can I help you today?"
                )
                await turn_context.send_activity(MessageFactory.text(welcome_message))
                logger.info("Welcome message sent")

