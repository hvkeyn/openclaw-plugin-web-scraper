"""
Универсальные скраперы на базе botasaurus
Заменяет функциональность vector.py с улучшенными возможностями
"""

import asyncio
import json
import logging
import os
import random
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse

from botasaurus.browser import browser, Driver
from botasaurus.request import request, Request
from botasaurus import bt
from botasaurus.soupify import soupify
from botasaurus.task import task

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BotasaurusProxyManager:
    """
    Менеджер прокси для botasaurus.

    Что делает:
    - Добавление / удаление / редактирование прокси
    - Нормализация формата (если нет схемы, добавляем http://)
    - Персистентность в JSON (по умолчанию ./proxies.json)
    - Статистика успех/ошибка + последнее использование
    - Выбор прокси (best / round_robin / weighted_random)
    """
    
    def __init__(self, storage_path: Optional[str] = None, save_interval_seconds: int = 5):
        self._lock = threading.RLock()
        self.storage_path = Path(storage_path or os.getenv("PROXY_STORAGE_PATH", "proxies.json"))
        self.save_interval_seconds = int(save_interval_seconds)

        self.proxies: List[str] = []
        self.proxy_stats: Dict[str, Dict[str, Any]] = {}
        self.allow_direct: bool = True

        self._rr_index = 0
        self._dirty = False
        self._last_save_ts = 0.0

        self._load()

    @staticmethod
    def _ensure_scheme(proxy: str) -> str:
        if "://" not in proxy:
            return f"http://{proxy}"
        return proxy

    @staticmethod
    def _mask_proxy(proxy: str) -> str:
        """Маскируем пароль (только для логов)."""
        try:
            p = urlparse(proxy)
            if not p.username:
                return proxy
            scheme = p.scheme or "http"
            host = p.hostname or ""
            port = p.port
            user = p.username
            host_port = f"{host}:{port}" if port is not None else host
            return f"{scheme}://{user}:***@{host_port}"
        except Exception:
            return proxy

    def normalize_proxy(self, proxy: str) -> str:
        proxy = (proxy or "").strip()
        if not proxy:
            raise ValueError("Proxy is empty")

        proxy = self._ensure_scheme(proxy)
        parsed = urlparse(proxy)

        if not parsed.scheme or not parsed.hostname or parsed.port is None:
            raise ValueError(f"Invalid proxy format: {proxy}")

        host = parsed.hostname
        port = parsed.port
        if port <= 0 or port > 65535:
            raise ValueError(f"Invalid proxy port: {port}")

        auth = ""
        if parsed.username:
            auth += parsed.username
            if parsed.password is not None:
                auth += f":{parsed.password}"
            auth += "@"

        # IPv6 needs brackets in URLs
        host_out = host
        if ":" in host_out and not host_out.startswith("["):
            host_out = f"[{host_out}]"

        return f"{parsed.scheme}://{auth}{host_out}:{port}"

    def _mark_dirty(self):
        self._dirty = True

    def _load(self):
        path = self.storage_path
        if not path.exists():
            return

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Не удалось загрузить файл прокси {path}: {e}")
            return

        allow_direct = payload.get("allow_direct", True)
        proxies = payload.get("proxies", [])
        stats = payload.get("proxy_stats", {})

        with self._lock:
            self.allow_direct = bool(allow_direct)
            self.proxies = []
            self.proxy_stats = {}

            # Сохраняем порядок прокси из файла
            for item in proxies:
                try:
                    if isinstance(item, str):
                        p = self.normalize_proxy(item)
                        desc = None
                    elif isinstance(item, dict):
                        p = self.normalize_proxy(item.get("proxy", ""))
                        desc = item.get("description")
                    else:
                        continue

                    if p not in self.proxies:
                        self.proxies.append(p)
                    self.proxy_stats.setdefault(
                        p,
                        {"success": 0, "fail": 0, "last_used": None, "description": desc, "last_error": None},
                    )
                    if desc is not None:
                        self.proxy_stats[p]["description"] = desc
                except Exception as e:
                    logger.warning(f"Пропускаю некорректный прокси из {path}: {item!r} ({e})")

            # Поддержка старого формата (ключи могли быть без схемы)
            if isinstance(stats, dict):
                for key, value in stats.items():
                    try:
                        p = self.normalize_proxy(key)
                    except Exception:
                        continue

                    if p not in self.proxies:
                        self.proxies.append(p)
                    st = self.proxy_stats.setdefault(
                        p,
                        {"success": 0, "fail": 0, "last_used": None, "description": None, "last_error": None},
                    )
                    if isinstance(value, dict):
                        for field in ("success", "fail", "last_used", "description", "last_error"):
                            if field in value and value[field] is not None:
                                st[field] = value[field]

    def _save(self, force: bool = False):
        now = time.time()
        with self._lock:
            if not self._dirty and not force:
                return
            if not force and (now - self._last_save_ts) < self.save_interval_seconds:
                return

            payload = {
                "version": 1,
                "allow_direct": self.allow_direct,
                "proxies": [
                    {"proxy": p, "description": self.proxy_stats.get(p, {}).get("description")}
                    for p in self.proxies
                ],
                "proxy_stats": self.proxy_stats,
                "updated_at": datetime.now().isoformat(),
            }

            path = self.storage_path
            tmp_path = path.with_suffix(path.suffix + ".tmp")
            try:
                tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                tmp_path.replace(path)
                self._dirty = False
                self._last_save_ts = now
            except Exception as e:
                logger.warning(f"Не удалось сохранить файл прокси {path}: {e}")
        
    def add_proxy(self, proxy: str, description: Optional[str] = None) -> str:
        """Добавить прокси (возвращает нормализованный формат)."""
        p = self.normalize_proxy(proxy)
        with self._lock:
            if p not in self.proxies:
                self.proxies.append(p)

            st = self.proxy_stats.setdefault(
                p, {"success": 0, "fail": 0, "last_used": None, "description": None, "last_error": None}
            )
            if description is not None:
                st["description"] = description

            self._mark_dirty()
            self._save()

        logger.info(f"Proxy added: {self._mask_proxy(p)}")
        return p
    
    def update_proxy(
        self,
        proxy: str,
        new_proxy: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Обновить прокси (смена адреса и/или описания)."""
        old_p = self.normalize_proxy(proxy)
        with self._lock:
            if old_p not in self.proxies:
                raise KeyError(f"Proxy not found: {proxy}")

            updated_p = old_p
            if new_proxy:
                new_p = self.normalize_proxy(new_proxy)
                if new_p != old_p and new_p in self.proxies:
                    raise ValueError("New proxy already exists")

                idx = self.proxies.index(old_p)
                self.proxies[idx] = new_p

                old_stats = self.proxy_stats.pop(old_p, {})
                self.proxy_stats[new_p] = old_stats or {
                    "success": 0,
                    "fail": 0,
                    "last_used": None,
                    "description": None,
                    "last_error": None,
                }
                updated_p = new_p

            if description is not None:
                st = self.proxy_stats.setdefault(
                    updated_p,
                    {"success": 0, "fail": 0, "last_used": None, "description": None, "last_error": None},
                )
                st["description"] = description

            self._mark_dirty()
            self._save()

            return {
                "proxy": updated_p,
                "description": self.proxy_stats.get(updated_p, {}).get("description"),
            }

    def remove_proxy(self, proxy: str) -> bool:
        """Удалить прокси из списка."""
        p = self.normalize_proxy(proxy)
        with self._lock:
            if p not in self.proxies:
                return False
            self.proxies.remove(p)
            self.proxy_stats.pop(p, None)
            self._mark_dirty()
            self._save()

        logger.info(f"Proxy removed: {self._mask_proxy(p)}")
        return True

    def set_allow_direct(self, allow_direct: bool):
        with self._lock:
            self.allow_direct = bool(allow_direct)
            self._mark_dirty()
            self._save(force=True)
    
    def get_proxy_list_for_botasaurus(self):
        """Получить список прокси в формате botasaurus"""
        return self.proxies if self.proxies else None
    
    def choose_proxy(self, strategy: str = "weighted_random") -> Optional[str]:
        """Выбрать прокси из списка."""
        with self._lock:
            if not self.proxies:
                return None

            if strategy == "round_robin":
                proxy = self.proxies[self._rr_index % len(self.proxies)]
                self._rr_index += 1
                return proxy

            if strategy == "best":
                def score(p: str) -> float:
                    st = self.proxy_stats.get(p, {})
                    s = float(st.get("success", 0))
                    f = float(st.get("fail", 0))
                    return s / (s + f + 1.0)

                return sorted(self.proxies, key=score, reverse=True)[0]

            # weighted_random по умолчанию
            weights = []
            for p in self.proxies:
                st = self.proxy_stats.get(p, {})
                s = float(st.get("success", 0))
                f = float(st.get("fail", 0))
                weights.append((s + 1.0) / (f + 1.0))
            return random.choices(self.proxies, weights=weights, k=1)[0]

    def get_best_proxy(self) -> Optional[str]:
        """Alias для обратной совместимости."""
        return self.choose_proxy(strategy="best")

    def mark_success(self, proxy: Optional[str]):
        if not proxy:
            return
        try:
            p = self.normalize_proxy(proxy)
        except Exception:
            return

        with self._lock:
            if p not in self.proxies:
                self.proxies.append(p)

            st = self.proxy_stats.setdefault(
                p,
                {"success": 0, "fail": 0, "last_used": None, "description": None, "last_error": None},
            )
            st["success"] = int(st.get("success", 0)) + 1
            st["last_used"] = datetime.now().isoformat()
            st["last_error"] = None

            self._mark_dirty()
            self._save()

    def mark_fail(self, proxy: Optional[str], error: Optional[str] = None):
        if not proxy:
            return
        try:
            p = self.normalize_proxy(proxy)
        except Exception:
            return

        with self._lock:
            if p not in self.proxies:
                self.proxies.append(p)

            st = self.proxy_stats.setdefault(
                p,
                {"success": 0, "fail": 0, "last_used": None, "description": None, "last_error": None},
            )
            st["fail"] = int(st.get("fail", 0)) + 1
            st["last_used"] = datetime.now().isoformat()
            if error:
                st["last_error"] = str(error)[:500]

            self._mark_dirty()
            self._save()


# Глобальный менеджер прокси
proxy_manager = BotasaurusProxyManager()


@browser(
    proxy=lambda data: data.get("proxy"),
    user_agent=lambda data: data.get("user_agent"),
    cache=True,
    max_retry=5,
    reuse_driver=True,
    close_on_crash=True,
    create_error_logs=False,
    block_images_and_css=True,  # Ускоряем загрузку
    wait_for_complete_page_load=False,  # Быстрее для HTML-страниц
)
def scrape_page_browser(driver: Driver, data):
    """
    Универсальный браузерный скрапер
    Заменяет функцию fetch_page из vector.py
    """
    url = data.get('url')
    wait_for = data.get('wait_for')
    cookies = data.get('cookies', {})
    headers = data.get('headers', {})
    timeout = data.get('timeout', 30) * 1000  # Конвертируем в миллисекунды
    
    try:
        # Устанавливаем куки если есть
        if cookies:
            for name, value in cookies.items():
                driver.add_cookie({"name": name, "value": value, "url": url})
        
        # Устанавливаем заголовки
        if headers:
            driver.set_extra_http_headers(headers)
        
        # Переходим на страницу
        if data.get('use_google_referrer', True):
            driver.google_get(url, timeout=timeout)
        else:
            driver.get(url, timeout=timeout)
        
        # Ждем элемент если нужно
        if wait_for:
            driver.wait_for_element(wait_for, timeout=timeout)
        
        # Получаем контент
        content = driver.page_html
        page_title = driver.title
        current_url = driver.current_url
        proxy_used = driver.config.proxy

        proxy_manager.mark_success(proxy_used)
        
        return {
            "content": content,
            "title": page_title,
            "url": current_url,
            "proxy_used": proxy_used,
            "status": "success",
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        proxy_used = getattr(getattr(driver, "config", None), "proxy", None)
        proxy_manager.mark_fail(proxy_used, str(e))
        logger.error(f"Browser scraping failed for {url}: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
            "url": url,
            "proxy_used": proxy_used,
            "timestamp": datetime.now().isoformat()
        }


@request(
    proxy=lambda data: data.get("proxy"),
    user_agent=lambda data: data.get("user_agent"),
    cache=True,
    max_retry=20,
    close_on_crash=True,
    create_error_logs=False,
    parallel=40,  # Параллельные запросы
)
def scrape_page_request(request: Request, data):
    """
    Быстрый HTTP скрапер для простых страниц
    Использует humane HTTP запросы
    """
    url = data.get('url')
    headers = data.get('headers', {})
    cookies = data.get('cookies', {})
    timeout = data.get('timeout', 30)
    post_data = data.get('post_data')
    proxy_used = data.get("proxy")
    
    try:
        if post_data:
            response = request.post(
                url, 
                json=post_data, 
                headers=headers, 
                cookies=cookies,
                timeout=timeout
            )
        else:
            response = request.get(
                url, 
                headers=headers, 
                cookies=cookies,
                timeout=timeout
            )
        
        response.raise_for_status()
        
        # Создаем BeautifulSoup объект для парсинга
        soup = soupify(response.text)

        proxy_manager.mark_success(proxy_used)
        
        return {
            "content": response.text,
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "url": response.url,
            "title": soup.title.string if soup.title else None,
            "proxy_used": proxy_used,
            "status": "success",
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        proxy_manager.mark_fail(proxy_used, str(e))
        logger.error(f"Request scraping failed for {url}: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
            "url": url,
            "proxy_used": proxy_used,
            "timestamp": datetime.now().isoformat()
        }


@task(
    cache=True,
    parallel=20,
    close_on_crash=True,
    create_error_logs=False
)
def scrape_batch_urls(data):
    """
    Пакетная обработка URL
    Автоматически выбирает наилучший метод скрапинга
    """
    urls = data.get("urls", [])
    use_browser = data.get("use_browser", False)
    proxy = data.get("proxy")  # может быть str или list[str] (по URL)

    items = []
    proxy_list = proxy if isinstance(proxy, list) else None

    for i, url in enumerate(urls):
        item_proxy = proxy_list[i] if (proxy_list and i < len(proxy_list)) else proxy
        items.append(
            {
                "url": url,
                "timeout": data.get("timeout", 30),
                "headers": data.get("headers", {}),
                "cookies": data.get("cookies", {}),
                "wait_for": data.get("wait_for"),
                "proxy": item_proxy,
                "user_agent": data.get("user_agent"),
            }
        )

    try:
        results = scrape_page_browser(items) if use_browser else scrape_page_request(items)
        if isinstance(results, dict):
            results = [results]
    except Exception as e:
        logger.error(f"Batch scraping failed: {str(e)}")
        results = [
            {
                "status": "error",
                "error": str(e),
                "url": None,
                "proxy_used": None,
                "timestamp": datetime.now().isoformat(),
            }
        ]
    
    return {
        "urls": urls,
        "results": results,
        "proxy_used": proxy if isinstance(proxy, str) else None,
        "total_processed": len(results),
        "successful": len([r for r in results if r.get('status') == 'success']),
        "failed": len([r for r in results if r.get('status') == 'error']),
        "timestamp": datetime.now().isoformat()
    }


# Специализированные скраперы для разных задач

@browser(
    proxy=lambda data: data.get("proxy") or proxy_manager.choose_proxy(strategy="round_robin"),
    user_agent=lambda data: data.get("user_agent"),
    cache=True,
    max_retry=3,
    reuse_driver=True,
    block_images_and_css=True
)
def scrape_with_proxy_rotation(driver: Driver, data):
    """
    Скрапер с автоматической ротацией прокси
    Идеален для сайтов с блокировкой IP
    """
    url = data.get('url')
    
    try:
        # Используем Google referrer для меньшей подозрительности
        driver.google_get(url, bypass_cloudflare=True)
        
        # Получаем основные данные
        title = driver.get_text('h1', wait=2) if driver.select('h1') else driver.title
        content = driver.page_html
        
        # Обновляем статистику прокси при успехе
        current_proxy = driver.config.proxy
        proxy_manager.mark_success(current_proxy)
        
        return {
            "title": title,
            "content": content,
            "url": url,
            "proxy_used": current_proxy,
            "status": "success",
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        # Обновляем статистику прокси при ошибке
        current_proxy = driver.config.proxy
        proxy_manager.mark_fail(current_proxy, str(e))
        
        logger.error(f"Proxy scraping failed for {url}: {str(e)}")
        raise e


@request(
    parallel=50,  # Высокая параллельность для быстрых запросов
    cache=True,
    max_retry=10,
    proxy=lambda data: data.get("proxy"),
    user_agent=lambda data: data.get("user_agent"),
)
def extract_page_metadata(request: Request, data):
    """
    Быстрое извлечение метаданных страницы
    Заголовки, описания, ключевые слова и т.д.
    """
    url = data.get('url')
    
    try:
        response = request.get(url)
        response.raise_for_status()
        
        soup = soupify(response.text)
        
        # Извлекаем метаданные
        title = soup.find('title').get_text(strip=True) if soup.find('title') else None
        description = None
        keywords = None
        
        # Meta description
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc:
            description = meta_desc.get('content', '').strip()
        
        # Meta keywords  
        meta_keywords = soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords:
            keywords = meta_keywords.get('content', '').strip()
        
        # Open Graph данные
        og_title = soup.find('meta', attrs={'property': 'og:title'})
        og_desc = soup.find('meta', attrs={'property': 'og:description'})
        og_image = soup.find('meta', attrs={'property': 'og:image'})
        
        # Извлекаем заголовки H1-H6
        headings = {}
        for i in range(1, 7):
            headings[f'h{i}'] = [h.get_text(strip=True) for h in soup.find_all(f'h{i}')]
        
        return {
            "url": url,
            "title": title,
            "description": description,
            "keywords": keywords,
            "headings": headings,
            "open_graph": {
                "title": og_title.get('content') if og_title else None,
                "description": og_desc.get('content') if og_desc else None,
                "image": og_image.get('content') if og_image else None
            },
            "word_count": len(soup.get_text().split()),
            "status": "success",
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Metadata extraction failed for {url}: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
            "url": url,
            "timestamp": datetime.now().isoformat()
        }


# Утилиты для совместимости с существующим API
def get_scraper_stats():
    """Получить статистику работы скраперов"""
    return {
        "proxy_stats": proxy_manager.proxy_stats,
        "available_proxies": len(proxy_manager.proxies),
        "direct_access_allowed": proxy_manager.allow_direct,
        "proxy_storage_path": str(proxy_manager.storage_path),
        "timestamp": datetime.now().isoformat()
    }


def add_proxy(proxy: str, description: str = None):
    """Добавить прокси в менеджер"""
    normalized = proxy_manager.add_proxy(proxy, description)
    return {"status": "success", "proxy": normalized, "description": description}


def remove_proxy(proxy: str):
    """Удалить прокси из менеджера"""
    normalized = proxy_manager.normalize_proxy(proxy)
    removed = proxy_manager.remove_proxy(normalized)
    return {"status": "success", "proxy": normalized, "removed": removed}


def update_proxy(proxy: str, new_proxy: str = None, description: str = None):
    """Обновить прокси (адрес и/или описание)."""
    updated = proxy_manager.update_proxy(proxy=proxy, new_proxy=new_proxy, description=description)
    return {"status": "success", **updated}


def list_proxies():
    """Получить список всех прокси"""
    return {
        "proxies": proxy_manager.proxies,
        "stats": proxy_manager.proxy_stats,
        "count": len(proxy_manager.proxies)
    } 