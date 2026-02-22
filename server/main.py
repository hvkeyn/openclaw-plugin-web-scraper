"""
Главный файл приложения с поддержкой botasaurus
Обеспечивает обратную совместимость с существующим API
Автоопределение IP и настройка для удаленного доступа
"""

import os
import uvicorn
import socket
import requests
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Depends, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from botasaurus_server.server import Server
from botasaurus_api import Api

# Импортируем наши скраперы
from scrapers import (
    scrape_page_browser,
    scrape_page_request, 
    scrape_batch_urls,
    scrape_with_proxy_rotation,
    extract_page_metadata,
    add_proxy,
    remove_proxy,
    update_proxy,
    list_proxies,
    get_scraper_stats,
    proxy_manager
)

# Модели для совместимости
from vector_models import *

import secrets
import logging
from datetime import datetime


# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_server_ip():
    """Универсальное определение IP сервера"""
    try:
        # Попытка получить внешний IP
        logger.info("Определение внешнего IP сервера...")
        response = requests.get('https://httpbin.org/ip', timeout=5)
        if response.status_code == 200:
            external_ip = response.json().get('origin', '').split(',')[0].strip()
            logger.info(f"Внешний IP: {external_ip}")
            return external_ip
    except Exception as e:
        logger.warning(f"Не удалось получить внешний IP: {e}")
    
    try:
        # Альтернативный способ получения внешнего IP
        response = requests.get('https://ipv4.icanhazip.com', timeout=5)
        if response.status_code == 200:
            external_ip = response.text.strip()
            logger.info(f"Внешний IP (альтернативный): {external_ip}")
            return external_ip
    except Exception as e:
        logger.warning(f"Альтернативный способ получения IP не сработал: {e}")
    
    try:
        # Получение локального IP (для локальной сети)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            logger.info(f"Локальный IP: {local_ip}")
            return local_ip
    except Exception as e:
        logger.warning(f"Не удалось получить локальный IP: {e}")
    
    # Fallback
    logger.warning("Используем fallback IP: 0.0.0.0")
    return "0.0.0.0"


def get_network_interfaces():
    """Получение информации о сетевых интерфейсах"""
    interfaces = {}
    try:
        import netifaces
        for interface in netifaces.interfaces():
            try:
                addrs = netifaces.ifaddresses(interface)
                if netifaces.AF_INET in addrs:
                    for addr in addrs[netifaces.AF_INET]:
                        ip = addr.get('addr')
                        if ip and not ip.startswith('127.'):
                            interfaces[interface] = ip
            except Exception:
                continue
    except ImportError:
        logger.info("netifaces не установлен, используем базовое определение IP")
    
    return interfaces


def resolve_proxy_for_request(
    requested_proxy: str | None,
    use_internal_proxy: bool,
    force_proxy: bool,
    *,
    strategy: str = "weighted_random",
) -> str | None:
    """
    Единая логика выбора прокси для эндпоинтов.

    Правила:
    - Если передан `requested_proxy`, используем его (после нормализации).
    - Если включен `use_internal_proxy` или `force_proxy` или глобально запрещен direct,
      пытаемся взять прокси из внутреннего списка.
    - Если прокси нет, а `force_proxy`=True или direct запрещен -> 503.
    """
    if requested_proxy:
        try:
            return proxy_manager.normalize_proxy(requested_proxy)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Некорректный формат прокси: {e}")

    must_use_proxy = bool(force_proxy or use_internal_proxy or (not proxy_manager.allow_direct))
    if not must_use_proxy:
        return None

    chosen = proxy_manager.choose_proxy(strategy=strategy)
    if chosen:
        return chosen

    if force_proxy or (not proxy_manager.allow_direct):
        raise HTTPException(status_code=503, detail="Прокси не настроены, а прямой доступ отключён")

    return None


def resolve_proxy_list_for_batch(
    urls: list[str],
    requested_proxy: str | None,
    use_internal_proxy: bool,
) -> str | list[str] | None:
    """
    Для batch:
    - если задан внешний прокси -> один proxy (str) на все URL
    - если internal/direct-disabled -> список proxy на каждый URL (round_robin)
    - иначе -> None
    """
    if requested_proxy:
        try:
            return proxy_manager.normalize_proxy(requested_proxy)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Некорректный формат прокси: {e}")

    must_use_internal = bool(use_internal_proxy or (not proxy_manager.allow_direct))
    if not must_use_internal:
        return None

    if not proxy_manager.proxies:
        if not proxy_manager.allow_direct:
            raise HTTPException(status_code=503, detail="Прокси не настроены, а прямой доступ отключён")
        return None

    proxy_list: list[str] = []
    for _ in urls:
        p = proxy_manager.choose_proxy(strategy="round_robin")
        proxy_list.append(p)
    return proxy_list


# Определяем конфигурацию сервера
SERVER_IP = get_server_ip()
HOST = os.getenv("SERVER_HOST", "0.0.0.0")  # 0.0.0.0 для доступа извне
PORT = int(os.getenv("SERVER_PORT", 8000))
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")  # production/development

logger.info(f"Сервер будет запущен на: {HOST}:{PORT}")
logger.info(f"Внешний доступ: http://{SERVER_IP}:{PORT}")
if HOST == "0.0.0.0":
    logger.info("✅ Сервер доступен для удаленных подключений")
else:
    logger.warning("⚠️ Сервер доступен только локально")

# Получаем информацию о сетевых интерфейсах
network_interfaces = get_network_interfaces()
if network_interfaces:
    logger.info("Доступные сетевые интерфейсы:")
    for interface, ip in network_interfaces.items():
        logger.info(f"  {interface}: {ip}")


# Lifespan для управления жизненным циклом приложения
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Запуск
    logger.info("🚀 Запуск pyUniBParcer с botasaurus")
    logger.info(f"🌐 Сервер доступен по адресам:")
    logger.info(f"   Локальный: http://localhost:{PORT}")
    logger.info(f"   Сетевой: http://{SERVER_IP}:{PORT}")
    logger.info(f"   API документация: http://{SERVER_IP}:{PORT}/docs")
    
    # Регистрируем скраперы в botasaurus server (опционально).
    # В Botasaurus Server для каждого scraper ожидается файл `backend/inputs/<scraper_name>.js`.
    # Если его нет, не валим весь API — просто логируем предупреждение.
    if os.getenv("ENABLE_BOTASAURUS_SERVER", "true").lower() in ("1", "true", "yes", "y", "on"):
        for scraper_fn in (
            scrape_page_browser,
            scrape_page_request,
            scrape_batch_urls,
            scrape_with_proxy_rotation,
            extract_page_metadata,
        ):
            try:
                Server.add_scraper(scraper_fn)
            except Exception as e:
                logger.warning(
                    f"⚠️ Не удалось зарегистрировать {getattr(scraper_fn, '__name__', str(scraper_fn))} "
                    f"в Botasaurus Server: {e}"
                )
    
    yield
    
    # Очистка при завершении
    logger.info("🛑 Завершение работы pyUniBParcer")


# Создание FastAPI приложения
app = FastAPI(
    title="pyUniBParcer API (Botasaurus Edition)",
    description=f"Универсальный API для веб-скрапинга на базе botasaurus. Сервер: {SERVER_IP}:{PORT}",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",  # Swagger UI
    redoc_url="/redoc",  # ReDoc
    openapi_url="/openapi.json"
)

# Настройка CORS для удаленного доступа
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене заменить на конкретные домены
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Настройка аутентификации
security = HTTPBasic()

def get_current_username(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, os.getenv("API_USERNAME", "admin"))
    correct_password = secrets.compare_digest(credentials.password, os.getenv("API_PASSWORD", "admin"))
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# Инициализация Botasaurus API клиента
try:
    botasaurus_api = Api()
    logger.info("✅ Botasaurus API клиент инициализирован")
except Exception as e:
    logger.warning(f"⚠️ Не удалось инициализировать Botasaurus API: {e}")
    botasaurus_api = None


# ========== Информационные эндпоинты ==========

@app.get("/", tags=["Info"])
async def root():
    return {
        "name": "pyUniBParcer API (Botasaurus Edition)",
        "version": "2.0.0",
        "description": "Универсальный API для веб-скрапинга на базе botasaurus",
        "server_ip": SERVER_IP,
        "server_port": PORT,
        "endpoints": {
            "docs": f"http://{SERVER_IP}:{PORT}/docs",
            "health": f"http://{SERVER_IP}:{PORT}/health",
            "stats": f"http://{SERVER_IP}:{PORT}/stats"
        },
        "features": [
            "Обратная совместимость с Vector API",
            "Встроенная защита от блокировок",
            "Автоматическое кеширование",
            "Ротация прокси",
            "Веб-интерфейс для управления",
            "Высокая производительность",
            "Удаленный доступ"
        ]
    }

@app.get("/health", tags=["Info"])
async def health_check():
    """Проверка состояния сервера"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "server_ip": SERVER_IP,
        "server_port": PORT,
        "environment": ENVIRONMENT,
        "uptime": "running"
    }

@app.get("/routes", tags=["Info"])
def list_routes():
    return [{"path": route.path, "methods": list(route.methods)} for route in app.routes]

@app.get("/test_connection", tags=["Info"])
def test_connection(request: Request):
    client_host = request.client.host
    return {
        "status": "ok",
        "message": "Connection successful!",
        "client_ip": client_host,
        "server_ip": SERVER_IP,
        "server_host": request.headers.get("host", "unknown"),
        "powered_by": "botasaurus",
        "remote_accessible": HOST == "0.0.0.0"
    }

@app.get("/server-info", tags=["Info"])
def server_info():
    """Детальная информация о сервере"""
    return {
        "server_ip": SERVER_IP,
        "bind_host": HOST,
        "port": PORT,
        "environment": ENVIRONMENT,
        "network_interfaces": network_interfaces,
        "access_urls": {
            "local": f"http://localhost:{PORT}",
            "network": f"http://{SERVER_IP}:{PORT}",
            "docs": f"http://{SERVER_IP}:{PORT}/docs"
        },
        "remote_accessible": HOST == "0.0.0.0"
    }


# ========== Эндпоинты для управления прокси ==========

@app.post("/proxy/add", tags=["Proxy"])
async def add_proxy_endpoint(request: ProxyRequest, username: str = Depends(get_current_username)):
    try:
        result = add_proxy(request.proxy, request.description)
        return {
            "message": "Proxy added successfully",
            "proxy": result.get("proxy"),
            "description": request.description,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/proxy/remove", tags=["Proxy"])
async def remove_proxy_endpoint(request: ProxyRequest, username: str = Depends(get_current_username)):
    try:
        result = remove_proxy(request.proxy)
        return {
            "message": "Proxy removed successfully" if result.get("removed") else "Proxy not found",
            "proxy": result.get("proxy"),
            "removed": bool(result.get("removed")),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/proxy/update", tags=["Proxy"])
async def update_proxy_endpoint(request: ProxyUpdateRequest, username: str = Depends(get_current_username)):
    try:
        result = update_proxy(request.proxy, request.new_proxy, request.description)
        return {"message": "Proxy updated successfully", **result}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/proxy/list", tags=["Proxy"])
async def list_proxies_endpoint(username: str = Depends(get_current_username)):
    result = list_proxies()
    if not result.get("proxies"):
        result["message"] = "No proxies available"
    return result

@app.get("/proxy/check", tags=["Proxy"])
async def check_proxy_endpoint(proxy: str, username: str = Depends(get_current_username)):
    test_url = os.getenv("PROXY_CHECK_URL", "https://httpbin.org/ip")
    timeout = int(os.getenv("PROXY_CHECK_TIMEOUT", "15"))

    try:
        normalized = proxy_manager.normalize_proxy(proxy)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Некорректный формат прокси: {e}")

    start = time.perf_counter()
    result = scrape_page_request({"url": test_url, "timeout": timeout, "proxy": normalized})
    elapsed = time.perf_counter() - start

    if result.get("status") == "success":
        return {
            "proxy": normalized,
            "status": "working",
            "response_time": f"{elapsed:.2f}s",
            "last_check": datetime.now().isoformat(),
        }

    return {
        "proxy": normalized,
        "status": "failed",
        "response_time": f"{elapsed:.2f}s",
        "last_check": datetime.now().isoformat(),
        "error": result.get("error", "Unknown error"),
    }

@app.get("/proxy/check/all", tags=["Proxy"])
async def check_all_proxies_endpoint(username: str = Depends(get_current_username)):
    proxy_list = list_proxies()
    if not proxy_list.get("proxies"):
        return {"proxies_status": [], "message": "No proxies available"}
    
    # Проверяем каждый прокси
    results = []
    for proxy in proxy_list["proxies"]:
        try:
            check_result = await check_proxy_endpoint(proxy, username)
            results.append(check_result)
        except Exception as e:
            results.append({
                "proxy": proxy,
                "status": "failed",
                "error": str(e)
            })
    
    return {"proxies_status": results}

@app.post("/proxy/config", tags=["Proxy"])
async def configure_proxy_endpoint(request: ProxyConfig, username: str = Depends(get_current_username)):
    proxy_manager.set_allow_direct(request.allow_direct)
    logger.info(f"Direct access {'enabled' if request.allow_direct else 'disabled'}")
    return {
        "message": "Proxy configuration updated",
        "allow_direct": request.allow_direct
    }

@app.get("/proxy/config", tags=["Proxy"])
async def get_proxy_config_endpoint(username: str = Depends(get_current_username)):
    return {
        "allow_direct": proxy_manager.allow_direct,
        "available_proxies": len(proxy_manager.proxies)
    }


# ========== Основные эндпоинты скрапинга ==========

@app.post("/crawl", tags=["Crawler"])
async def crawl_page_endpoint(request: CrawlRequest, username: str = Depends(get_current_username)):
    """
    Универсальный эндпоинт для скрапинга страниц
    Автоматически выбирает лучший метод (browser/request)
    """
    try:
        proxy_used = resolve_proxy_for_request(
            request.proxy,
            bool(request.use_internal_proxy),
            bool(request.force_proxy),
            strategy="weighted_random",
        )

        # Подготавливаем данные для скрапера
        scrape_data = {
            "url": request.url,
            "timeout": request.timeout,
            "wait_for": request.wait_for,
            "use_google_referrer": True,
            "user_agent": request.user_agent,
            "headers": {},
            "cookies": {}
        }
        if proxy_used:
            scrape_data["proxy"] = proxy_used
        
        # Определяем нужен ли браузер или достаточно HTTP запроса
        use_browser = bool(request.wait_for)
        
        if use_browser:
            # Используем браузерный скрапер для сложных сайтов
            result = scrape_page_browser(scrape_data)
        else:
            # Используем быстрый HTTP скрапер
            result = scrape_page_request(scrape_data)
        
        # Форматируем ответ для совместимости
        return {
            "url": request.url,
            "proxy_used": result.get("proxy_used") or proxy_used,
            "content": {
                "status": result.get("status", "unknown"),
                "content": result.get("content", ""),
                "title": result.get("title", ""),
                "headers": result.get("headers", {}),
            }
        }
        
    except Exception as e:
        logger.error(f"Crawling failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/crawl/batch", tags=["Crawler"])
async def batch_crawl_endpoint(request: BatchCrawlRequest, username: str = Depends(get_current_username)):
    """
    Пакетная обработка URL с использованием botasaurus
    """
    try:
        proxy_setting = resolve_proxy_list_for_batch(
            request.urls,
            request.proxy,
            bool(request.use_internal_proxy),
        )

        batch_data = {
            "urls": request.urls,
            "timeout": request.timeout,
            "use_browser": False,  # Для быстроты используем HTTP запросы
            "proxy": proxy_setting,
            "user_agent": request.user_agent,
            "headers": {},
            "cookies": {}
        }
        
        result = scrape_batch_urls(batch_data)
        
        # Форматируем для совместимости
        return {
            "urls": request.urls,
            "proxy_used": result.get("proxy_used"),
            "results": [
                {
                    "status": r.get("status", "unknown"),
                    "content": r.get("content", ""),
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "proxy_used": r.get("proxy_used"),
                }
                for r in result.get("results", [])
            ]
        }
        
    except Exception as e:
        logger.error(f"Batch crawling failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/post_crawl", tags=["Crawler"])
async def post_crawl_endpoint(request: PostRequest, username: str = Depends(get_current_username)):
    """
    POST запросы с данными
    """
    try:
        proxy_used = resolve_proxy_for_request(
            request.proxy,
            bool(request.use_internal_proxy),
            bool(request.force_proxy),
            strategy="weighted_random",
        )

        scrape_data = {
            "url": request.url,
            "timeout": request.timeout,
            "wait_for": request.wait_for,
            "headers": request.headers or {},
            "cookies": request.cookies or {},
            "post_data": request.post_data,
            "user_agent": request.user_agent,
        }
        if proxy_used:
            scrape_data["proxy"] = proxy_used
        
        # Для POST запросов используем HTTP скрапер
        result = scrape_page_request(scrape_data)
        
        return {
            "url": request.url,
            "proxy_used": result.get("proxy_used") or proxy_used,
            "result": {
                "status": result.get("status", "unknown"),
                "content": result.get("content", ""),
                "headers": result.get("headers", {}),
            }
        }
        
    except Exception as e:
        logger.error(f"POST crawling failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== Расширенные эндпоинты botasaurus ==========

@app.post("/scrape/metadata", tags=["Advanced"])
async def extract_metadata_endpoint(request: CrawlRequest, username: str = Depends(get_current_username)):
    """
    Быстрое извлечение метаданных страницы
    """
    try:
        proxy_used = resolve_proxy_for_request(
            request.proxy,
            bool(request.use_internal_proxy),
            bool(request.force_proxy),
            strategy="weighted_random",
        )
        data = {"url": request.url, "user_agent": request.user_agent}
        if proxy_used:
            data["proxy"] = proxy_used
        result = extract_page_metadata(data)
        return result
    except Exception as e:
        logger.error(f"Metadata extraction failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/scrape/protected", tags=["Advanced"])
async def scrape_protected_endpoint(request: CrawlRequest, username: str = Depends(get_current_username)):
    """
    Скрапинг защищенных сайтов с Cloudflare bypass
    """
    try:
        proxy_used = resolve_proxy_for_request(
            request.proxy,
            bool(request.use_internal_proxy),
            bool(request.force_proxy),
            strategy="round_robin",
        )
        data = {
            "url": request.url,
            "timeout": request.timeout,
            "wait_for": request.wait_for,
            "user_agent": request.user_agent,
        }
        if proxy_used:
            data["proxy"] = proxy_used
        result = scrape_with_proxy_rotation(data)
        return result
    except Exception as e:
        logger.error(f"Protected scraping failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats", tags=["Monitoring"])
async def get_stats_endpoint(username: str = Depends(get_current_username)):
    """
    Получить статистику работы скраперов
    """
    stats = get_scraper_stats()
    stats.update({
        "server_ip": SERVER_IP,
        "server_port": PORT,
        "remote_accessible": HOST == "0.0.0.0"
    })
    return stats


# ========== Интеграция с Botasaurus Server ==========

if botasaurus_api:
    @app.post("/botasaurus/task", tags=["Botasaurus"])
    async def create_botasaurus_task(
        scraper_name: str, 
        data: dict, 
        sync: bool = False,
        username: str = Depends(get_current_username)
    ):
        """
        Создать задачу через Botasaurus API
        """
        try:
            if sync:
                task = botasaurus_api.create_sync_task(data, scraper_name=scraper_name)
            else:
                task = botasaurus_api.create_async_task(data, scraper_name=scraper_name)
            
            return task
        except Exception as e:
            logger.error(f"Botasaurus task creation failed: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.get("/botasaurus/tasks", tags=["Botasaurus"])
    async def get_botasaurus_tasks(username: str = Depends(get_current_username)):
        """
        Получить список задач Botasaurus
        """
        try:
            tasks = botasaurus_api.get_tasks()
            return tasks
        except Exception as e:
            logger.error(f"Failed to get Botasaurus tasks: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))


# Обработчики ошибок
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "message": exc.detail,
            "status_code": exc.status_code,
            "timestamp": datetime.now().isoformat(),
            "path": request.url.path,
            "server_ip": SERVER_IP
        }
    )


if __name__ == "__main__":
    logger.info("="*60)
    logger.info("🚀 Запуск pyUniBParcer на базе botasaurus")
    logger.info("="*60)
    logger.info(f"🖥️  Сервер: {HOST}:{PORT}")
    logger.info(f"🌐 Внешний IP: {SERVER_IP}")
    logger.info(f"📚 Документация: http://{SERVER_IP}:{PORT}/docs")
    logger.info(f"🔐 Аутентификация: {os.getenv('API_USERNAME', 'admin')} / {os.getenv('API_PASSWORD', 'admin')}")
    logger.info("="*60)
    
    uvicorn.run(
        app, 
        host=HOST, 
        port=PORT, 
        log_level="info",
        access_log=True,
        reload=False if ENVIRONMENT == "production" else True
    ) 