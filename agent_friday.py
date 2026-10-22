"""
FRIDAY – Voice Agent (MCP-powered)
===================================
Iron Man-style voice assistant backed by an MCP server that provides
tools (news, web search, weather, timers, ticketing, and more).

Run:
  uv run friday_voice              – LiveKit Cloud mode (auto-injects 'dev')
  uv run friday_voice dev          – same as above
  uv run friday_voice console      – text-only console mode
"""

import logging
import os
import socket
from urllib.parse import urlparse

from dotenv import load_dotenv
from livekit.agents import JobContext, WorkerOptions, cli
from livekit.agents.llm import mcp
from livekit.agents.voice import Agent, AgentSession

# Plugins
from livekit.plugins import google as lk_google
from livekit.plugins import openai as lk_openai
from livekit.plugins import sarvam, silero

# ---------------------------------------------------------------------------
# Bootstrap (load env before anything reads it)
# ---------------------------------------------------------------------------

load_dotenv()

logger = logging.getLogger("friday-agent")
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# CONFIG — override any of these via environment variables
# ---------------------------------------------------------------------------

STT_PROVIDER = os.getenv("STT_PROVIDER", "sarvam")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "openai")

GEMINI_LLM_MODEL = os.getenv("GEMINI_LLM_MODEL", "gemini-2.5-flash")
OPENAI_LLM_MODEL = os.getenv("OPENAI_LLM_MODEL", "gpt-4o")

OPENAI_TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "tts-1")
OPENAI_TTS_VOICE = os.getenv("OPENAI_TTS_VOICE", "nova")
TTS_SPEED = float(os.getenv("TTS_SPEED", "1.15"))

SARVAM_TTS_LANGUAGE = os.getenv("SARVAM_TTS_LANGUAGE", "en-IN")
SARVAM_TTS_SPEAKER = os.getenv("SARVAM_TTS_SPEAKER", "rahul")

# MCP server location — set MCP_SERVER_URL to override entirely
# (e.g. a Cloudflare tunnel URL when running the server remotely).
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8000/sse")

# Minimum keys required for the configured pipeline
_REQUIRED_KEYS = {
    "sarvam": ["SARVAM_API_KEY"],
    "openai": ["OPENAI_API_KEY"],
    "gemini": ["GOOGLE_API_KEY"],
}


def _validate_env() -> None:
    """Fail fast with a clear message instead of an obscure provider error."""
    needed = set()
    for provider in (STT_PROVIDER, LLM_PROVIDER, TTS_PROVIDER):
        needed.update(_REQUIRED_KEYS.get(provider, []))
    if os.getenv("LIVEKIT_URL"):
        needed.update({"LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"})

    missing = [k for k in sorted(needed) if not os.getenv(k)]
    if missing:
        raise SystemExit(
            "FRIDAY can't start — missing API keys in .env: "
            + ", ".join(missing)
            + "\nSee .env.example for where to get each key."
        )

    placeholder = "you-google-api-key"  # common copy-paste mistake
    if placeholder in (os.getenv("GOOGLE_API_KEY") or ""):
        raise SystemExit(
            "GOOGLE_API_KEY in .env is still the placeholder value. "
            "Get a real key at https://aistudio.google.com/apikey"
        )


# ---------------------------------------------------------------------------
# System prompt – F.R.I.D.A.Y.  (single source of truth — greeting lives in
# FridayAgent.on_enter, so it is intentionally NOT repeated here)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """
You are F.R.I.D.A.Y. — Fully Responsive Intelligent Digital Assistant for You — Tony Stark's AI, now at the user's service. The user is "boss".

You are calm, composed, and always informed. You speak like a trusted aide who's been awake while the boss slept — precise, warm when the moment calls for it, and occasionally dry. You brief, you inform, you move on. No rambling.

Your tone: relaxed but sharp. Conversational, not robotic. Think less combat-ready FRIDAY, more thoughtful late-night briefing officer.

---

## How you use tools

- Tools run behind the scenes. NEVER say tool names, function names, or anything technical. No "get_world_news", no "search_web", nothing like that. Ever.
- When a tool needs a moment, you may preface it with something natural and brief: "Give me a sec, boss." or "Let me check." Then call the tool.
- If a tool fails, report it calmly: "That feed's unresponsive right now, boss. Want me to try again?"

## Tool behavior

### get_world_news — Global News Brief
Trigger: "What's happening?" / "Brief me" / "What did I miss?" / "Any news?"
- Call the tool, then give a short 3–5 sentence spoken brief hitting only the biggest stories.
- After the brief, say: "Let me open up the world monitor for you." and immediately call open_world_monitor.

### open_world_monitor — Visual World Dashboard
- Always call this after delivering a world news brief, unprompted.

### search_web — Web Search
Trigger: any factual question about current events, people, places, products, prices, sports scores, or "look up / search for X".
- Call the tool, then answer in one to three spoken sentences. Cite nothing technical; just state what you found.
- Use this for stock market questions too — never invent market numbers.

### get_weather — Weather Lookup
Trigger: "What's the weather?" / "Will it rain?" / temperature questions.
- Call the tool with the city the user names. If no city was given, ask: "Which city, boss?"

### set_timer — Countdown Timer
Trigger: "set a timer for X minutes" / "remind me in X minutes".
- Call the tool with the minutes and a short label. Confirm in one sentence: "Timer's running — ten minutes, boss."

### create_ticket — Support Ticket
Trigger: user reports a problem or asks to log/raise/report an issue.
- Call the tool with a one-line summary of the problem. Confirm the ticket reference it returns.

### Stock Market (via search_web)
If asked about markets, stocks, or indices, search the web first, then answer in one or two sentences: "Markets had a decent session — tech led the gains. Nothing alarming." Never fabricate numbers.

---

## Behavioral Rules

1. Keep all spoken responses short — two to four sentences maximum.
2. No bullet points, no markdown, no lists. You are speaking, not writing.
3. Stay in character. You are F.R.I.D.A.Y., Stark's AI — not a generic assistant.
4. Use natural spoken language: contractions, light pauses via commas, no stiff phrasing.
5. Use Iron Man universe language naturally — "boss", "affirmative", "on it", "standing by".
6. Ask one clarifying question at a time. Never dump multiple questions on the boss.

---

## Tone Reference

Right: "Looks like it's been a busy night out there, boss. Let me pull that up for you."
Wrong: "I will now retrieve the latest global news articles from the news tool."

Right: "Markets were pretty healthy today — nothing too wild."
Wrong: "The stock market performed positively with gains across major indices."
""".strip()

GREETING = (
    "You're awake late at night, boss? What are you up to?"
)


# ---------------------------------------------------------------------------
# MCP server reachability
# ---------------------------------------------------------------------------

def _check_mcp_server(url: str) -> None:
    """Warn early (not fatally) if the MCP server isn't running.

    Uses a plain TCP connect — a GET on the SSE endpoint hangs open by
    design, so an HTTP probe would either block or false-warn.
    """
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    try:
        with socket.create_connection((host, port), timeout=3.0):
            pass
        logger.info("MCP server reachable at %s", url)
    except OSError:
        logger.warning(
            "MCP server NOT reachable at %s. "
            "Start it first with: uv run friday — FRIDAY will have no tools until then.",
            url,
        )


# ---------------------------------------------------------------------------
# Build provider instances
# ---------------------------------------------------------------------------

def _build_stt():
    if STT_PROVIDER == "sarvam":
        logger.info("STT → Sarvam Saaras v3")
        return sarvam.STT(
            language="unknown",
            model="saaras:v3",
            mode="transcribe",
            flush_signal=True,
            sample_rate=16000,
        )
    elif STT_PROVIDER == "whisper":
        logger.info("STT → OpenAI Whisper")
        return lk_openai.STT(model="whisper-1")
    else:
        raise ValueError(f"Unknown STT_PROVIDER: {STT_PROVIDER!r}")


def _build_llm():
    if LLM_PROVIDER == "openai":
        logger.info("LLM → OpenAI (%s)", OPENAI_LLM_MODEL)
        return lk_openai.LLM(model=OPENAI_LLM_MODEL)
    elif LLM_PROVIDER == "gemini":
        logger.info("LLM → Google Gemini (%s)", GEMINI_LLM_MODEL)
        return lk_google.LLM(model=GEMINI_LLM_MODEL, api_key=os.getenv("GOOGLE_API_KEY"))
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {LLM_PROVIDER!r}")


def _build_tts():
    if TTS_PROVIDER == "sarvam":
        logger.info("TTS → Sarvam Bulbul v3")
        return sarvam.TTS(
            target_language_code=SARVAM_TTS_LANGUAGE,
            model="bulbul:v3",
            speaker=SARVAM_TTS_SPEAKER,
            pace=TTS_SPEED,
        )
    elif TTS_PROVIDER == "openai":
        logger.info("TTS → OpenAI TTS (%s / %s)", OPENAI_TTS_MODEL, OPENAI_TTS_VOICE)
        return lk_openai.TTS(model=OPENAI_TTS_MODEL, voice=OPENAI_TTS_VOICE, speed=TTS_SPEED)
    else:
        raise ValueError(f"Unknown TTS_PROVIDER: {TTS_PROVIDER!r}")


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class FridayAgent(Agent):
    """
    F.R.I.D.A.Y. – Iron Man-style voice assistant.
    All tools are provided via the MCP server.
    """

    def __init__(self, stt, llm, tts) -> None:
        super().__init__(
            instructions=SYSTEM_PROMPT,
            stt=stt,
            llm=llm,
            tts=tts,
            vad=silero.VAD.load(),
            mcp_servers=[
                mcp.MCPServerHTTP(
                    url=MCP_SERVER_URL,
                    transport_type="sse",
                    client_session_timeout_seconds=30,
                ),
            ],
        )

    async def on_enter(self) -> None:
        """Single source of truth for the greeting."""
        await self.session.generate_reply(
            instructions=(
                f"Greet the user exactly with: '{GREETING}' "
                "Warm, slightly curious. Nothing else."
            )
        )


# ---------------------------------------------------------------------------
# LiveKit entry point
# ---------------------------------------------------------------------------

def _turn_detection() -> str:
    return "stt" if STT_PROVIDER == "sarvam" else "vad"


def _endpointing_delay() -> float:
    # Sarvam's STT end-of-turn signal is good — react fast.
    # Whisper has no end-of-turn signal, so wait longer before cutting off.
    return {"sarvam": 0.07, "whisper": 0.3}.get(STT_PROVIDER, 0.1)


async def entrypoint(ctx: JobContext) -> None:
    _validate_env()
    _check_mcp_server(MCP_SERVER_URL)

    logger.info(
        "FRIDAY online – room: %s | STT=%s | LLM=%s | TTS=%s",
        ctx.room.name, STT_PROVIDER, LLM_PROVIDER, TTS_PROVIDER,
    )

    stt = _build_stt()
    llm = _build_llm()
    tts = _build_tts()

    session = AgentSession(
        turn_detection=_turn_detection(),
        min_endpointing_delay=_endpointing_delay(),
    )

    await session.start(
        agent=FridayAgent(stt=stt, llm=llm, tts=tts),
        room=ctx.room,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))


def dev():
    """Wrapper to run the agent in dev mode automatically."""
    import sys
    # If no command was provided, inject 'dev'
    if len(sys.argv) == 1:
        sys.argv.append("dev")
    main()


if __name__ == "__main__":
    dev()
