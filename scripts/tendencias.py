"""Paso 1 · Cazador de tendencias: qué Shorts están petando AHORA.

Uso:
  python scripts/tendencias.py runs/X              # busca y deja 01_candidatos.json
  python scripts/tendencias.py runs/X --validar    # valida el 01_tendencia.json que escribe el agente

Cuota (YouTube Data API v3): search.list = 100 unidades por llamada; videos.list y
channels.list = 1 unidad por llamada (50 ids). Se hace UNA search.list por
(consulta x región) y se cachea `tendencias.cache_horas` para no gastar de más.
"""
import argparse
import hashlib
import json
import math
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from comun import (RAIZ, SALIDAS, ahora_iso, cargar_config, clave, encargo, escribir_json,
                   historial, leer_json, normalizar, parar, tirada_desde_arg)

API = "https://www.googleapis.com/youtube/v3"
CACHE_DIR = RAIZ / "canal" / "cache_tendencias"


def iso_a_segundos(d: str) -> int:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    if not m:
        return 0
    dd, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return dd * 86400 + h * 3600 + mi * 60 + s


class Cuota:
    def __init__(self):
        self.unidades = 0

    def get(self, recurso: str, coste: int, **params):
        params["key"] = clave("YOUTUBE_API_KEY")
        for intento in range(3):
            r = requests.get(f"{API}/{recurso}", params=params, timeout=30)
            if r.status_code == 200:
                self.unidades += coste
                return r.json()
            if r.status_code == 403 and "quota" in r.text.lower():
                parar("Cuota de YouTube Data API agotada por hoy (se renueva a medianoche, hora del Pacífico).")
            if r.status_code >= 500:
                time.sleep(2 * (intento + 1))
                continue
            parar(f"YouTube API {recurso} respondió {r.status_code}: {r.text[:400]}")
        parar(f"YouTube API {recurso} no responde")


def buscar_api(cfg, enc) -> tuple[list[dict], dict, int]:
    if not clave("YOUTUBE_API_KEY"):
        parar("Falta YOUTUBE_API_KEY en .env (ver README, paso 3).")
    t = cfg["tendencias"]
    lang = cfg["idiomas"][enc["idioma"]]["relevance_language"]
    consultas = [enc["tema_forzado"]] if enc.get("tema_forzado") else t["consultas"]
    desde = (datetime.now(timezone.utc) - timedelta(days=t["dias"])).strftime("%Y-%m-%dT%H:%M:%SZ")
    q = Cuota()
    ids, origen = [], {}
    for region in enc["regiones"]:
        for consulta in consultas:
            params = dict(part="id", type="video", videoDuration="short", order="viewCount",
                          publishedAfter=desde, regionCode=region, relevanceLanguage=lang,
                          maxResults=t["resultados_por_busqueda"])
            if consulta:
                params["q"] = consulta
            res = q.get("search", 100, **params)
            for it in res.get("items", []):
                vid = it["id"].get("videoId")
                if vid and vid not in origen:
                    ids.append(vid)
                    origen[vid] = f"search:{region}:{consulta}"
    detalles = []
    if t.get("usar_mas_populares") and not enc.get("tema_forzado"):
        for region in enc["regiones"]:
            res = q.get("videos", 1, part="snippet,statistics,contentDetails", chart="mostPopular",
                        regionCode=region, maxResults=50)
            for it in res.get("items", []):
                if it["id"] not in origen:
                    origen[it["id"]] = f"mostPopular:{region}"
                    detalles.append(it)
    for i in range(0, len(ids), 50):
        res = q.get("videos", 1, part="snippet,statistics,contentDetails", id=",".join(ids[i:i + 50]))
        detalles.extend(res.get("items", []))
    canales = list({d["snippet"]["channelId"] for d in detalles})
    subs = {}
    for i in range(0, len(canales), 50):
        res = q.get("channels", 1, part="statistics", id=",".join(canales[i:i + 50]))
        for c in res.get("items", []):
            st = c.get("statistics", {})
            subs[c["id"]] = None if st.get("hiddenSubscriberCount") else int(st.get("subscriberCount", 0))
    for d in detalles:
        d["_subs"] = subs.get(d["snippet"]["channelId"])
        d["_origen"] = origen.get(d["id"])
    return detalles, origen, q.unidades


def buscar_simulado(enc) -> tuple[list[dict], dict, int]:
    datos = json.loads((RAIZ / "scripts" / "fixtures" / "tendencias_ejemplo.json").read_text(encoding="utf-8"))
    lang = enc["idioma"]
    for d in datos:
        d["_origen"] = "simulacion"
    datos = [d for d in datos if d["snippet"].get("defaultAudioLanguage", lang) == lang]
    return datos, {}, 0


def metricas(detalles: list[dict], max_dur: int) -> list[dict]:
    ahora = datetime.now(timezone.utc)
    out = []
    for d in detalles:
        dur = iso_a_segundos(d.get("contentDetails", {}).get("duration", ""))
        if dur == 0 or dur > max_dur:
            continue
        st = d.get("statistics", {})
        views = int(st.get("viewCount", 0))
        likes = int(st.get("likeCount", 0)) if "likeCount" in st else None
        coms = int(st.get("commentCount", 0)) if "commentCount" in st else None
        pub = datetime.fromisoformat(d["snippet"]["publishedAt"].replace("Z", "+00:00"))
        horas = max((ahora - pub).total_seconds() / 3600, 1.0)
        subs = d.get("_subs")
        vph = views / horas
        ratio_subs = round(views / subs, 2) if subs else None
        out.append({
            "video_id": d["id"],
            "url": f"https://www.youtube.com/shorts/{d['id']}",
            "titulo": d["snippet"]["title"],
            "canal": d["snippet"].get("channelTitle"),
            "publicado": d["snippet"]["publishedAt"],
            "horas_desde_publicacion": round(horas, 1),
            "duracion_s": dur,
            "views": views,
            "likes": likes,
            "comentarios": coms,
            "suscriptores_canal": subs,
            "views_por_hora": round(vph),
            "views_por_suscriptor": ratio_subs,
            "like_ratio": round(likes / views, 4) if likes and views else None,
            "coment_ratio": round(coms / views, 5) if coms and views else None,
            # Señal de TEMA: un canal pequeño que revienta pesa más que un canal gigante
            "puntuacion_tema": round(math.log10(vph + 1) * (1 + math.log10((ratio_subs or 1) + 1)), 3),
            "categoria_id": d["snippet"].get("categoryId"),
            "tags": (d["snippet"].get("tags") or [])[:10],
            "descripcion": (d["snippet"].get("description") or "")[:300],
            "origen": d.get("_origen"),
        })
    out.sort(key=lambda x: x["views_por_hora"], reverse=True)
    return out


def temas_recientes(dias: int) -> list[dict]:
    limite = datetime.now(timezone.utc) - timedelta(days=dias)
    out = []
    for h in historial():
        try:
            f = datetime.fromisoformat(h.get("fecha", "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if f >= limite:
            out.append({"tema": h.get("tema"), "fecha": h.get("fecha"), "formato": h.get("formato"),
                        "idioma": h.get("idioma")})
    return out


def similitud(a: str, b: str) -> float:
    sa = {normalizar(w) for w in a.split() if len(normalizar(w)) > 3}
    sb = {normalizar(w) for w in b.split() if len(normalizar(w)) > 3}
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def validar(tirada: Path, cfg: dict) -> None:
    p = tirada / SALIDAS[1]
    if not p.exists():
        parar("No existe 01_tendencia.json")
    t = leer_json(p)
    errores = []
    for campo in ["tema", "idioma", "angulo", "por_que", "videos_referencia", "palabras_clave"]:
        if not t.get(campo):
            errores.append(f"falta el campo '{campo}'")
    for sub in ["patron_gancho", "formato", "emocion"]:
        if not (t.get("por_que") or {}).get(sub):
            errores.append(f"falta por_que.{sub}")
    for h in temas_recientes(cfg["canal"]["dias_sin_repetir_tema"]):
        s = similitud(t.get("tema", ""), h["tema"] or "")
        if s >= 0.5:
            errores.append(f"tema demasiado parecido a uno del historial ({h['tema']!r}, similitud {s:.2f})")
    if errores:
        parar("01_tendencia.json no válido:\n - " + "\n - ".join(errores))
    print("✅ 01_tendencia.json válido")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tirada")
    ap.add_argument("--validar", action="store_true")
    ap.add_argument("--sin-cache", action="store_true")
    a = ap.parse_args()
    tirada = tirada_desde_arg(a.tirada)
    cfg = cargar_config(tirada)
    enc = encargo(tirada)
    if a.validar:
        return validar(tirada, cfg)

    t = cfg["tendencias"]
    clave_cache = hashlib.md5(json.dumps([enc["idioma"], enc["regiones"], enc.get("tema_forzado"),
                                          t["consultas"], t["dias"], enc.get("simulacion")]).encode()).hexdigest()[:12]
    cache = CACHE_DIR / f"{clave_cache}.json"
    if (not a.sin_cache and cache.exists()
            and time.time() - cache.stat().st_mtime < t["cache_horas"] * 3600):
        datos = leer_json(cache)
        detalles, unidades = datos["detalles"], 0
        print(f"♻️  Usando búsqueda en caché ({cache.name}), 0 unidades de cuota gastadas")
    else:
        if enc.get("simulacion"):
            detalles, _, unidades = buscar_simulado(enc)
        elif not clave("YOUTUBE_API_KEY"):
            # Plan B sin clave: el agente buscará las tendencias en la web (WebSearch)
            escribir_json(tirada / "01_candidatos.json", {
                "fecha": ahora_iso(), "idioma": enc["idioma"], "regiones": enc["regiones"],
                "fuente": "sin_api", "formato": enc.get("formato"),
                "aviso": "No hay YOUTUBE_API_KEY: busca con WebSearch qué temas de Shorts/curiosidades están "
                         "funcionando esta semana y elige uno para el formato del encargo.",
                "unidades_cuota_gastadas": 0, "total_analizados": 0,
                "top_por_views_hora": [], "top_por_views_suscriptor": [],
                "temas_ya_usados": temas_recientes(cfg["canal"]["dias_sin_repetir_tema"]),
                "temas_prohibidos": cfg["canal"]["temas_prohibidos"],
            })
            print("⚠️  Sin YOUTUBE_API_KEY: modo web. El agente debe buscar tendencias con WebSearch.")
            return
        else:
            detalles, _, unidades = buscar_api(cfg, enc)
        escribir_json(cache, {"fecha": ahora_iso(), "detalles": detalles})

    cands = metricas(detalles, t["max_duracion_s"])
    if not cands:
        parar("La búsqueda no devolvió ningún Short ≤ %ss. Prueba otras consultas en config.yaml." % t["max_duracion_s"])
    top = cands[: t["top_candidatos"]]
    por_ratio = sorted([c for c in cands if c["views_por_suscriptor"]],
                       key=lambda c: c["views_por_suscriptor"], reverse=True)[:10]
    escribir_json(tirada / "01_candidatos.json", {
        "fecha": ahora_iso(),
        "idioma": enc["idioma"],
        "regiones": enc["regiones"],
        "tema_forzado": enc.get("tema_forzado"),
        "simulacion": bool(enc.get("simulacion")),
        "unidades_cuota_gastadas": unidades,
        "total_analizados": len(cands),
        "top_por_views_hora": top,
        "top_por_views_suscriptor": por_ratio,
        "temas_ya_usados": temas_recientes(cfg["canal"]["dias_sin_repetir_tema"]),
        "temas_prohibidos": cfg["canal"]["temas_prohibidos"],
    })
    print(f"Analizados {len(cands)} Shorts ≤{t['max_duracion_s']}s · cuota gastada: {unidades} unidades\n")
    print(f"{'views/h':>9} {'v/subs':>7} {'dur':>4}  título")
    for c in top[:15]:
        print(f"{c['views_por_hora']:>9} {str(c['views_por_suscriptor'] or '-'):>7} {c['duracion_s']:>4}  {c['titulo'][:70]}")
    print(f"\n→ Detalle completo en {tirada / '01_candidatos.json'}")


if __name__ == "__main__":
    main()
