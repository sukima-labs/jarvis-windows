"""Descarga clips oficiales de GIPHY para la instalación personal de Jarvis."""

from __future__ import annotations

import io
import json
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image, ImageSequence


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
MAX_BYTES = 16 * 1024 * 1024


def install_clip(item: dict) -> bool:
    target = ASSETS / item["file"]
    if target.exists():
        return True
    if target.suffix.lower() != ".gif" or target.parent != ASSETS:
        raise ValueError("Entrada de vigilancia no válida")
    if "media_url" in item:
        media_url = item["media_url"]
        parsed = urlparse(media_url)
        if parsed.scheme != "https" or parsed.hostname != "media.tenor.com" or not parsed.path.endswith(".gif"):
            raise ValueError("Origen de vídeo no permitido")
    else:
        media_id = item["id"]
        if not media_id.isalnum():
            raise ValueError("Identificador de GIPHY no válido")
        media_url = f"https://media.giphy.com/media/{media_id}/giphy.gif"
    response = requests.get(media_url, timeout=25)
    response.raise_for_status()
    if len(response.content) > MAX_BYTES or not response.content.startswith((b"GIF87a", b"GIF89a")):
        raise ValueError("El archivo recibido no es un GIF válido")

    animation = Image.open(io.BytesIO(response.content))
    frames, durations = [], []
    for index, frame in enumerate(ImageSequence.Iterator(animation)):
        if index >= 100:
            break
        image = frame.convert("RGB")
        image.thumbnail((218, 78), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (218, 78), "#10131A")
        canvas.paste(image, ((218-image.width)//2, (78-image.height)//2))
        frames.append(canvas)
        durations.append(max(35, int(frame.info.get("duration", 50))))
    if not frames:
        raise ValueError("El GIF no contiene fotogramas")
    frames[0].save(target, save_all=True, append_images=frames[1:],
                   duration=durations, loop=0, optimize=True)
    print(f"Instalado: {target.name} ({len(frames)} fotogramas)")
    return True


def main() -> None:
    catalog = json.loads((ASSETS / "vigilancia_sources.json").read_text(encoding="utf-8"))
    for item in catalog:
        try:
            install_clip(item)
        except (requests.RequestException, OSError, ValueError) as exc:
            print(f"No se pudo instalar {item.get('file', 'clip')}: {exc}")


if __name__ == "__main__":
    main()
