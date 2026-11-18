"""Paso 6 · Diseñador de miniaturas.

Uso:
  python scripts/miniaturas.py runs/X --render      # lee 06_conceptos.json -> 10 JPG + hoja + métricas
  python scripts/miniaturas.py runs/X --puntuar 06_puntuaciones.json   # nota final y ganadora

06_conceptos.json (lo escribe el agente):
{
  "titulo_previsto": "…",
  "conceptos": [
    {"id": 1, "nombre": "…", "texto": "TU CEREBRO MIENTE", "palabra_destacada": "MIENTE",
     "fondo": {"tipo": "escena|color|degradado", "escena": 3, "color": "#101010", "color2": "#3a0ca3",
               "oscurecer": 0.3, "desenfoque": 0, "zoom": 1.0},
     "texto_color": "#FFFFFF", "destacado_color": "#FFE600", "caja": null,
     "posicion": "arriba|centro|abajo", "tamano": 1.0, "inclinacion": 0,
     "flecha": {"de": [0.2, 0.75], "a": [0.5, 0.55], "color": "#FF2D2D"} | null,
     "circulo": {"centro": [0.5, 0.55], "radio": 0.15, "color": "#FF2D2D"} | null,
     "borde": "#FFE600" | null}
  ]
}
Coordenadas normalizadas 0-1 sobre 1080x1920.
"""
import argparse
import math
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from comun import (RAIZ, SALIDAS, ahora_iso, cargar_config, ejecutar, escribir_json, leer_json, parar,
                   requiere, tirada_desde_arg)

FUENTE = RAIZ / "assets" / "fonts" / "Anton-Regular.ttf"
W, H = 1080, 1920


def rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def luminancia(c) -> float:
    def ch(v):
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = c[:3]
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def wcag(a, b) -> float:
    la, lb = sorted([luminancia(a), luminancia(b)], reverse=True)
    return round((la + 0.05) / (lb + 0.05), 2)


def colorido(img: Image.Image) -> float:
    """Métrica de Hasan & Süsstrunk (0 = gris, >80 = muy colorido)."""
    a = np.asarray(img.convert("RGB").resize((270, 480)), dtype=float)
    rg = a[..., 0] - a[..., 1]
    yb = 0.5 * (a[..., 0] + a[..., 1]) - a[..., 2]
    return round(float(math.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * math.sqrt(rg.mean() ** 2 + yb.mean() ** 2)), 1)


# ------------------------------------------------------------------ fondos
def fondo_escena(tirada: Path, n: int, cache: Path) -> Image.Image:
    esc = {e["escena"]: e for e in leer_json(tirada / SALIDAS[4])["escenas"]}
    if n not in esc:
        parar(f"El concepto usa la escena {n}, que no existe")
    e = esc[n]
    destino = cache / f"escena_{n:02d}.jpg"
    if not destino.exists():
        src = tirada / e["archivo"]
        t = ["-ss", f"{min(e.get('duracion_clip') or 1, e['duracion_necesaria']) / 2:.2f}"] if e["tipo"] == "video" else []
        if e.get("recorte") and e["tipo"] == "imagen":   # mismo encuadre que el plano del vídeo
            im = Image.open(src).convert("RGB")
            cx, cy, z = (float(x) for x in e["recorte"])
            W0, H0 = im.size
            bw, bh = (H0 * W / H, H0) if W0 / H0 > W / H else (W0, W0 * H / W)
            w, h = bw / z, bh / z
            x0 = min(max(cx * W0 - w / 2, 0), W0 - w)
            y0 = min(max(cy * H0 - h / 2, 0), H0 - h)
            im.crop((int(x0), int(y0), int(x0 + w), int(y0 + h))).resize((W, H), Image.LANCZOS).save(destino, quality=95)
        else:
            ejecutar(["ffmpeg", "-y", *t, "-i", str(src), "-frames:v", "1", "-vf",
                      f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}", "-q:v", "2", str(destino)])
    return Image.open(destino).convert("RGB")


def construir_fondo(c: dict, tirada: Path, cache: Path) -> Image.Image:
    f = c.get("fondo") or {"tipo": "color", "color": "#111111"}
    tipo = f.get("tipo", "color")
    if tipo == "escena":
        img = fondo_escena(tirada, int(f.get("escena", 1)), cache)
        z = float(f.get("zoom", 1.0))
        if z > 1.0:
            cw, ch = int(W / z), int(H / z)
            cx, cy = f.get("centro_zoom", [0.5, 0.5])
            x0 = int(min(max(cx * W - cw / 2, 0), W - cw))
            y0 = int(min(max(cy * H - ch / 2, 0), H - ch))
            img = img.crop((x0, y0, x0 + cw, y0 + ch)).resize((W, H), Image.LANCZOS)
    elif tipo == "degradado":
        a, b = np.array(rgb(f.get("color", "#000000")), float), np.array(rgb(f.get("color2", "#333333")), float)
        k = np.linspace(0, 1, H)[:, None, None]
        img = Image.fromarray(np.broadcast_to(a * (1 - k) + b * k, (H, W, 3)).astype("uint8"))
    else:
        img = Image.new("RGB", (W, H), rgb(f.get("color", "#111111")))
    if f.get("desenfoque"):
        img = img.filter(ImageFilter.GaussianBlur(float(f["desenfoque"])))
    if f.get("oscurecer"):
        img = Image.blend(img, Image.new("RGB", (W, H), (0, 0, 0)), float(f["oscurecer"]))
    return img


# ------------------------------------------------------------------ texto y adornos
def opciones_lineas(texto: str) -> list[list[str]]:
    pal = texto.split()
    ops = [[" ".join(pal)]]
    for k in range(1, len(pal)):
        ops.append([" ".join(pal[:k]), " ".join(pal[k:])])
    return ops


def ajustar(lineas: list[str], factor: float) -> int:
    """Mayor tamaño de letra con el que caben las líneas."""
    tam = int(330 * factor)
    while tam > 60:
        f = ImageFont.truetype(str(FUENTE), tam)
        if max(f.getlength(l) for l in lineas) <= W * 0.88 and tam * 1.08 * len(lineas) <= H * 0.45:
            return tam
        tam -= 6
    return tam


def dibujar_texto(img: Image.Image, c: dict) -> tuple[tuple, int]:
    texto = c["texto"].upper().strip()
    destacada = (c.get("palabra_destacada") or "").upper().strip()
    col = rgb(c.get("texto_color", "#FFFFFF"))
    col_d = rgb(c.get("destacado_color", "#FFE600"))
    factor = float(c.get("tamano", 1.0))
    # elige el reparto en líneas que permite la letra más grande (empate: más equilibrado)
    lineas, tam = max(((ls, ajustar(ls, factor)) for ls in opciones_lineas(texto)),
                      key=lambda x: (x[1], -abs(len(x[0][0]) - len(x[0][-1]))))
    f = ImageFont.truetype(str(FUENTE), tam)
    alto_linea = int(tam * 1.08)
    bloque_h = alto_linea * len(lineas)
    pos = c.get("posicion", "arriba")
    y0 = {"arriba": int(H * 0.10), "centro": (H - bloque_h) // 2, "abajo": int(H * 0.86) - bloque_h}.get(pos, int(H * 0.10))
    capa = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    borde = max(6, tam // 18)
    x_min, x_max = W, 0
    filas = []
    for i, l in enumerate(lineas):
        lw = f.getlength(l)
        x, y = (W - lw) / 2, y0 + i * alto_linea
        x_min, x_max = min(x_min, x), max(x_max, x + lw)
        filas.append((l, x, y, lw))
    if c.get("caja"):  # primero todas las cajas, luego el texto (que una caja no tape otra línea)
        for l, x, y, lw in filas:
            d.rectangle([x - 30, y - 10, x + lw + 30, y + alto_linea + 4], fill=rgb(c["caja"]) + (235,))
    for l, x, y, lw in filas:
        cx = x
        for w in l.split(" "):
            color = col_d if (destacada and w.strip("!?¿¡.,") in destacada.split()) else col
            d.text((cx, y), w, font=f, fill=color, stroke_width=borde, stroke_fill=(0, 0, 0))
            cx += f.getlength(w + " ")
    ang = float(c.get("inclinacion", 0))
    if ang:
        capa = capa.rotate(ang, resample=Image.BICUBIC, center=(W / 2, y0 + bloque_h / 2))
    caja = (int(max(x_min - 30, 0)), int(y0), int(min(x_max + 30, W)), int(y0 + bloque_h))
    img.paste(capa, (0, 0), capa)
    return caja, tam


def dibujar_adornos(img: Image.Image, c: dict) -> None:
    d = ImageDraw.Draw(img)
    if c.get("circulo"):
        ci = c["circulo"]
        cx, cy, r = ci["centro"][0] * W, ci["centro"][1] * H, ci.get("radio", 0.15) * W
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(0, 0, 0), width=26)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=rgb(ci.get("color", "#FF2D2D")), width=16)
    if c.get("flecha"):
        fl = c["flecha"]
        (x1, y1), (x2, y2) = [(p[0] * W, p[1] * H) for p in (fl["de"], fl["a"])]
        col = rgb(fl.get("color", "#FF2D2D"))
        ang = math.atan2(y2 - y1, x2 - x1)
        L = 120
        punta = [(x2, y2), (x2 - L * math.cos(ang - 0.45), y2 - L * math.sin(ang - 0.45)),
                 (x2 - L * math.cos(ang + 0.45), y2 - L * math.sin(ang + 0.45))]
        xb, yb = x2 - 0.8 * L * math.cos(ang), y2 - 0.8 * L * math.sin(ang)
        d.line([(x1, y1), (xb, yb)], fill=(0, 0, 0), width=48)
        d.polygon(punta, fill=(0, 0, 0), outline=(0, 0, 0), width=12)
        d.line([(x1, y1), (xb, yb)], fill=col, width=30)
        d.polygon(punta, fill=col)
    if c.get("borde"):
        d.rectangle([0, 0, W - 1, H - 1], outline=rgb(c["borde"]), width=28)


def guardar_jpg(img: Image.Image, destino: Path, max_mb: float) -> float:
    for q in (92, 88, 84, 80, 75, 70, 60):
        img.save(destino, "JPEG", quality=q, optimize=True, progressive=True)
        mb = destino.stat().st_size / 1e6
        if mb < max_mb:
            return round(mb, 3)
    return round(mb, 3)


def render(tirada: Path, cfg: dict) -> None:
    requiere(tirada, SALIDAS[2], SALIDAS[4], "06_conceptos.json")
    m = cfg["miniaturas"]
    conceptos = leer_json(tirada / "06_conceptos.json")["conceptos"]
    if len(conceptos) != m["cantidad"]:
        parar(f"06_conceptos.json tiene {len(conceptos)} conceptos; deben ser {m['cantidad']}")
    carpeta = tirada / "06_miniaturas"
    carpeta.mkdir(exist_ok=True)
    cache = carpeta / "_fondos"
    cache.mkdir(exist_ok=True)
    metricas, errores = [], []
    firmas = set()
    for c in conceptos:
        n_pal = len(c["texto"].split())
        if n_pal > m["max_palabras"]:
            errores.append(f"concepto {c['id']}: {n_pal} palabras (máx {m['max_palabras']})")
        firma = (c["texto"].upper(), (c.get("fondo") or {}).get("tipo"), (c.get("fondo") or {}).get("escena"),
                 c.get("posicion"), c.get("texto_color"), bool(c.get("flecha")))
        if firma in firmas:
            errores.append(f"concepto {c['id']}: es igual que otro concepto, haz uno distinto de verdad")
        firmas.add(firma)
        img = construir_fondo(c, tirada, cache)
        fondo_np = np.asarray(img)
        caja, tam = dibujar_texto(img, c)
        dibujar_adornos(img, c)
        x0, y0, x1, y1 = caja
        zona = fondo_np[max(y0, 0):min(y1, H), max(x0, 0):min(x1, W)].reshape(-1, 3)
        bg_medio = tuple(int(v) for v in (zona.mean(axis=0) if len(zona) else (0, 0, 0)))
        col_t = rgb(c.get("texto_color", "#FFFFFF"))
        destino = carpeta / f"miniatura_{c['id']:02d}.jpg"
        mb = guardar_jpg(img, destino, m["max_mb"])
        escala = m["tamano_movil"][1] / H
        metricas.append({
            "id": c["id"], "archivo": str(destino.relative_to(tirada)), "texto": c["texto"],
            "palabras": n_pal, "peso_mb": mb,
            "contraste_texto_fondo": wcag(col_t, bg_medio),
            "contraste_texto_borde": wcag(col_t, (0, 0, 0)) if not c.get("caja") else wcag(col_t, rgb(c["caja"])),
            "colorido": colorido(img),
            "altura_letra_movil_px": round(tam * escala, 1),
            "texto_ocupa_pct": round(100 * (x1 - x0) * (y1 - y0) / (W * H), 1),
        })
    if errores:
        parar("Conceptos no válidos:\n - " + "\n - ".join(errores))
    # hoja de contacto al tamaño en que se ve en el móvil
    tw, th = m["tamano_movil"]
    pad = 24
    hoja = Image.new("RGB", (5 * (tw + pad) + pad, 2 * (th + pad + 28) + pad), (15, 15, 15))
    dr = ImageDraw.Draw(hoja)
    fnum = ImageFont.truetype(str(FUENTE), 22)
    for k, c in enumerate(conceptos):
        im = Image.open(carpeta / f"miniatura_{c['id']:02d}.jpg").resize((tw, th), Image.LANCZOS)
        x = pad + (k % 5) * (tw + pad)
        y = pad + (k // 5) * (th + pad + 28)
        dr.text((x, y), f"#{c['id']}", font=fnum, fill=(255, 255, 255))
        hoja.paste(im, (x, y + 28))
    hoja.save(carpeta / "hoja_contacto.jpg", quality=90)
    escribir_json(carpeta / "metricas.json", {"fecha": ahora_iso(), "metricas": metricas})
    print(f"{'id':>3} {'MB':>5} {'contr.fondo':>11} {'contr.borde':>11} {'color':>6} {'letra móvil':>11}  texto")
    for x in metricas:
        print(f"{x['id']:>3} {x['peso_mb']:>5} {x['contraste_texto_fondo']:>11} {x['contraste_texto_borde']:>11} "
              f"{x['colorido']:>6} {x['altura_letra_movil_px']:>9}px  {x['texto']}")
    print(f"\n→ Mira {carpeta / 'hoja_contacto.jpg'} (tamaño móvil) y puntúa con --puntuar")


CRITERIOS = ["se_lee_pequeno", "contraste", "un_punto_atencion", "hueco_curiosidad", "coherencia_titulo"]


def nota_automatica(x: dict) -> float:
    # el contorno negro ayuda, pero lo que más cuenta es el contraste texto/fondo (7:1 = WCAG AAA)
    c = 0.3 + 0.7 * min(x["contraste_texto_fondo"] / 7, 1)
    col = min(x["colorido"] / 70, 1)
    letra = min(x["altura_letra_movil_px"] / 45, 1)
    return round(10 * (0.45 * c + 0.25 * col + 0.30 * letra), 2)


def puntuar(tirada: Path, archivo: str) -> None:
    carpeta = tirada / "06_miniaturas"
    requiere(tirada, "06_miniaturas/metricas.json")
    met = {x["id"]: x for x in leer_json(carpeta / "metricas.json")["metricas"]}
    p = Path(archivo)
    if not p.is_absolute():
        p = tirada / p
    pun = leer_json(p)
    filas = []
    for s in pun["puntuaciones"]:
        faltan = [k for k in CRITERIOS if k not in s]
        if faltan:
            parar(f"miniatura {s.get('id')}: faltan criterios {faltan}")
        if s["id"] not in met:
            parar(f"miniatura {s['id']} no existe")
        media = sum(float(s[k]) for k in CRITERIOS) / len(CRITERIOS)
        auto = nota_automatica(met[s["id"]])
        filas.append({**met[s["id"]], "notas": {k: s[k] for k in CRITERIOS}, "comentario": s.get("comentario", ""),
                      "nota_agente": round(media, 2), "nota_automatica": auto,
                      "nota_final": round(0.8 * media + 0.2 * auto, 2)})
    if len(filas) != len(met):
        parar(f"Hay {len(met)} miniaturas y solo {len(filas)} puntuaciones")
    filas.sort(key=lambda f: f["nota_final"], reverse=True)
    gan = filas[0]
    shutil.copy(tirada / gan["archivo"], carpeta / "ganadora.jpg")
    escribir_json(tirada / SALIDAS[6], {
        "fecha": ahora_iso(), "titulo_previsto": pun.get("titulo") or pun.get("titulo_previsto"),
        "ganadora": {"id": gan["id"], "archivo": "06_miniaturas/ganadora.jpg", "texto": gan["texto"],
                     "nota_final": gan["nota_final"], "motivo": pun.get("motivo_ganadora", gan["comentario"])},
        "ranking": filas,
    })
    print("Ranking:")
    for f in filas:
        print(f"  #{f['id']:<2} final {f['nota_final']:<5} (agente {f['nota_agente']}, auto {f['nota_automatica']})  {f['texto']}")
    print(f"\n🏆 Ganadora: #{gan['id']} «{gan['texto']}» → 06_miniaturas/ganadora.jpg")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tirada")
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--puntuar")
    a = ap.parse_args()
    tirada = tirada_desde_arg(a.tirada)
    cfg = cargar_config()
    if a.render:
        render(tirada, cfg)
    elif a.puntuar:
        puntuar(tirada, a.puntuar)
    else:
        parar("Usa --render o --puntuar")


if __name__ == "__main__":
    main()
