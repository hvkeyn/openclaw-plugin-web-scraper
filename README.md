# openclaw-plugin-web-scraper

OpenClaw plugin that provides web search and scraping tools for the AI agent.

- **`web_search`** — DuckDuckGo search via `ddgr` CLI (no API keys needed)
- **`web_fetch`** — Fetch web pages via a remote [pyUniBParcer](https://github.com/hvkeyn/pyUniBParcer) service with anti-bot protection, proxy rotation, and caching
- **`web_crawl_batch`** — Parallel multi-URL fetching

## Architecture

```
Agent calls web_search  ──►  ddgr CLI (local)  ──►  DuckDuckGo
Agent calls web_fetch   ──►  pyUniBParcer API  ──►  target website
                             (your-vps:8001)
                             Botasaurus engine
                             proxy rotation
                             Cloudflare bypass
```

## Quick start

### 1. Install ddgr (for web_search)

```bash
pip install ddgr
```

### 2. Install the plugin

```bash
openclaw plugins install /path/to/openclaw-plugin-web-scraper
```

### 3. Configure

Edit `~/.openclaw/openclaw.json`:

```json5
{
  plugins: {
    entries: {
      "web-scraper": {
        enabled: true,
        config: {
          scraperUrl: "http://your-server:8001",
          username: "admin",
          password: "admin",
          defaultTimeout: 30,
          useInternalProxy: false
        }
      }
    }
  }
}
```

### 4. Restart gateway

```bash
openclaw gateway restart
```

### 5. Verify

```bash
openclaw web-scraper status
```

## Tools

### `web_search`

Search the web using DuckDuckGo. Works locally via `ddgr` — no API keys, no rate limits.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | yes | — | Search query |
| `num_results` | number | no | 5 | Number of results (max 25) |

**Example response:**
```json
{
  "query": "OpenClaw AI assistant",
  "results": [
    {
      "title": "OpenClaw - AI Assistant Framework",
      "url": "https://openclaw.ai",
      "snippet": "Open-source AI assistant that runs on your machine..."
    }
  ],
  "count": 5
}
```

### `web_fetch`

Fetch a web page and return its text content. Uses the remote pyUniBParcer service.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `url` | string | yes | — | URL to fetch |
| `timeout` | number | no | 30 | Timeout in seconds |
| `wait_for` | string | no | — | CSS selector to wait for (enables browser mode) |
| `extract_metadata` | boolean | no | false | Return only metadata (title, description, headings) |

### `web_crawl_batch`

Fetch multiple URLs in parallel.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `urls` | string[] | yes | — | List of URLs to fetch |
| `timeout` | number | no | 30 | Timeout per URL in seconds |

## Remote scraper server

This plugin expects a running [pyUniBParcer](https://github.com/hvkeyn/pyUniBParcer) instance. The `server/` directory contains a ready-to-deploy copy.

See [`server/README.md`](./server/README.md) for deployment instructions.

Quick deploy:

```bash
cd server/
pip install -r requirements.txt
python main.py
# Server starts on http://0.0.0.0:8001
```

### Server API endpoints used by this plugin

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check |
| `/crawl` | POST | Scrape a single URL |
| `/crawl/batch` | POST | Batch scrape multiple URLs |
| `/scrape/metadata` | POST | Extract page metadata |

## Configuration reference

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `scraperUrl` | string | yes | — | pyUniBParcer API URL |
| `username` | string | no | `admin` | HTTP Basic auth username |
| `password` | string | no | `admin` | HTTP Basic auth password |
| `defaultTimeout` | number | no | `30` | Default timeout (seconds) |
| `useInternalProxy` | boolean | no | `false` | Use server-side proxy rotation |

## How it works

The plugin registers three tools:

1. **`web_search`** — Runs `ddgr` (DuckDuckGo CLI) locally and parses JSON output. No network dependencies besides DuckDuckGo itself. No API keys needed.

2. **`web_fetch`** — Sends requests to the remote pyUniBParcer server which uses Botasaurus for anti-bot protection. HTML is stripped to plain text before returning to the agent (max 50KB).

3. **`web_crawl_batch`** — Sends batch requests to pyUniBParcer for parallel processing.

## Troubleshooting

**web_search returns empty results:**
- Verify `ddgr` is installed: `ddgr --version`
- Install it: `pip install ddgr`

**web_fetch returns connection error:**
- Check that pyUniBParcer is running: `curl http://your-server:8001/health`
- Verify `scraperUrl`, `username`, `password` in plugin config

**Slow responses:**
- First request may take 10–30s (Botasaurus browser cold start)
- Subsequent requests use caching and are faster
- Use `extract_metadata: true` for lightweight requests

## License

MIT
