# Changelog

## 1.0.0 (2026-02-22)

### Features

- `web_search` tool: DuckDuckGo search via `ddgr` CLI (no API keys needed)
- `web_fetch` tool: fetch and extract page content via remote pyUniBParcer service
  - Anti-bot protection (Botasaurus)
  - Automatic proxy rotation
  - Browser mode for JS-heavy pages (via `wait_for` CSS selector)
  - Metadata extraction mode
- `web_crawl_batch` tool: parallel multi-URL fetching
- CLI health check: `openclaw web-scraper status`
- Bundled server component for remote deployment
