"""Paso 4 · Director de escenas: material visual de cada escena.

Uso:
  python scripts/escenas.py runs/X                                  # todas las escenas
  python scripts/escenas.py runs/X --escena 3 --busqueda "shark underwater close up"
  python scripts/escenas.py runs/X --escena 3 --proveedor openai --prompt "..."
  python scripts/escenas.py runs/X --aprobar 1,2,3,4,5,6            # marca escenas revisadas y OK
  python scripts/escenas.py runs/X --validar

Deja 04_escenas/escena_XX.(mp4|png), 04_escenas/frame_XX.jpg y 04_escenas.json.
"""
import argparse
import base64
import shutil
import textwrap
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

from comun import (RAIZ, SALIDAS, ahora_iso, cargar_config, clave, duracion_media, encargo,
                   ejecutar, escribir_json, leer_json, parar, requiere, tirada_desde_arg)

USADOS = RAIZ / "canal" / "clips_usados.json"
FUENTE = RAIZ / "assets" / "fonts" / "Anton-Regular.ttf"


# ------------------------------------------------------------------ utilidades
def clips_usados_recientes(cfg, tirada_actual: str) -> set:
    if not USADOS.exists():
        return set()
    datos = leer_json(USADOS)
    tiradas = []
    for d in datos:
        if d["tirada"] != tirada_actual and d["tirada"] not in tiradas:
            tiradas.append(d["tirada"])
    recientes = set(tiradas[-cfg["visual"]["pexels"]["no_repetir_en_ultimas_tiradas"]:])
    return {d["id"] for d in datos if d["tirada"] in recientes}


def registrar_clips(tirada_nombre: str, ids: list) -> None:
    datos = leer_json(USADOS) if USADOS.exists() else []
    datos = [d for d in datos if d["tirada"] != tirada_nombre]
    datos += [{"tirada": tirada_nombre, "id": i} for i in ids if i]
    escribir_json(USADOS, datos)


def extraer_frame(archivo: Path, tipo: str, destino: Path, t: float) -> None:
    """Fotograma tal y como se verá (recortado a 9:16), a 540x960 para revisarlo."""
    vf = "scale=540:960:force_original_aspect_ratio=increase,crop=540:960"
    if tipo == "video":
        ejecutar(["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", str(archivo), "-frames:v", "1", "-vf", vf,
                  "-q:v", "3", str(destino)])
    else:
        ejecutar(["ffmpeg", "-y", "-i", str(archivo), "-frames:v", "1", "-vf", vf, "-q:v", "3", str(destino)])


# ------------------------------------------------------------------ proveedores
def pexels(busqueda: str, necesaria: float, excluir: set, cfg, destino: Path) -> dict | None:
    k = clave("PEXELS_API_KEY")
    if not k:
        raise RuntimeError("Falta PEXELS_API_KEY")
    p = cfg["visual"]["pexels"]
    r = requests.get("https://api.pexels.com/videos/search", headers={"Authorization": k},
                     params={"query": busqueda, "orientation": "portrait", "size": "medium",
                             "per_page": p["resultados"]}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Pexels {r.status_code}: {r.text[:200]}")
    candidatos = []
    for v in r.json().get("videos", []):
        if v["id"] in excluir or v["height"] < v["width"]:
            continue
        files = [f for f in v["video_files"] if f.get("height") and f["height"] >= p["min_altura"]
                 and f["height"] > f["width"] and f.get("file_type") == "video/mp4"]
        if not files:
            continue
        f = min(files, key=lambda f: abs(f["height"] - 1920))
        # preferir clips que cubren la escena sin bucle y no excesivamente largos
        puntos = (0 if v["duration"] >= necesaria else 1, abs(f["height"] - 1920) / 1000)
        candidatos.append((puntos, v, f))
    if not candidatos:
        return None
    candidatos.sort(key=lambda c: c[0])
    _, v, f = candidatos[0]
    with requests.get(f["link"], stream=True, timeout=120) as dl:
        dl.raise_for_status()
        with open(destino, "wb") as out:
            for chunk in dl.iter_content(1 << 16):
                out.write(chunk)
    return {"pexels_id": v["id"], "autor": v["user"]["name"], "url_fuente": v["url"],
            "duracion_clip": v["duration"], "resolucion": f"{f['width']}x{f['height']}"}


def cloudflare_imagen(prompt: str, cfg, destino: Path, estilo: str = "") -> dict:
    """Workers AI (Flux). GRATIS: 10.000 neuronas/día con una cuenta de Cloudflare sin tarjeta."""
    cuenta, token = clave("CLOUDFLARE_ACCOUNT_ID"), clave("CLOUDFLARE_API_TOKEN")
    if not cuenta:
        raise RuntimeError("Falta CLOUDFLARE_ACCOUNT_ID")
    c = cfg["visual"].get("cloudflare", {})
    modelo = c.get("modelo", "@cf/black-forest-labs/flux-1-schnell")
    prompt_final = ((estilo.strip() + " ") if estilo else "") + prompt + (
        ". Tall vertical portrait framing, single clear subject in the center, cinematic lighting, "
        "ultra detailed, no text, no letters, no watermark.")
    body = {"prompt": prompt_final[:2000], "steps": int(c.get("pasos", 8))}
    if c.get("ancho") and c.get("alto"):
        body.update(width=int(c["ancho"]), height=int(c["alto"]))
    cab = {"Authorization": f"Bearer {token or 'proxy'}"}   # en la nube el proxy inyecta el token
    for intento in range(3):
        r = requests.post(f"https://api.cloudflare.com/client/v4/accounts/{cuenta}/ai/run/{modelo}",
                          headers=cab, json=body, timeout=180)
        if r.status_code == 429 or r.status_code >= 500:
            import time
            time.sleep(5 * (intento + 1))
            continue
        break
    if r.status_code != 200:
        if "neurons" in r.text.lower() or r.status_code == 429:
            raise RuntimeError("Cloudflare: cupo gratis diario agotado (se renueva a las 00:00 UTC)")
        raise RuntimeError(f"Cloudflare {r.status_code}: {r.text[:300]}")
    if r.headers.get("content-type", "").startswith("image/"):
        destino.write_bytes(r.content)
    else:
        img = (r.json().get("result") or {}).get("image")
        if not img:
            raise RuntimeError(f"Cloudflare no devolvió imagen: {r.text[:300]}")
        destino.write_bytes(base64.b64decode(img))
    return {"modelo": modelo, "prompt_final": prompt_final}


def proveedor_ia(cfg) -> str:
    """Qué generador de imágenes usar: el de config o, en 'auto', el primero que tenga clave."""
    p = cfg["visual"].get("ia", "auto")
    if p != "auto":
        return p
    if clave("CLOUDFLARE_ACCOUNT_ID"):
        return "cloudflare"
    if clave("OPENAI_API_KEY"):
        return "openai"
    raise RuntimeError("No hay generador de imágenes: pon CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_API_TOKEN "
                       "(gratis) u OPENAI_API_KEY en .env")


def imagen_ia(prompt: str, cfg, destino: Path, estilo: str = "") -> dict:
    p = proveedor_ia(cfg)
    info = (cloudflare_imagen if p == "cloudflare" else openai_imagen)(prompt, cfg, destino, estilo)
    info["fuente"] = p
    return info


def openai_imagen(prompt: str, cfg, destino: Path, estilo: str = "") -> dict:
    k = clave("OPENAI_API_KEY")
    if not k:
        raise RuntimeError("Falta OPENAI_API_KEY")
    o = cfg["visual"]["openai"]
    prompt_final = ((estilo.strip() + " ") if estilo else "") + prompt + (
        ". Vertical 9:16 composition, subject centered in the middle third, "
        "cinematic lighting, high detail, no text, no letters, no watermark.")
    r = requests.post("https://api.openai.com/v1/images/generations",
                      headers={"Authorization": f"Bearer {k}"},
                      json={"model": o["modelo"], "prompt": prompt_final, "size": o["tamano"],
                            "quality": o["calidad"], "n": 1}, timeout=300)
    if r.status_code != 200:
        raise RuntimeError(f"OpenAI {r.status_code}: {r.text[:300]}")
    d = r.json()["data"][0]
    if d.get("b64_json"):
        destino.write_bytes(base64.b64decode(d["b64_json"]))
    else:
        destino.write_bytes(requests.get(d["url"], timeout=120).content)
    return {"modelo": o["modelo"], "prompt_final": prompt_final}


PALETA = [((20, 30, 80), (200, 60, 120)), ((10, 70, 60), (230, 200, 60)), ((60, 10, 90), (40, 180, 220)),
          ((90, 30, 10), (240, 150, 40)), ((15, 15, 15), (90, 90, 200)), ((0, 60, 120), (0, 200, 160))]


def simulado(i: int, esc: dict, necesaria: float, tipo: str, destino: Path) -> dict:
    """Material de prueba: imágenes degradado con el texto 'visual' y clips horizontales sintéticos."""
    if tipo == "imagen":
        a, b = PALETA[i % len(PALETA)]
        img = Image.new("RGB", (1024, 1536))
        dr = ImageDraw.Draw(img)
        for y in range(1536):
            k = y / 1535
            dr.line([(0, y), (1024, y)], fill=tuple(int(a[c] * (1 - k) + b[c] * k) for c in range(3)))
        for r_ in range(6):
            cx, cy = 200 + (i * 137 + r_ * 211) % 640, 300 + (i * 91 + r_ * 173) % 900
            dr.ellipse([cx - 90, cy - 90, cx + 90, cy + 90], outline=(255, 255, 255), width=4)
        f = ImageFont.truetype(str(FUENTE), 64)
        txt = "\n".join(textwrap.wrap(f"ESCENA {i + 1}: {esc['visual']}".upper(), 22))
        dr.multiline_text((512, 768), txt, font=f, fill=(255, 255, 255), anchor="mm", align="center",
                          stroke_width=3, stroke_fill=(0, 0, 0))
        img.save(destino)
        return {"fuente": "simulacion"}
    fuentes = ["testsrc2=s=1280x720:r=30", "mandelbrot=s=1280x720:r=30", "life=s=1280x720:r=30:mold=10:ratio=0.2"]
    src = fuentes[i % len(fuentes)]
    dur = max(necesaria * 0.7, 2.0)  # a propósito más corto a veces, para probar el bucle
    ejecutar(["ffmpeg", "-y", "-f", "lavfi", "-i", src, "-t", f"{dur:.2f}", "-vf",
              f"drawtext=fontfile={FUENTE}:text='ESCENA {i + 1}':fontsize=90:fontcolor=white:"
              "borderw=5:x=(w-tw)/2:y=(h-th)/2", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset",
              "veryfast", str(destino)])
    return {"fuente": "simulacion", "duracion_clip": dur, "resolucion": "1280x720"}


# ------------------------------------------------------------------ proceso de una escena
def hacer_escena(i, esc, necesaria, cfg, enc, tirada, carpeta, excluir, proveedor, busqueda, prompt, previo,
                 estilo=""):
    intentos = (previo or {}).get("intentos", 0) + 1
    if intentos > cfg["visual"]["max_reintentos_por_escena"] + 1:
        print(f"⚠️  escena {i + 1}: superado el máximo de reintentos ({cfg['visual']['max_reintentos_por_escena']}).")
    for viejo in carpeta.glob(f"escena_{i + 1:02d}.*"):
        viejo.unlink()
    busqueda = busqueda or esc["busqueda_stock"]
    prompt = prompt or esc["prompt_imagen"]
    info, tipo = None, None
    if enc.get("simulacion"):
        tipo = "video" if (i % 2 == 0 and proveedor != "openai") else "imagen"
        archivo = carpeta / f"escena_{i + 1:02d}.{'mp4' if tipo == 'video' else 'png'}"
        info = simulado(i, esc, necesaria, tipo, archivo)
    else:
        if proveedor in ("pexels", "mixto"):
            archivo = carpeta / f"escena_{i + 1:02d}.mp4"
            try:
                info = pexels(busqueda, necesaria, excluir, cfg, archivo)
            except RuntimeError as ex:
                if proveedor == "pexels":
                    parar(f"escena {i + 1}: {ex}")
                print(f"⚠️  escena {i + 1}: Pexels falló ({ex}); uso imagen IA")
            if info:
                tipo = "video"
            elif proveedor == "pexels":
                parar(f"escena {i + 1}: Pexels no tiene clips verticales para '{busqueda}'. Cambia la búsqueda.")

        if info is None:
            archivo = carpeta / f"escena_{i + 1:02d}.png"
            try:
                info = imagen_ia(prompt, cfg, archivo, estilo)
            except RuntimeError as ex:
                parar(f"escena {i + 1}: {ex}")
            tipo = "imagen"
        else:
            info.setdefault("fuente", "pexels")
    frame = carpeta / f"frame_{i + 1:02d}.jpg"
    t = min(necesaria / 2, (info.get("duracion_clip") or necesaria) / 2) if tipo == "video" else 0
    extraer_frame(archivo, tipo, frame, t)
    if tipo == "video":
        info["duracion_clip"] = round(duracion_media(archivo), 2)
    return {
        "escena": i + 1, "tipo": tipo, "archivo": str(archivo.relative_to(tirada)),
        "frame": str(frame.relative_to(tirada)), "narracion": esc["narracion"], "visual": esc["visual"],
        "busqueda": busqueda if tipo == "video" else None, "prompt": prompt if tipo == "imagen" else None,
        "duracion_necesaria": round(necesaria, 3), "intentos": intentos,
        "revisado": False, "encaja": None,
        "movimiento": (previo or {}).get("movimiento") or esc.get("movimiento"),
        "efecto": (previo or {}).get("efecto") or esc.get("efecto"),
        "recorte": (previo or {}).get("recorte") or esc.get("recorte"),
        **info,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tirada")
    ap.add_argument("--escena", type=int, help="rehacer solo esta escena (1..N)")
    ap.add_argument("--busqueda")
    ap.add_argument("--prompt")
    ap.add_argument("--proveedor", choices=["ia", "pexels", "openai", "cloudflare", "mixto"])
    ap.add_argument("--aprobar", help="lista de escenas revisadas que encajan, p. ej. 1,2,3")
    ap.add_argument("--validar", action="store_true")
    ap.add_argument("--importar", help="usa este archivo (imagen o vídeo) para --escena N")
    ap.add_argument("--fuente", default="ia", help="origen del archivo importado: ia | pexels | propio")
    ap.add_argument("--recorte", help="encuadre de la escena: cx,cy,zoom (0-1, 0-1, >=1). Ej: 0.5,0.35,1.8")
    ap.add_argument("--movimiento", help="push_in | pull_out | pan_left | pan_right | tilt_up | tilt_down | drift")
    ap.add_argument("--efecto", help="lista separada por comas: flash, shake, boom, alarma, cuenta_atras, riser")
    a = ap.parse_args()
    tirada = tirada_desde_arg(a.tirada)
    requiere(tirada, SALIDAS[2], SALIDAS[3], "03_voz.mp3")
    cfg = cargar_config(tirada)
    enc = encargo(tirada)
    guion = leer_json(tirada / SALIDAS[2])
    voz = leer_json(tirada / SALIDAS[3])
    carpeta = tirada / "04_escenas"
    carpeta.mkdir(exist_ok=True)
    salida = tirada / SALIDAS[4]
    datos = leer_json(salida) if salida.exists() else {"escenas": []}
    por_num = {e["escena"]: e for e in datos["escenas"]}

    if a.aprobar or a.validar:
        if not salida.exists():
            parar("Aún no existe 04_escenas.json")
        if a.aprobar:
            for n in [int(x) for x in a.aprobar.split(",") if x.strip()]:
                if n in por_num:
                    por_num[n]["revisado"] = True
                    por_num[n]["encaja"] = True
            datos["escenas"] = [por_num[k] for k in sorted(por_num)]
            escribir_json(salida, datos)
        pend = [e["escena"] for e in datos["escenas"] if not (e.get("revisado") and e.get("encaja"))]
        if len(datos["escenas"]) != len(guion["escenas"]):
            parar(f"04_escenas.json tiene {len(datos['escenas'])} escenas y el guion {len(guion['escenas'])}")
        if pend:
            parar(f"Escenas sin revisar o que no encajan: {pend}")
        print("✅ Todas las escenas revisadas y aprobadas")
        return

    if a.recorte or a.movimiento or a.efecto or a.importar:
        if not a.escena:
            parar("--importar/--recorte/--movimiento/--efecto necesitan --escena N")
    if a.importar:
        i = a.escena - 1
        if not 0 <= i < len(guion["escenas"]):
            parar(f"La escena {a.escena} no existe")
        src = Path(a.importar).expanduser().resolve()
        if not src.exists():
            parar(f"No existe {src}")
        tipo = "video" if src.suffix.lower() in (".mp4", ".mov", ".webm", ".mkv") else "imagen"
        destino = carpeta / f"escena_{a.escena:02d}{src.suffix.lower()}"
        for viejo in carpeta.glob(f"escena_{a.escena:02d}.*"):
            viejo.unlink()
        shutil.copy(src, destino)
        previo = por_num.get(a.escena, {})
        esc = guion["escenas"][i]
        frame = carpeta / f"frame_{a.escena:02d}.jpg"
        extraer_frame(destino, tipo, frame, 0.5)
        por_num[a.escena] = {
            "escena": a.escena, "tipo": tipo, "archivo": str(destino.relative_to(tirada)),
            "frame": str(frame.relative_to(tirada)), "narracion": esc["narracion"], "visual": esc["visual"],
            "busqueda": None, "prompt": esc.get("prompt_imagen"), "duracion_necesaria": voz["escenas"][i]["duracion"],
            "intentos": previo.get("intentos", 0) + 1, "revisado": False, "encaja": None,
            "movimiento": previo.get("movimiento") or esc.get("movimiento"),
            "efecto": previo.get("efecto") or esc.get("efecto"), "recorte": previo.get("recorte") or esc.get("recorte"),
            "fuente": a.fuente, "importado_de": src.name,
        }
    if a.escena and (a.recorte or a.movimiento or a.efecto):
        e = por_num.get(a.escena)
        if not e:
            parar(f"La escena {a.escena} aún no tiene material")
        if a.recorte:
            e["recorte"] = [float(x) for x in a.recorte.split(",")]
        if a.movimiento:
            e["movimiento"] = a.movimiento
        if a.efecto:
            e["efecto"] = [x.strip() for x in a.efecto.split(",") if x.strip()]
        if e.get("recorte"):   # el fotograma de revisión muestra el encuadre elegido
            cx, cy, z = e["recorte"]
            src = Image.open(tirada / e["archivo"]) if e["tipo"] == "imagen" else Image.open(tirada / e["frame"])
            W0, H0 = src.size
            bw, bh = (H0 * 9 / 16, H0) if W0 / H0 > 9 / 16 else (W0, W0 * 16 / 9)
            w, h = bw / z, bh / z
            x0 = min(max(cx * W0 - w / 2, 0), W0 - w)
            y0 = min(max(cy * H0 - h / 2, 0), H0 - h)
            src.convert("RGB").crop((int(x0), int(y0), int(x0 + w), int(y0 + h))).resize((540, 960)).save(tirada / e["frame"])
    if a.importar or a.recorte or a.movimiento or a.efecto:
        datos = {"proveedor": datos.get("proveedor", "mixto"), "actualizado": ahora_iso(),
                 "escenas": [por_num[k] for k in sorted(por_num)]}
        escribir_json(salida, datos)
        e = por_num[a.escena]
        print(f"  escena {a.escena}: {e['tipo']} · {e.get('fuente')} · recorte={e.get('recorte')} · "
              f"mov={e.get('movimiento')} · efecto={e.get('efecto')} → {e['frame']}")
        return

    proveedor = a.proveedor or cfg["visual"]["proveedor"]
    if proveedor in ("openai", "cloudflare"):      # forzar un generador concreto
        cfg["visual"]["ia"] = proveedor
        proveedor = "ia"
    excluir = clips_usados_recientes(cfg, enc["tirada"])
    excluir |= {e.get("pexels_id") for n, e in por_num.items() if n != a.escena}
    indices = [a.escena - 1] if a.escena else range(len(guion["escenas"]))
    for i in indices:
        if not 0 <= i < len(guion["escenas"]):
            parar(f"La escena {i + 1} no existe")
        esc = guion["escenas"][i]
        necesaria = voz["escenas"][i]["duracion"]
        res = hacer_escena(i, esc, necesaria, cfg, enc, tirada, carpeta, excluir, proveedor,
                           a.busqueda if a.escena else None, a.prompt if a.escena else None, por_num.get(i + 1),
                           guion.get("estilo_visual", ""))
        por_num[i + 1] = res
        if res.get("pexels_id"):
            excluir.add(res["pexels_id"])
        print(f"  escena {i + 1}: {res['tipo']:<6} {res['fuente']:<10} {res.get('busqueda') or (res.get('prompt') or '')[:50]!s:<50} → {res['frame']}")
    datos = {"proveedor": proveedor, "actualizado": ahora_iso(),
             "escenas": [por_num[k] for k in sorted(por_num)]}
    escribir_json(salida, datos)
    registrar_clips(enc["tirada"], [e.get("pexels_id") for e in datos["escenas"]])
    print(f"\n→ Mira cada frame (Read) y aprueba con: python scripts/escenas.py {tirada} --aprobar 1,2,...")


if __name__ == "__main__":
    main()
