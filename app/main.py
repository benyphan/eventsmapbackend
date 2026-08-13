import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine
from app.routers import auth, users, events, admin, notifications, posts, friends, chats, referrals, shop
from app.ratelimit import RateLimiter

# В проде используйте Alembic-миграции вместо create_all
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Events Map API")

ALLOWED_ORIGINS = [
    "https://eventsmapbrowse.ru",
    "https://www.eventsmapbrowse.ru",
    "https://api.eventsmapbrowse.ru",
    "http://localhost:19006",
    "http://localhost:8081",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(events.router)
app.include_router(admin.router)
app.include_router(notifications.router)
app.include_router(posts.router)
app.include_router(friends.router)
app.include_router(chats.router)
app.include_router(referrals.router)
app.include_router(shop.router)

BASE_DIR = Path(__file__).resolve().parents[1]
app.mount("/uploads", StaticFiles(directory=str(BASE_DIR / "uploads")), name="uploads")
app.mount("/admin", StaticFiles(directory=str(BASE_DIR / "admin_static"), html=True), name="admin")


@app.get("/api/tiles")
def tile_proxy(
    request: Request,
    x: int,
    y: int,
    z: int,
    l: str = "map",
    scale: int = 1,
    lang: str = "ru_RU",
):
    """Прокси тайлов Яндекса: эмулятор/устройство получает тайлы через хост,
    который имеет прямой доступ к tile-серверам Яндекса."""
    import urllib.request

    from fastapi import HTTPException
    from fastapi.responses import Response

    # Валидация координат (Slippy map): x,y в диапазоне [0, 2^z-1], z не глубже 19
    if z < 0 or z > 19:
        raise HTTPException(status_code=400, detail="Недопустимый z")
    max_tile = (1 << z) - 1
    if x < 0 or x > max_tile or y < 0 or y > max_tile:
        raise HTTPException(status_code=400, detail="Тайл вне карты")
    if scale not in (1, 2):
        raise HTTPException(status_code=400, detail="Недопустимый scale")
    if len(l) > 16 or len(lang) > 16:
        raise HTTPException(status_code=400, detail="Недопустимые параметры")

    # Rate limit по IP, чтобы прокси не превращали в бесплатный ретранслятор
    client_ip = request.client.host if request.client else "unknown"
    ok, wait = TILE_LIMITER.allow(f"tile:{client_ip}")
    if not ok:
        raise HTTPException(status_code=429, detail=f"Слишком много запросов. Подождите {wait} с.")

    cache_key = (x, y, z, l, scale, lang)
    cached = TILE_CACHE.get(cache_key)
    if cached is not None:
        return Response(content=cached, media_type="image/png")

    url = (
        "https://core-renderer-tiles.maps.yandex.net/tiles"
        f"?l={l}&x={x}&y={y}&z={z}&scale={scale}&lang={lang}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
    except Exception:
        raise HTTPException(status_code=502, detail="Не удалось получить тайл")
    if len(TILE_CACHE) > 500:
        TILE_CACHE.clear()
    TILE_CACHE[cache_key] = data
    return Response(content=data, media_type="image/png")


TILE_CACHE = {}
# 120 запросов тайлов в минуту на IP — хватает для карты, но не для абьюза
TILE_LIMITER = RateLimiter(max_count=120, window_seconds=60)


@app.get("/api/geocode")
def geocode_proxy(q: str = ""):
    """Поиск координат по адресу/названию места через Nominatim (OpenStreetMap).

    Бесплатный геокодер без ключа. Ответы кэшируем и держим суммарный rate limit,
    чтобы не нарушать политику внешнего сервиса (~1 запрос/сек).
    """
    import urllib.request
    from urllib.parse import quote

    from fastapi import HTTPException
    from fastapi.responses import JSONResponse

    q = (q or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Пустой запрос")
    if len(q) > 200:
        raise HTTPException(status_code=400, detail="Слишком длинный запрос")

    cache_key = q.lower()
    cached = GEOCODE_CACHE.get(cache_key)
    if cached is not None:
        return JSONResponse(cached)

    ok, wait = GEOCODE_LIMITER.allow("geocode:global")
    if not ok:
        raise HTTPException(status_code=429, detail=f"Слишком много запросов. Подождите {wait} с.")

    url = "https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=" + quote(q)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "EventsMapApp/1.0 (https://eventsmapbrowse.ru)",
            "Referer": "https://eventsmapbrowse.ru",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            rows = json.loads(resp.read().decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=502, detail="Не удалось получить ответ геокодера")

    if rows:
        r = rows[0]
        result = {
            "found": True,
            "q": q,
            "lat": float(r["lat"]),
            "lng": float(r["lon"]),
            "name": r.get("display_name"),
        }
    else:
        result = {"found": False, "q": q}

    if len(GEOCODE_CACHE) > 2000:
        GEOCODE_CACHE.clear()
    GEOCODE_CACHE[cache_key] = result
    return JSONResponse(result)


GEOCODE_CACHE = {}
# Nominatim разрешает ~1 запрос/сек; 40/мин суммарно с кэшем — безопасно
GEOCODE_LIMITER = RateLimiter(max_count=40, window_seconds=60)


@app.get("/")
def health_check():
    return {"status": "ok"}
