# pyUniBParcer Server (Botasaurus Edition)

Web scraping server based on [Botasaurus](https://github.com/omkarcloud/botasaurus) providing anti-bot protection, proxy rotation, and caching.

## Deployment options

### Direct (development)

```bash
cp .env.example .env
# edit .env with your credentials
pip install -r requirements.txt
python main.py
```

Server starts on `http://0.0.0.0:8001`.

### Docker

```bash
docker compose up -d
```

### systemd (production)

```bash
# create virtual environment
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# create systemd service
sudo tee /etc/systemd/system/web-scraper.service > /dev/null <<'EOF'
[Unit]
Description=pyUniBParcer Web Scraper
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/web-scraper
ExecStart=/opt/web-scraper/.venv/bin/python main.py
Restart=always
RestartSec=5
Environment=SERVER_HOST=0.0.0.0
Environment=SERVER_PORT=8001
Environment=API_USERNAME=admin
Environment=API_PASSWORD=your_password

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now web-scraper
```

## API endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/` | no | API info |
| GET | `/health` | no | Health check |
| GET | `/routes` | no | List all routes |
| GET | `/test_connection` | no | Test connectivity |
| GET | `/server-info` | no | Server details |
| POST | `/crawl` | yes | Scrape a single URL |
| POST | `/crawl/batch` | yes | Batch scrape multiple URLs |
| POST | `/post_crawl` | yes | POST request scraping |
| POST | `/scrape/metadata` | yes | Extract page metadata |
| POST | `/scrape/protected` | yes | Scrape Cloudflare-protected pages |
| GET | `/stats` | yes | Scraper statistics |
| POST | `/proxy/add` | yes | Add proxy |
| DELETE | `/proxy/remove` | yes | Remove proxy |
| PUT | `/proxy/update` | yes | Update proxy |
| GET | `/proxy/list` | yes | List all proxies |
| GET | `/proxy/check` | yes | Check single proxy |
| GET | `/proxy/check/all` | yes | Check all proxies |
| POST | `/proxy/config` | yes | Configure proxy settings |
| GET | `/proxy/config` | yes | Get proxy configuration |

## Authentication

HTTP Basic Auth. Default credentials: `admin` / `admin`.

Override via environment variables `API_USERNAME` and `API_PASSWORD`.

## Documentation

Interactive docs available at `http://your-server:8001/docs` (Swagger UI).
