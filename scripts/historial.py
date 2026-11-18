"""Apunta (o actualiza) una tirada en canal/historial.json.

Uso: python scripts/historial.py runs/X
"""
import argparse
from pathlib import Path

from comun import (HISTORIAL_PATH, SALIDAS, ahora_iso, escribir_json, historial, leer_json,
                   tirada_desde_arg)


def _leer(t: Path, n: str) -> dict:
    p = t / n
    return leer_json(p) if p.exists() else {}


def apuntar(tirada: Path) -> dict:
    enc = _leer(tirada, SALIDAS[0])
    ten = _leer(tirada, SALIDAS[1])
    gui = _leer(tirada, SALIDAS[2])
    mon = _leer(tirada, "05_montaje.json")
    mini = _leer(tirada, SALIDAS[6])
    meta = _leer(tirada, "07_metadatos.json")
    pub = _leer(tirada, SALIDAS[7])
    entrada = {
        "tirada": enc.get("tirada", tirada.name),
        "fecha": ahora_iso(),
        "marca": enc.get("marca"),
        "canal": enc.get("canal"),
        "idioma": enc.get("idioma"),
        "tema": ten.get("tema"),
        "formato": gui.get("formato"),
        "formato_id": enc.get("formato"),
        "gancho": gui.get("gancho"),
        "titulo": meta.get("titulo"),
        "duracion_s": mon.get("duracion"),
        "musica": mon.get("musica"),
        "miniatura": (mini.get("ganadora") or {}).get("texto"),
        "modo_subida": pub.get("modo"),
        "estado": pub.get("estado"),
        "video_id": pub.get("video_id"),
        "url": pub.get("url"),
        "privacidad": pub.get("privacidad"),
        "simulacion": bool(enc.get("simulacion")),
    }
    datos = historial(incluir_simulaciones=True)
    previa = next((h for h in datos if h.get("tirada") == entrada["tirada"]), None)
    if previa:
        entrada["fecha"] = previa.get("fecha", entrada["fecha"])
        previa.update(entrada)
    else:
        datos.append(entrada)
    escribir_json(HISTORIAL_PATH, datos)
    return entrada


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("tirada")
    e = apuntar(tirada_desde_arg(ap.parse_args().tirada))
    print(f"📒 Apuntado en historial: {e['tema']} · {e['estado']} · {e['url'] or 'sin url'}")
