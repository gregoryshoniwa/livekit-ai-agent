from dotenv import load_dotenv
import os
import asyncio
import signal

from livekit import agents, rtc
from livekit.agents import AgentServer,AgentSession, Agent, room_io, ChatContext
from livekit.plugins import noise_cancellation, silero, google, openai
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from prompts import AGENT_INSTRUCTION, SESSION_INSTRUCTION
from tools import get_weather, search_web, send_email
from mem0 import AsyncMemoryClient
import json
import logging

load_dotenv(".env.local")

# Initialize Mem0 client
mem0_client = AsyncMemoryClient(api_key=os.getenv("MEM0_API_KEY"))

# Global variables to track session for cleanup
current_assistant = None
current_user_name = None
current_memory_str = ''


async def shutdown_hook(chat_ctx: ChatContext, mem0: AsyncMemoryClient, user_id: str, memory_str: str = ''):
    """
    Save the chat context to memory when shutting down.
    
    Args:
        chat_ctx: The chat context containing conversation history
        mem0: The Mem0 client instance
        user_id: The user identifier for storing memories
        memory_str: The memory string that was loaded at the start to avoid re-saving it
    """
    logging.info("Shutting down, saving chat context to memory...")
    
    messages_formatted = []
    
    logging.info(f"Chat context messages: {chat_ctx.items}")
    
    for item in chat_ctx.items:
        # Handle content that could be a list or string
        content_str = ''.join(item.content) if isinstance(item.content, list) else str(item.content)
        
        # Skip if this content contains the loaded memory string (avoid re-saving past memories)
        if memory_str and memory_str in content_str:
            continue
        
        # Only save user and assistant messages (skip system messages)
        if item.role in ['user', 'assistant']:
            messages_formatted.append({
                "role": item.role,
                "content": content_str.strip()
            })
    
    if messages_formatted:
        logging.info(f"Saving {len(messages_formatted)} messages to memory for user {user_id}")
        try:
            result = await mem0.add(messages_formatted, user_id=user_id)
            logging.info(f"Memory saved successfully: {result}")
            logging.info("Chat context saved to memory.")
        except Exception as e:
            logging.error(f"Failed to save chat context to memory: {e}")
    else:
        logging.info("No messages to save to memory.")


class Assistant(Agent):
    def __init__(self, chat_ctx: ChatContext | None = None, model_type: str = "google") -> None:
        # Select the LLM based on model_type
        if model_type == "openai":
            # Use OpenAI-compatible LLM targeting Ollama's API; pair with Google TTS for audio replies
            llm = openai.LLM(
                model=os.getenv("OPENAI_MODEL", "llama3.2:latest"),
                base_url=os.getenv("OPENAI_BASE_URL", "http://localhost:11434/v1"),
                api_key=os.getenv("OPENAI_API_KEY", "ollama"),
            )
            super().__init__(
                instructions=AGENT_INSTRUCTION,
                llm=llm,
                tts=google.TTS(),
                tools=[
                    get_weather,
                    search_web,
                    send_email,
                ],
                chat_ctx=chat_ctx,
            )
        else:
            # Google Realtime Model handles its own audio
            llm = google.beta.realtime.RealtimeModel(
                voice="Aoede",
                temperature=0.8,
            )
            super().__init__(
                instructions=AGENT_INSTRUCTION,
                llm=llm,
                tools=[
                    get_weather,
                    search_web,
                    send_email,
                ],
                chat_ctx=chat_ctx,
            )
        
        self.model_type = model_type

server = AgentServer()

@server.rtc_session()
async def my_agent(ctx: agents.JobContext):
    global current_assistant, current_user_name, current_memory_str
    
    # Initialize session first
    session = AgentSession(
        stt="assemblyai/universal-streaming:en",
        tts="cartesia/sonic-3:9626c31c-bec5-4cca-baa8-f8ba9e84c8bc",
        vad=silero.VAD.load(),
        turn_detection=MultilingualModel(),
    )
    
    # Wait for participant to connect
    await ctx.connect()
    
    # Variables to track user name and memories
    user_name = None
    memory_str = ''
    memories_loaded = False
    
    # Track video state
    video_enabled = False
    current_model_type = "openai"  # Start with OpenAI (no video by default)
    
    # Create assistant with empty ChatContext - start with OpenAI
    assistant = Assistant(chat_ctx=ChatContext(), model_type="openai")
    
    # Store globally for signal handler
    current_assistant = assistant

    await session.start(
        room=ctx.room,
        agent=assistant,
        room_options=room_io.RoomOptions(
            video_input=True,
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: noise_cancellation.BVCTelephony() if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP else noise_cancellation.BVC(),
            ),
        ),
    )
    
    # Ask for user's name first
    await session.generate_reply(
        instructions="""Greet the user warmly and ask for their name in a friendly, conversational way. 
        For example: 'Hello! Welcome to Steward Bank. I'm Batsi, your virtual assistant. May I have your name please?' 
        Once they tell you their name, acknowledge it and proceed to help them with their banking needs."""
    )
    
    # Monitor for user's name in the chat and load memories
    original_chat_ctx_items = []
    
    async def check_and_load_memories():
        nonlocal user_name, memory_str, memories_loaded
        
        if memories_loaded or not hasattr(assistant, 'chat_ctx') or not assistant.chat_ctx:
            return
            
        # Look for the first user message after the greeting
        current_items = list(assistant.chat_ctx.items)
        
        # Find new user messages
        for item in current_items:
            if item.role == "user" and item not in original_chat_ctx_items:
                # This is the user's response with their name
                content = item.content.strip() if isinstance(item.content, str) else ''.join(item.content)
                
                # Extract just the name from common patterns
                # e.g., "My name is Gregory" -> "Gregory"
                # e.g., "I'm John" -> "John"  
                # e.g., "Gregory" -> "Gregory"
                import re
                name_patterns = [
                    r"(?:my name is|i'm|i am|it's|name is|this is|call me)\s+([a-zA-Z]+)",
                    r"^([a-zA-Z]+)$",  # Just a single name
                    r"([a-zA-Z]+)\s*$"  # Name at the end
                ]
                
                extracted_name = content
                for pattern in name_patterns:
                    match = re.search(pattern, content, re.IGNORECASE)
                    if match:
                        extracted_name = match.group(1).strip()
                        break
                
                user_name = extracted_name
                logging.info(f"User identified as: {user_name}")
                memories_loaded = True
                
                # Update global variables
                current_user_name = user_name
                
                # Now retrieve memories for this user
                try:
                    results = await mem0_client.get_all(user_id=user_name)
            
                    if results:
                        memories = [
                            {
                                "memory": result["memory"],
                                "updated_at": result.get("updated_at", "")
                            }
                            for result in results
                        ]
                        memory_str = json.dumps(memories)
                        current_memory_str = memory_str
                        logging.info(f"Retrieved {len(results)} memories for {user_name}")
                        logging.info(f"Memory contents: {memory_str}")
                        
                        # Format memories in a natural, readable way for the AI
                        memory_lines = [f"- {result['memory']}" for result in results]
                        memory_content = f"""Previous conversation memories about {user_name}:

{chr(10).join(memory_lines)}

Use these memories to personalize your responses and remember past conversations with {user_name}."""
                        
                        # Add memories to the chat context using the proper API
                        if hasattr(assistant, 'chat_ctx') and assistant.chat_ctx:
                            # Create a copy and add the memory message
                            ctx_copy = assistant.chat_ctx.copy()
                            ctx_copy.add_message(
                                role="system",
                                content=memory_content
                            )
                            # Update the agent's chat context (MUST await this!)
                            await assistant.update_chat_ctx(ctx_copy)
                            logging.info(f"Memories loaded into chat context: {memory_content}")
                    else:
                        logging.info(f"No existing memories found for {user_name}")
                except Exception as e:
                    logging.error(f"Failed to retrieve memories for {user_name}: {e}")
                break
    
    # Periodically check for user's name
    import asyncio
    async def memory_loader_task():
        while not memories_loaded:
            await check_and_load_memories()
            await asyncio.sleep(1)  # Check every second
        logging.info("Memory loader task completed")
    
    # Start the memory loader task
    asyncio.create_task(memory_loader_task())
    
    # Monitor video track state and switch models
    async def video_monitor_task():
        nonlocal assistant, video_enabled, current_model_type
        
        while True:
            try:
                # Check for local participant's video track
                local_participant = ctx.room.local_participant
                video_track = None
                
                for track_pub in local_participant.track_publications.values():
                    if track_pub.source == rtc.TrackSource.SOURCE_CAMERA:
                        video_track = track_pub.track
                        break
                
                # Determine if video is currently enabled
                new_video_enabled = video_track is not None and not video_track.muted
                
                # If video state changed, switch models
                if new_video_enabled != video_enabled:
                    video_enabled = new_video_enabled
                    new_model_type = "google" if video_enabled else "openai"
                    
                    if new_model_type != current_model_type:
                        logging.info(f"Video state changed: {video_enabled}. Switching from {current_model_type} to {new_model_type}")
                        current_model_type = new_model_type
                        
                        # Stop current session and create new assistant with different model
                        old_chat_ctx = assistant.chat_ctx.copy() if hasattr(assistant, 'chat_ctx') and assistant.chat_ctx else ChatContext()
                        
                        # Create new assistant with the appropriate model
                        assistant = Assistant(chat_ctx=old_chat_ctx, model_type=new_model_type)
                        current_assistant = assistant
                        
                        # Update the session with the new assistant
                        session._agent = assistant
                        
                        logging.info(f"Switched to {new_model_type.upper()} model successfully")
                        
            except Exception as e:
                logging.error(f"Error in video monitor task: {e}")
            
            await asyncio.sleep(0.5)  # Check every 500ms
    
    # Start the video monitor task
    asyncio.create_task(video_monitor_task())
    
    # Set up shutdown hook to save conversation when user disconnects
    def on_participant_disconnected(participant: rtc.RemoteParticipant):
        logging.info(f"Participant disconnected: {participant.identity or participant.sid}")
        async def _save():
            if user_name:
                logging.info(f"User {user_name} disconnected, saving conversation to memory...")
                try:
                    if hasattr(assistant, 'chat_ctx') and assistant.chat_ctx:
                        await shutdown_hook(assistant.chat_ctx, mem0_client, user_name, memory_str)
                        logging.info(f"Successfully saved conversation for {user_name}")
                    else:
                        logging.warning("Assistant doesn't have chat_ctx attribute")
                except Exception as e:
                    logging.error(f"Error saving memories: {e}")
            else:
                logging.info("User disconnected before providing name, no memories to save")
        asyncio.create_task(_save())
    ctx.room.on("participant_disconnected", on_participant_disconnected)

    # Handle cleanup on session end (for console mode)
    def on_room_disconnected():
        logging.info("Room disconnected, attempting to save memories...")
        async def _save():
            if user_name:
                try:
                    if hasattr(assistant, 'chat_ctx') and assistant.chat_ctx:
                        await shutdown_hook(assistant.chat_ctx, mem0_client, user_name, memory_str)
                        logging.info(f"Successfully saved conversation for {user_name} on room disconnect")
                except Exception as e:
                    logging.error(f"Error saving memories on room disconnect: {e}")
        asyncio.create_task(_save())
    ctx.room.on("disconnected", on_room_disconnected)
    
    # Monitor the session state and save when it closes
    async def session_monitor():
        try:
            # Wait for the session to be closed
            while session._agent is not None:
                await asyncio.sleep(1)
        except Exception:
            pass
        
        # Session is closing, save conversation
        logging.info("Session monitor detected closure, saving conversation...")
        if user_name:
            try:
                if hasattr(assistant, 'chat_ctx') and assistant.chat_ctx:
                    await shutdown_hook(assistant.chat_ctx, mem0_client, user_name, memory_str)
                    logging.info(f"Successfully saved conversation for {user_name} via monitor")
            except Exception as e:
                logging.error(f"Error saving memories via monitor: {e}")
    
    # Start session monitor
    asyncio.create_task(session_monitor())
    
    # Register cleanup callback for when context shuts down
    async def cleanup_callback():
        logging.info("Context shutdown callback triggered, saving conversation...")
        if user_name:
            try:
                if hasattr(assistant, 'chat_ctx') and assistant.chat_ctx:
                    await shutdown_hook(assistant.chat_ctx, mem0_client, user_name, memory_str)
                    logging.info(f"Successfully saved conversation for {user_name} via cleanup callback")
                else:
                    logging.warning("Assistant has no chat_ctx in cleanup")
            except Exception as e:
                logging.error(f"Error saving memories in cleanup: {e}")
                import traceback
                traceback.print_exc()
        else:
            logging.info("No user name available in cleanup callback")
    
    # Add the cleanup callback
    ctx.add_shutdown_callback(cleanup_callback)


# Signal handler for graceful shutdown
def signal_handler(sig, frame):
    logging.info(f"Received signal {sig}, saving conversation...")
    logging.info(f"Current user: {current_user_name}, Assistant exists: {current_assistant is not None}")
    if current_user_name and current_assistant:
        try:
            logging.info("Attempting to save via signal handler...")
            # Run the async shutdown in a new event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            if hasattr(current_assistant, 'chat_ctx') and current_assistant.chat_ctx:
                loop.run_until_complete(
                    shutdown_hook(current_assistant.chat_ctx, mem0_client, current_user_name, current_memory_str)
                )
                logging.info(f"Successfully saved conversation for {current_user_name} on exit")
            else:
                logging.warning("Assistant has no chat_ctx")
            loop.close()
        except Exception as e:
            logging.error(f"Error saving memories on exit: {e}")
            import traceback
            traceback.print_exc()
    else:
        logging.info(f"No active conversation to save (user_name: {current_user_name}, assistant: {current_assistant is not None})")
    exit(0)


if __name__ == "__main__":
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    agents.cli.run_app(server)