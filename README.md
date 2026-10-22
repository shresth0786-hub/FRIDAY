# F.R.I.D.A.Y.

> *"Fully Responsive Intelligent Digital Assistant for You"*

A local, voice-first AI assistant with an Iron Man attitude. Talk into your microphone and F.R.I.D.A.Y. listens, reasons, runs real tools on your machine, and answers out loud — news briefs, web searches, weather, timers, support tickets — in a single conversational turn.

Two processes cooperate:

| Component | What it is |
|-----------|-----------|
| **MCP Server** (`uv run friday`) | A [FastMCP](https://github.com/jlowin/fastmcp) tool server over SSE — the hands of the assistant. It fetches news, searches the web, checks weather, sets timers, and files tickets. |
| **Voice Agent** (`uv run friday_voice`) | A [LiveKit Agents](https://github.com/livekit/agents) voice pipeline — mic → speech-to-text → LLM → text-to-speech → speaker, pulling tools from the MCP server in real time. |

---

## Features

- **Natural voice conversation** — Sarvam Saaras v3 STT, Gemini 2.5 Flash reasoning, OpenAI `nova` TTS (all swappable via env vars)
- **World news brief** — pulls four RSS feeds (BBC, CNBC, NYTimes, AlJazeera) in parallel, delivers a short spoken summary, then opens a visual world monitor
- **Real web search** — DuckDuckGo search (no API key) plus page fetching with HTML→text extraction, so answers reflect what's happening *now*
- **Weather** — current conditions for any city via Open-Meteo (no API key)
- **Timers** — "set a timer for ten minutes" → countdown in the background → beep on your machine when done
- **Ticketing** — report an issue by voice; it's logged to Supabase with a reference number
- **Fail-fast startup** — validates required API keys and MCP server reachability before joining the room, with clear error messages
- **Clean voice UX** — single-source greeting, short spoken responses, no technical tool names ever spoken

---

## How it works

```
   you speak
      │
      ▼
  STT (Sarvam Saaras v3)
      │
      ▼
  LLM (Gemini 2.5 Flash) ─────► MCP Server (FastMCP / SSE, :8000)
      │                            ├─ get_world_news ──► open_world_monitor
      │                            ├─ search_web / fetch_url
      │                            ├─ get_weather
      ▼                            ├─ set_timer / cancel_timers
  TTS (OpenAI nova)                ├─ create_ticket / list_tickets
      │                            └─ get_current_time, get_system_info, …
      ▼
  speaker / LiveKit room
```

The agent connects to the MCP server at `http://127.0.0.1:8000/sse` by default — override with the `MCP_SERVER_URL` env var (e.g. a Cloudflare tunnel when the server runs elsewhere).

---

## Project structure

```
FRIDAY/
├── server.py           # uv run friday  → starts the MCP server (SSE on :8000)
├── agent_friday.py     # uv run friday_voice → starts the LiveKit voice agent
├── pyproject.toml
├── .env.example        # copy → .env and fill in your keys
│
└── friday/             # MCP server package
    ├── config.py       # env-var loading & app-wide settings
    ├── tools/          # MCP tools (callable by the LLM)
    │   ├── web.py      # search_web, fetch_url, get_world_news, open_world_monitor
    │   ├── weather.py  # get_weather (Open-Meteo, no API key needed)
    │   ├── timers.py   # set_timer, cancel_timers (beeps on the host)
    │   ├── tickets.py  # create_ticket, list_tickets (Supabase REST)
    │   ├── system.py   # get_current_time, get_system_info
    │   └── utils.py    # format_json, word_count
    ├── prompts/        # MCP prompt templates (summarize, explain_code, …)
    └── resources/      # MCP resources exposed to clients (friday://info)
```

---

## Quick start

### 1. Prerequisites

- Python ≥ 3.11
- [`uv`](https://github.com/astral-sh/uv) — `pip install uv` or `curl -Lsf https://astral.sh/uv/install.sh | sh`
- A [LiveKit Cloud](https://cloud.livekit.io) project (free tier works)

### 2. Clone & install

```bash
git clone https://github.com/shresth0786-hub/FRIDAY.git
cd FRIDAY
uv sync          # creates .venv and installs all dependencies
```

### 3. Set up environment

```bash
cp .env.example .env
# Open .env and fill in your API keys (see the section below)
```

### 4. Run — two terminals

**Terminal 1 — MCP server** (must start first)

```bash
uv run friday
```

Starts the FastMCP server on `http://127.0.0.1:8000/sse`. The voice agent connects here to fetch its tools.

**Terminal 2 — Voice agent**

```bash
uv run friday_voice
```

Starts the LiveKit voice agent in **dev mode** — it joins a LiveKit room and begins listening. Open the [LiveKit Agents Playground](https://agents-playground.livekit.io) and connect to your room to talk to FRIDAY.

---

## `uv run friday` vs `uv run friday_voice`

| Command | Entry point | What it does |
|---------|------------|--------------|
| `uv run friday` | `server.py → main()` | Launches the **FastMCP server** over SSE on port 8000. Registers all tools, prompts, and resources the LLM can call. |
| `uv run friday_voice` | `agent_friday.py → dev()` | Launches the **LiveKit voice agent**. Builds the STT / LLM / TTS pipeline, joins your LiveKit room, and wires up the MCP server as a tool source. The `dev()` wrapper auto-injects the `dev` CLI flag. |

> Both processes must run **simultaneously**. The voice agent calls the MCP server in real time whenever it needs a tool.

---

## Environment variables

Copy `.env.example` → `.env` and fill in the values below.

| Variable | Required | Where to get it |
|----------|----------|----------------|
| `LIVEKIT_URL` | ✅ | [LiveKit Cloud dashboard](https://cloud.livekit.io) → your project URL |
| `LIVEKIT_API_KEY` | ✅ | LiveKit Cloud → API Keys |
| `LIVEKIT_API_SECRET` | ✅ | LiveKit Cloud → API Keys |
| `SARVAM_API_KEY` | ✅ (default STT) | [dashboard.sarvam.ai](https://dashboard.sarvam.ai) |
| `OPENAI_API_KEY` | ✅ (default TTS) | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| `GOOGLE_API_KEY` | ✅ (default LLM) | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| `GROQ_API_KEY` | optional | [console.groq.com](https://console.groq.com) — for Groq LLM models |
| `DEEPGRAM_API_KEY` | optional | [console.deepgram.com](https://console.deepgram.com) |
| `GOOGLE_APPLICATION_CREDENTIALS` | optional | GCP service-account JSON *path* — only for `STT_PROVIDER = "google"` |
| `SUPABASE_URL` | optional | [supabase.com](https://supabase.com) — for the ticketing tools |
| `SUPABASE_API_KEY` | optional | Supabase project → API settings |
| `MCP_SERVER_URL` | optional | Override the MCP server URL (default `http://127.0.0.1:8000/sse`) |

The agent checks at startup that the keys for your chosen pipeline exist and exits with a clear message if any are missing.

### Supabase ticketing setup (optional)

Run this once in the Supabase SQL editor, then set `SUPABASE_URL` / `SUPABASE_API_KEY`:

```sql
create table tickets (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  title text not null,
  details text,
  status text not null default 'open'
);
```

---

## Switching providers

Set env vars in `.env` (no code changes needed):

```bash
STT_PROVIDER=sarvam   # sarvam | whisper
LLM_PROVIDER=gemini   # gemini | openai
TTS_PROVIDER=openai   # openai | sarvam
```

---

## Adding a new tool

1. Create or open a file in `friday/tools/`
2. Define a `register(mcp)` function and decorate tools with `@mcp.tool()`
3. Import and call `register(mcp)` inside `friday/tools/__init__.py`

The MCP server will pick it up on next start.

---

## Tech stack

- **[FastMCP](https://github.com/jlowin/fastmcp)** — MCP server framework
- **[LiveKit Agents](https://github.com/livekit/agents)** — real-time voice pipeline
- **Sarvam Saaras v3** — STT (Indian-English optimised)
- **Google Gemini 2.5 Flash** — LLM
- **OpenAI TTS** (`nova` voice) — TTS
- **Silero VAD** — voice activity detection
- **DuckDuckGo (HTML endpoint)** — keyless web search
- **Open-Meteo** — keyless weather data
- **Supabase REST** — ticket storage
- **[uv](https://github.com/astral-sh/uv)** — fast Python package manager

---

## Roadmap

- [ ] Own demo video / screenshots of this fork in action
- [ ] Wake-word or push-to-talk activation
- [ ] Conversation memory across a session
- [ ] Ticket status updates (`update_ticket`, `close_ticket`)
- [ ] Optional ElevenLabs TTS voice
- [ ] System controls (volume, brightness, app launching) as MCP tools

---

## Credits & attribution

This project is a modified fork of [SAGAR-TAMANG/friday-tony-stark-demo](https://github.com/SAGAR-TAMANG/friday-tony-stark-demo) by **Sagar Tamang**, used under the MIT license. The core architecture (LiveKit voice agent + FastMCP tool server) is his work — thank you for open-sourcing it.

**What this fork changed:**

- Rewritten F.R.I.D.A.Y. system prompt (single-source greeting, no spoken tool names, short spoken answers)
- Fail-fast startup: API-key validation + MCP server reachability check
- Real DuckDuckGo `search_web` (was a stub) and HTML→text `fetch_url`
- New tools: `get_weather`, `set_timer` / `cancel_timers`, `create_ticket` / `list_tickets`
- Providers, models, and MCP URL configurable via env vars (no code edits)
- Packaging fixes (hatch wheel includes the `friday` package), dead code removed
- Ruff lint config, updated docs, `.env.example`

## License

[MIT](LICENSE) — see [LICENSE](LICENSE) for copyright notices covering the original work and this fork.
