"""Paso 3 · Locutor: genera 03_voz.mp3 y 03_palabras.json con el tiempo de cada palabra.

Uso: python scripts/voz.py runs/X [--proveedor elevenlabs|edge] [--voz ID]

- ElevenLabs: endpoint /with-timestamps (tiempo por carácter -> tiempo por palabra).
- edge-tts:   boundary="WordBoundary" (gratis).
- Simulación: voz sintética offline (flite) con tiempos repartidos por escena.
Después: recorta el silencio inicial, acelera con atempo y normaliza a -14 LUFS.
"""
import argparse
import asyncio
import base64
import json
import os
import re
import tempfile
from pathlib import Path

import requests

from comun import (SALIDAS, alinear_escenas, cargar_config, clave, duracion_media, encargo,
                   ejecutar, escribir_json, leer_json, parar, requiere, tiempos_escenas,
                   tirada_desde_arg, tokenizar)


# ------------------------------------------------------------------ proveedores
def tts_elevenlabs(texto: str, voice_id: str, cfg: dict, idioma: str, destino: Path) -> list[dict]:
    k = clave("ELEVENLABS_API_KEY")
    if not k:
        raise RuntimeError("Falta ELEVENLABS_API_KEY")
    e = cfg["voz"]["elevenlabs"]
    body = {
        "text": texto,
        "model_id": e["modelo"],
        "voice_settings": {"stability": e["stability"], "similarity_boost": e["similarity_boost"],
                           "style": e["style"], "use_speaker_boost": e["speaker_boost"]},
    }
    r = requests.post(f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps",
                      params={"output_format": "mp3_44100_128"},
                      headers={"xi-api-key": k, "Content-Type": "application/json"},
                      json=body, timeout=180)
    if r.status_code != 200:
        raise RuntimeError(f"ElevenLabs {r.status_code}: {r.text[:300]}")
    d = r.json()
    destino.write_bytes(base64.b64decode(d["audio_base64"]))
    al = d.get("alignment") or d.get("normalized_alignment")
    chars, ini, fin = al["characters"], al["character_start_times_seconds"], al["character_end_times_seconds"]
    palabras, actual, t0, t1 = [], "", None, None
    for c, a, b in zip(chars, ini, fin):
        if c.isspace():
            if actual:
                palabras.append({"palabra": actual, "inicio": t0, "fin": t1})
            actual, t0 = "", None
            continue
        if t0 is None:
            t0 = a
        actual += c
        t1 = b
    if actual:
        palabras.append({"palabra": actual, "inicio": t0, "fin": t1})
    return palabras


def tts_edge(texto: str, voz: str, destino: Path, rate: str = "+0%") -> list[dict]:
    import edge_tts

    async def run():
        kw = {}
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if proxy:
            kw["proxy"] = proxy
        com = edge_tts.Communicate(texto, voz, rate=rate, boundary="WordBoundary", **kw)
        palabras = []
        with open(destino, "wb") as f:
            async for ch in com.stream():
                if ch["type"] == "audio":
                    f.write(ch["data"])
                elif ch["type"] == "WordBoundary":
                    ini = ch["offset"] / 1e7
                    palabras.append({"palabra": ch["text"], "inicio": ini, "fin": ini + ch["duration"] / 1e7})
        return palabras

    crudas = asyncio.run(run())
    if not crudas or destino.stat().st_size == 0:
        raise RuntimeError("edge-tts no devolvió audio")
    # edge-tts a veces agrupa varias palabras en un bloque ("Jueves 19 de noviembre"):
    # se parte en palabras repartiendo el tiempo según la longitud de cada una
    palabras = []
    for p in crudas:
        trozos = p["palabra"].split()
        if len(trozos) <= 1:
            palabras.append(p)
            continue
        total = sum(len(t) + 1 for t in trozos)
        t0, dur, acc = p["inicio"], p["fin"] - p["inicio"], 0
        for t in trozos:
            a = t0 + dur * acc / total
            acc += len(t) + 1
            palabras.append({"palabra": t, "inicio": a, "fin": t0 + dur * acc / total})
    # edge-tts no devuelve signos de puntuación: se recuperan del texto original
    orig = tokenizar(texto)
    from comun import normalizar
    j = 0
    for p in palabras:
        while j < len(orig) and normalizar(orig[j]) != normalizar(p["palabra"]):
            j += 1
        if j < len(orig):
            p["palabra"] = orig[j]
            j += 1
    return palabras


def tts_simulado(guion: dict, destino: Path) -> list[dict]:
    """Voz offline con flite. No suena a español: SOLO para probar la cadena."""
    tmp = Path(tempfile.mkdtemp())
    partes, palabras, t = [], [], 0.0
    for i, esc in enumerate(guion["escenas"]):
        txt = tmp / f"e{i}.txt"
        txt.write_text(esc["narracion"], encoding="utf-8")
        wav = tmp / f"e{i}.wav"
        ejecutar(["ffmpeg", "-y", "-f", "lavfi", "-i", f"flite=textfile={txt}:voice=slt",
                  "-ar", "44100", "-ac", "1", str(wav)])
        d = duracion_media(wav)
        ws = tokenizar(esc["narracion"])
        pesos = [len(w) + 2 for w in ws]
        total = sum(pesos)
        util_ini, util = t + 0.08, d - 0.2
        acc = 0
        for w, p in zip(ws, pesos):
            a = util_ini + util * acc / total
            acc += p
            b = util_ini + util * acc / total
            palabras.append({"palabra": w, "inicio": round(a, 3), "fin": round(b - 0.02, 3)})
        partes.append(wav)
        t += d
    lista = tmp / "lista.txt"
    lista.write_text("".join(f"file '{p}'\n" for p in partes))
    ejecutar(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lista), "-c:a", "libmp3lame",
              "-b:a", "128k", str(destino)])
    return palabras


# ------------------------------------------------------------------ post-proceso
def postprocesar(crudo: Path, salida: Path, palabras: list[dict], velocidad: float, lufs: float) -> list[dict]:
    recorte = max(0.0, palabras[0]["inicio"] - 0.04)
    filtro_base = f"atrim=start={recorte:.3f},asetpts=PTS-STARTPTS,atempo={velocidad}"
    r = ejecutar(["ffmpeg", "-hide_banner", "-i", str(crudo), "-af",
                  f"{filtro_base},loudnorm=I={lufs}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"])
    m = json.loads(re.findall(r"\{[^{}]+\}", r.stderr)[-1])
    ln = (f"loudnorm=I={lufs}:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=false")
    ejecutar(["ffmpeg", "-y", "-i", str(crudo), "-af", f"{filtro_base},{ln}", "-ar", "44100", "-ac", "2",
              "-c:a", "libmp3lame", "-b:a", "192k", str(salida)])
    out = []
    for p in palabras:
        out.append({"palabra": p["palabra"],
                    "inicio": round(max(0.0, (p["inicio"] - recorte) / velocidad), 3),
                    "fin": round(max(0.0, (p["fin"] - recorte) / velocidad), 3)})
    return out


def ajustar_lufs(path: Path, objetivo: float) -> None:
    """loudnorm se queda corto cuando limita picos: corrección final de ganancia + limitador."""
    for _ in range(2):
        actual = medir_lufs(path)
        if abs(actual - objetivo) <= 0.5:
            return
        tmp = path.with_suffix(".tmp.mp3")
        ejecutar(["ffmpeg", "-y", "-i", str(path), "-af",
                  f"volume={objetivo - actual:.2f}dB,alimiter=limit=0.89:level=false",
                  "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", str(tmp)])
        tmp.replace(path)


def medir_lufs(path: Path) -> float:
    r = ejecutar(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "ebur128", "-f", "null", "-"])
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)
    return float(m[-1]) if m else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tirada")
    ap.add_argument("--proveedor", choices=["elevenlabs", "edge"])
    ap.add_argument("--voz", help="voice_id de ElevenLabs o nombre de voz edge-tts")
    a = ap.parse_args()
    tirada = tirada_desde_arg(a.tirada)
    requiere(tirada, SALIDAS[2])
    cfg = cargar_config(tirada)
    enc = encargo(tirada)
    guion = leer_json(tirada / SALIDAS[2])
    texto = " ".join(e["narracion"].strip() for e in guion["escenas"])
    voces = cfg["idiomas"][enc["idioma"]]["voz"]
    crudo = tirada / "03_voz_cruda.mp3"
    proveedor = a.proveedor or cfg["voz"]["proveedor"]
    voz_usada = None

    if enc.get("simulacion"):
        # en pruebas también se intenta una voz real gratis (edge-tts); flite solo si no hay red
        try:
            voz_usada = voces["edge"]
            palabras = tts_edge(texto, voz_usada, crudo, cfg["voz"].get("edge_rate", "+0%"))
            proveedor = "edge"
        except Exception as ex:  # noqa: BLE001
            print(f"⚠️  edge-tts no disponible ({ex}). Voz de PRUEBA flite (no es española): solo para probar la cadena.")
            proveedor, voz_usada = "simulacion-flite", "slt"
            palabras = tts_simulado(guion, crudo)
    else:
        palabras = None
        if proveedor == "elevenlabs":
            voz_usada = a.voz or voces["elevenlabs_voice_id"]
            try:
                palabras = tts_elevenlabs(texto, voz_usada, cfg, enc["idioma"], crudo)
            except Exception as ex:  # noqa: BLE001
                if not cfg["voz"].get("respaldo_edge"):
                    parar(f"ElevenLabs falló: {ex}")
                print(f"⚠️  ElevenLabs no disponible ({ex}). Uso edge-tts de respaldo.")
                proveedor = "edge"
        if palabras is None:
            voz_usada = (a.voz if a.proveedor == "edge" and a.voz else None) or voces["edge"]
            try:
                palabras = tts_edge(texto, voz_usada, crudo, cfg["voz"].get("edge_rate", "+0%"))
            except Exception as ex:  # noqa: BLE001
                parar(f"edge-tts falló: {ex}")

    if not palabras:
        parar("El TTS no devolvió tiempos de palabras")
    final = postprocesar(crudo, tirada / "03_voz.mp3", palabras, cfg["voz"]["velocidad"], cfg["voz"]["lufs"])
    crudo.unlink(missing_ok=True)
    ajustar_lufs(tirada / "03_voz.mp3", cfg["voz"]["lufs"])
    dur = duracion_media(tirada / "03_voz.mp3")
    escenas_idx = alinear_escenas(guion, final)
    for p, e in zip(final, escenas_idx):
        p["escena"] = e + 1
    tiempos = tiempos_escenas(guion, [dict(p, escena=p["escena"] - 1) for p in final], dur,
                              cfg["video"]["cola_final_s"])
    lufs = medir_lufs(tirada / "03_voz.mp3")
    escribir_json(tirada / SALIDAS[3], {
        "proveedor": proveedor, "voz": voz_usada, "velocidad": cfg["voz"]["velocidad"],
        "lufs_medido": lufs, "duracion": round(dur, 3), "palabras": final, "escenas": tiempos,
    })
    print(f"✅ Voz lista · {proveedor} ({voz_usada}) · {dur:.1f}s · {len(final)} palabras · {lufs:.1f} LUFS")
    for t in tiempos:
        print(f"   escena {t['escena']}: {t['inicio']:6.2f}s → {t['fin']:6.2f}s ({t['duracion']:.2f}s)")
    if dur > cfg["guion"]["duracion_max_s"] + 0.5:
        print(f"⚠️  DURACIÓN EXCEDIDA: {dur:.1f}s (máx {cfg['guion']['duracion_max_s']}s). El guionista debe recortar.")
    elif dur < cfg["guion"]["duracion_min_s"] - 2:
        print(f"⚠️  Demasiado corto: {dur:.1f}s (mín {cfg['guion']['duracion_min_s']}s).")


if __name__ == "__main__":
    main()
