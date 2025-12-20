# AI Voice Agent - Dynamic Model Switching

This agent automatically switches between two LLM models based on video state:

- **Video OFF** → OpenAI plugin pointed at Ollama (OpenAI-compatible endpoint)
- **Video ON** → Google Realtime API (with multimodal capabilities)

## Setup Instructions

### 1. Install Python Dependencies

```bash
cd ai-voice-agent-back
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Copy `.env.local.example` to `.env.local` and fill in your credentials:

```bash
cp .env.local.example .env.local
```

Required variables:
- `MEM0_API_KEY`: Your Mem0 API key
- `GOOGLE_APPLICATION_CREDENTIALS`: Path to Google Cloud credentials JSON
- `OPENAI_API_KEY`: Dummy value (e.g., `ollama`) for OpenAI-compatible calls
- `OPENAI_BASE_URL`: Your Ollama OpenAI-compatible endpoint, default `http://localhost:11434/v1`
- `OPENAI_MODEL`: Ollama model name, default `llama3.2:latest`
- `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`: LiveKit credentials

### 3. Run the Agent

```bash
python3 agent.py dev
```

## How It Works

The agent monitors the local participant's camera track in real-time:

1. **Initial State**: Starts with OpenAI plugin against Ollama (no video)
2. **Camera Enabled**: Automatically switches to Google Realtime API
3. **Camera Disabled**: Switches back to OpenAI plugin against Ollama
4. **Seamless Transition**: Chat context is preserved during switches

## Benefits

- **Cost Savings**: Use free local Ollama when video is not needed
- **Better Performance**: Google Realtime API handles video/multimodal inputs
- **Automatic**: No manual intervention required
- **Context Preservation**: Conversation history maintained across switches

## Model Customization

To use a different Ollama model, modify `agent.py`:

```python
llm = ollama.LLM(model="llama3.2:latest")  # Change to your preferred model
```

Available Ollama models:
- llama3.2:latest
- llama3.1:latest
- mistral:latest
- codellama:latest
- And many more...

## Troubleshooting

### Ollama Connection Issues

If you see connection errors:

1. Check if Ollama is running: `curl http://localhost:11434`
2. Verify the model is pulled: `ollama list`
3. Check Ollama logs: `ollama logs`

### Model Not Switching

If the model doesn't switch when toggling camera:

1. Check backend logs for "Video state changed" messages
2. Verify camera permissions in browser
3. Ensure LiveKit connection is stable

## Performance Notes

- **OpenAI plugin (Ollama backend)**: Text-first interactions when video is off
- **Google Realtime**: Required for video analysis, cloud-based
- **Switch Time**: Typically < 1 second, transparent to user
