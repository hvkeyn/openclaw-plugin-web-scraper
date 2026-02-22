"""
Модели данных для обратной совместимости с vector.py API
Сохраняют оригинальные структуры запросов и ответов
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Union


class ProxyRequest(BaseModel):
    proxy: str = Field(..., description="IP:port прокси сервера")
    description: Optional[str] = Field(None, description="Описание прокси")


class ProxyUpdateRequest(BaseModel):
    """Запрос на редактирование прокси."""

    proxy: str = Field(..., description="Текущий прокси (например, http://ip:port или ip:port)")
    new_proxy: Optional[str] = Field(None, description="Новый прокси (если нужно изменить адрес)")
    description: Optional[str] = Field(None, description="Новое описание (если нужно изменить)")


class ProxyConfig(BaseModel):
    allow_direct: bool = Field(True, description="Разрешить прямые соединения без прокси")


class CrawlRequest(BaseModel):
    url: str = Field(..., description="URL для парсинга")
    use_internal_proxy: Optional[bool] = Field(False, description="Использовать внутренний прокси")
    proxy: Optional[str] = Field(None, description="Внешний прокси (IP:port)")
    user_agent: Optional[str] = Field(None, description="User-Agent для запроса")
    timeout: Optional[int] = Field(30, description="Таймаут запроса в секундах")
    wait_for: Optional[str] = Field(None, description="CSS селектор для ожидания загрузки")
    force_proxy: Optional[bool] = Field(False, description="Обязательно использовать прокси (если доступен)")


class PostRequest(CrawlRequest):
    post_data: Optional[Dict[str, Any]] = Field(None, description="Данные для POST-запроса")
    headers: Optional[Dict[str, str]] = Field(None, description="Дополнительные заголовки")
    cookies: Optional[Dict[str, str]] = Field(None, description="Cookies для запроса")


class BatchCrawlRequest(BaseModel):
    urls: List[str] = Field(..., description="Список URL для парсинга")
    use_internal_proxy: Optional[bool] = Field(False, description="Использовать внутренний прокси")
    proxy: Optional[str] = Field(None, description="Внешний прокси (IP:port)")
    user_agent: Optional[str] = Field(None, description="User-Agent для запроса")
    timeout: Optional[int] = Field(30, description="Таймаут запроса в секундах")


# Расширенные модели для новых возможностей botasaurus
class AdvancedCrawlRequest(CrawlRequest):
    """Расширенный запрос с дополнительными возможностями botasaurus"""
    cache: Optional[bool] = Field(True, description="Использовать кеширование")
    block_images: Optional[bool] = Field(False, description="Блокировать изображения")
    block_images_and_css: Optional[bool] = Field(False, description="Блокировать изображения и CSS")
    bypass_cloudflare: Optional[bool] = Field(False, description="Обход Cloudflare")
    extract_metadata: Optional[bool] = Field(False, description="Извлекать метаданные")
    use_google_referrer: Optional[bool] = Field(True, description="Использовать Google как referrer")


class ScraperTaskRequest(BaseModel):
    """Запрос для создания задач через botasaurus API"""
    scraper_name: str = Field(..., description="Название скрапера")
    data: Dict[str, Any] = Field(..., description="Данные для скрапера")
    sync: Optional[bool] = Field(False, description="Синхронное выполнение")
    parallel: Optional[int] = Field(None, description="Количество параллельных задач")


# Модели ответов
class BaseResponse(BaseModel):
    status: str = Field(..., description="Статус выполнения")
    timestamp: str = Field(..., description="Время выполнения")


class CrawlResponse(BaseResponse):
    url: str = Field(..., description="Обработанный URL")
    proxy_used: Optional[str] = Field(None, description="Использованный прокси")
    content: Dict[str, Any] = Field(..., description="Содержимое страницы")


class BatchCrawlResponse(BaseResponse):
    urls: List[str] = Field(..., description="Обработанные URL")
    proxy_used: Optional[str] = Field(None, description="Использованный прокси")
    results: List[Dict[str, Any]] = Field(..., description="Результаты обработки")
    total_processed: int = Field(..., description="Всего обработано")
    successful: int = Field(..., description="Успешно обработано")
    failed: int = Field(..., description="Обработано с ошибками")


class ProxyStatus(BaseModel):
    proxy: str = Field(..., description="IP:port прокси")
    status: str = Field(..., description="Статус прокси (working/failed)")
    response_time: Optional[str] = Field(None, description="Время ответа")
    location: Optional[str] = Field(None, description="Местоположение")
    last_check: Optional[str] = Field(None, description="Время последней проверки")
    error: Optional[str] = Field(None, description="Сообщение об ошибке")


class ProxyListResponse(BaseModel):
    proxies: List[str] = Field(..., description="Список прокси")
    stats: Dict[str, Dict[str, Any]] = Field(..., description="Статистика прокси")
    count: int = Field(..., description="Количество прокси")


class MetadataResponse(BaseResponse):
    url: str = Field(..., description="URL страницы")
    title: Optional[str] = Field(None, description="Заголовок страницы")
    description: Optional[str] = Field(None, description="Описание страницы")
    keywords: Optional[str] = Field(None, description="Ключевые слова")
    headings: Dict[str, List[str]] = Field(..., description="Заголовки H1-H6")
    open_graph: Dict[str, Optional[str]] = Field(..., description="Open Graph данные")
    word_count: int = Field(..., description="Количество слов")


class StatsResponse(BaseModel):
    proxy_stats: Dict[str, Dict[str, Any]] = Field(..., description="Статистика прокси")
    available_proxies: int = Field(..., description="Доступных прокси")
    direct_access_allowed: bool = Field(..., description="Разрешен прямой доступ")
    timestamp: str = Field(..., description="Время получения статистики")


class ErrorResponse(BaseModel):
    error: bool = Field(True, description="Индикатор ошибки")
    message: str = Field(..., description="Сообщение об ошибке")
    status_code: int = Field(..., description="HTTP код ошибки")
    timestamp: str = Field(..., description="Время возникновения ошибки")
    path: str = Field(..., description="Путь запроса")


# Дополнительные модели для расширенной функциональности
class SitemapRequest(BaseModel):
    domain: str = Field(..., description="Домен для извлечения sitemap")
    save_to_file: Optional[bool] = Field(True, description="Сохранить в файл")


class LinkExtractionRequest(BaseModel):
    url: str = Field(..., description="URL для извлечения ссылок")
    selector: Optional[str] = Field("a[href]", description="CSS селектор для ссылок")
    filter_pattern: Optional[str] = Field(None, description="Паттерн для фильтрации ссылок")
    max_links: Optional[int] = Field(None, description="Максимальное количество ссылок")


class DataExtractionRequest(BaseModel):
    url: str = Field(..., description="URL для извлечения данных")
    selectors: Dict[str, str] = Field(..., description="Селекторы для извлечения данных")
    output_format: Optional[str] = Field("json", description="Формат вывода (json/csv/excel)")


class BulkOperationRequest(BaseModel):
    operation: str = Field(..., description="Тип операции (scrape/extract/check)")
    urls: List[str] = Field(..., description="Список URL")
    settings: Optional[Dict[str, Any]] = Field({}, description="Настройки операции")
    output_file: Optional[str] = Field(None, description="Файл для сохранения результатов")


# Конфигурационные модели
class ScraperConfig(BaseModel):
    """Конфигурация скрапера"""
    name: str = Field(..., description="Название скрапера")
    description: Optional[str] = Field(None, description="Описание скрапера")
    default_timeout: int = Field(30, description="Таймаут по умолчанию")
    max_retries: int = Field(3, description="Максимальное количество повторов")
    cache_enabled: bool = Field(True, description="Включено кеширование")
    proxy_rotation: bool = Field(False, description="Ротация прокси")
    cloudflare_bypass: bool = Field(False, description="Обход Cloudflare")
    block_images: bool = Field(False, description="Блокировать изображения")
    parallel_tasks: int = Field(1, description="Параллельные задачи")


class SystemStatus(BaseModel):
    """Статус системы"""
    status: str = Field(..., description="Общий статус системы")
    version: str = Field(..., description="Версия API")
    uptime: str = Field(..., description="Время работы")
    active_tasks: int = Field(..., description="Активных задач")
    total_requests: int = Field(..., description="Всего запросов")
    cache_hits: int = Field(..., description="Попаданий в кеш")
    proxy_count: int = Field(..., description="Количество прокси")
    memory_usage: Optional[str] = Field(None, description="Использование памяти")
    cpu_usage: Optional[str] = Field(None, description="Использование CPU") 