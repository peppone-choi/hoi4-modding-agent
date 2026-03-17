# HOI4 Modding Agent

AI-powered modding assistant for Hearts of Iron IV.
Drop into any HOI4 mod folder, and it auto-scans the entire mod structure, then lets you manage everything through chat.

## Features

- **Auto-scan**: Detects countries, characters, events, ideologies, focus trees on startup
- **16 tools**: Web search, wiki lookup, file read/write, mod search, schema validation, portrait generation
- **Persistent sessions**: Chat history survives server restarts (SQLite)
- **Fact-checked**: Always searches Wikipedia/web before answering about real-world politicians
- **Portrait pipeline**: Face detection → background removal → Gemini style transfer → scanline overlay

## Quick Start

```bash
# Install
pip install -e ".[search,portrait]"

# Set API keys
cp .env.example .env
# Edit .env with your keys

# Run (from your mod directory)
cd /path/to/your/hoi4/mod
hoi4-agent .

# Or with streamlit directly
streamlit run hoi4_agent/ui/app.py
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Claude API key |
| `GEMINI_API_KEY` | No | For portrait generation |
| `TAVILY_API_KEY` | No | Web search (falls back to DuckDuckGo) |
| `GOOGLE_API_KEY` | No | Google Custom Search |
| `GOOGLE_CX` | No | Google Search engine ID |
| `MOD_ROOT` | No | Explicit mod path (auto-detected otherwise) |

## Project Structure

```
hoi4_agent/
├── cli.py              # CLI entry point (hoi4-agent command)
├── config/
│   └── settings.py     # Environment & configuration management
├── core/
│   ├── scanner.py      # Mod auto-scanner
│   ├── mod_tools.py    # Mod file operations
│   ├── wiki_tools.py   # Wikipedia/Wikidata lookup
│   ├── chat_session.py # SQLite session persistence
│   ├── prompt.py       # System prompt & tool definitions
│   └── wiki/           # Wiki updater modules
├── ui/
│   ├── app.py          # Streamlit main app
│   ├── sidebar.py      # Session manager & mod info
│   └── chat_view.py    # Chat interface
└── tools/
    ├── executor.py     # Tool execution engine
    ├── search.py       # Web search (Tavily → Google → DDGS)
    └── portrait/       # Portrait generation pipeline
```

## Tools (16)

| Category | Tools |
|---|---|
| Search | `web_search`, `wiki_lookup` |
| File | `read_file`, `write_file`, `safe_write`, `list_files` |
| Mod | `search_mod`, `find_entity`, `country_details`, `get_schema`, `validate_pdx`, `diff_preview`, `analyze_mod` |
| Portrait | `search_portraits`, `generate_portrait`, `show_image` |

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev,search,portrait]"

# Run tests
pytest tests/ -v
```

## License

MIT
