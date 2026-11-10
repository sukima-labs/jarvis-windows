"""
Basit hava durumu ozeti — uzaktaki bir servis uzerinden calisir.

Varsayilan konum:
- JARVIS_WEATHER_LOCATION env varsa onu kullanir
- yoksa Hatay varsayilir
"""

from __future__ import annotations

import os
import threading
import time

import requests
from app_config import get_app_config_value, save_app_config


_LOCATION_CACHE_SECONDS = 900
_location_cache = {"city": "", "region": "", "country": "", "checked_at": 0.0}
_location_lock = threading.Lock()


def _refresh_ip_location() -> None:
    now = time.monotonic()
    with _location_lock:
        if _location_cache["city"] and now - _location_cache["checked_at"] < _LOCATION_CACHE_SECONDS:
            return

        city = ""
        region = ""
        country = ""
        try:
            # El servicio recibe la IP pública y devuelve solo la ubicación aproximada.
            response = requests.get(
                "https://ipapi.co/json/",
                timeout=5,
                headers={"User-Agent": "JARVIS Windows"},
            )
            response.raise_for_status()
            data = response.json()
            if not data.get("error"):
                city = str(data.get("city") or "").strip()
                region = str(data.get("region") or "").strip()
                country = str(data.get("country_name") or "").strip()
        except Exception:
            pass

        if not city:
            city = "Alcalá de Henares"
        _location_cache.update(city=city, region=region, country=country, checked_at=now)


def get_location_region() -> str:
    _refresh_ip_location()
    return "|".join((_location_cache["region"], _location_cache["country"])).strip("|")


def get_current_city() -> str:
    """Usa la ciudad manual actual y la renueva al cambiar de región por IP."""
    env_override = str(os.environ.get("JARVIS_WEATHER_LOCATION") or "").strip()
    if env_override:
        return env_override

    _refresh_ip_location()
    override = str(get_app_config_value("weather_location", "") or "").strip()
    override_region = str(get_app_config_value("weather_location_region", "") or "").strip()
    detected_region = get_location_region()
    if override:
        if not override_region or not detected_region or override_region.casefold() == detected_region.casefold():
            return override
        # El equipo ya está en otra región o país: vuelve al seguimiento automático.
        save_app_config({"weather_location": "", "weather_location_region": ""})
    return _location_cache["city"]


def get_weather_summary(location: str | None = None) -> str:
    target = (location or get_current_city()).strip()
    try:
        geocoding = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": target, "count": 1, "language": "es", "format": "json"},
            timeout=10,
            headers={"User-Agent": "JARVIS Windows"},
        )
        geocoding.raise_for_status()
        places = geocoding.json().get("results") or []
        if not places:
            return f"No encontré la ciudad {target}."
        place = places[0]

        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
                "timezone": "auto",
                "forecast_days": 1,
            },
            timeout=10,
            headers={"User-Agent": "JARVIS Windows"},
        )
        response.raise_for_status()
        current = response.json().get("current") or {}
        temp_c = current.get("temperature_2m")
        feels_like = current.get("apparent_temperature")
        humidity = current.get("relative_humidity_2m")
        wind_kmh = current.get("wind_speed_10m")
        weather_code = current.get("weather_code")

        weather_codes_es = {
            0: "despejado",
            1: "mayormente despejado",
            2: "parcialmente nublado",
            3: "nublado",
            45: "niebla",
            48: "niebla con escarcha",
            51: "llovizna ligera",
            53: "llovizna moderada",
            55: "llovizna intensa",
            56: "llovizna helada ligera",
            57: "llovizna helada intensa",
            61: "lluvia ligera",
            63: "lluvia moderada",
            65: "lluvia intensa",
            66: "lluvia helada ligera",
            67: "lluvia helada intensa",
            71: "nieve ligera",
            73: "nieve moderada",
            75: "nieve intensa",
            77: "granos de nieve",
            80: "chubascos ligeros",
            81: "chubascos moderados",
            82: "chubascos intensos",
            85: "chubascos de nieve ligeros",
            86: "chubascos de nieve intensos",
            95: "tormenta",
            96: "tormenta con granizo ligero",
            99: "tormenta con granizo intenso",
        }

        parts = []
        if temp_c is not None:
            parts.append(f"{temp_c:g} °C")
        if weather_code is not None:
            parts.append(weather_codes_es.get(int(weather_code), "condiciones variables"))
        if feels_like is not None and feels_like != temp_c:
            parts.append(f"sensación de {feels_like:g} °C")
        if humidity:
            parts.append(f"humedad {humidity}%")
        if wind_kmh is not None:
            parts.append(f"viento {wind_kmh:g} km/h")

        if not parts:
            return "No hay datos del clima en este momento."

        return f"{target}: " + ", ".join(parts) + "."
    except Exception:
        return "No se pudo consultar el clima en este momento."

