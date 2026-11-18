"""Paso 5 · Montador: monta 05_final.mp4.

Uso: python scripts/montaje.py runs/X [--solo-capturas] [--rapido]

Motor propio fotograma a fotograma (PIL + numpy -> ffmpeg), pensado para el ritmo de los
Shorts de curiosidades en 3D:
- Cada escena = un plano, cortado exactamente cuando la voz empieza su frase.
- Movimiento de cámara con curva suave por plano (push_in, pull_out, pan_left, pan_right,
  tilt_up, tilt_down, drift) sobre el recorte/foco que eligió el director.
- "Punch" de zoom en cada corte, temblor (shake), destello blanco (flash), pulso rojo (alarma),
  viñeta y barra de progreso arriba.
- Tarjeta del gancho (la pregunta) los primeros segundos, subtítulos karaoke palabra a palabra con
  rebote, cuenta atrás 3-2-1 para el formato quiz.
- Pista de efectos (whoosh en cortes, boom en golpes, pop en el gancho, tic-tac en cuenta atrás)
  + música con ducking bajo la voz.
- Control de calidad: capturas, hoja, zonas de interfaz, detección de negros, 05_montaje.json.
"""
import argparse
import math
import random
import re
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from comun import (RAIZ, SALIDAS, ahora_iso, cargar_config, duracion_media, ejecutar, escribir_json,
                   historial, info_video, leer_json, parar, requiere, tirada_desde_arg)

FUENTES_DIR = RAIZ / "assets" / "fonts"
SFX_DIR = RAIZ / "assets" / "sfx"
PUNTUACION_CORTE = tuple(".,!?;:…")
MOVIMIENTOS = ["push_in", "pan_right", "pull_out", "tilt_up", "push_in", "pan_left", "drift", "tilt_down"]


def hex_a_ass(h: str, alfa: str = "00") -> str:
    h = h.lstrip("#")
    return f"&H{alfa}{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def ease(t: float) -> float:          # ease-in-out seno
    t = min(max(t, 0.0), 1.0)
    return 0.5 - 0.5 * math.cos(math.pi * t)


def ease_out(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return 1 - (1 - t) ** 3


# ================================================================== PLANOS
class Plano:
    def __init__(self, esc: dict, gui: dict, archivo: Path, t0: float, t1: float, idx: int, cfg: dict):
        v = cfg["video"]
        self.W, self.H, self.fps = v["ancho"], v["alto"], v["fps"]
        self.t0, self.t1 = t0, t1
        self.tipo = esc["tipo"]
        self.mov = esc.get("movimiento") or gui.get("movimiento") or MOVIMIENTOS[idx % len(MOVIMIENTOS)]
        ef = esc.get("efecto") or gui.get("efecto") or []
        self.efectos = [ef] if isinstance(ef, str) else list(ef)
        self.efectos = [e for e in self.efectos if e and e != "ninguno"]
        rec = esc.get("recorte") or gui.get("recorte") or [0.5, 0.5, 1.0]   # [cx, cy, zoom]
        self.cx, self.cy, self.z0 = float(rec[0]), float(rec[1]), max(1.0, float(rec[2]))
        self.intensidad = float(v.get("intensidad_movimiento", 1.0))
        self.punch = idx > 0 or "punch" in self.efectos
        self.archivo = archivo
        self.img = None
        self.video_frames = None
        random.seed(idx * 7919)
        self.fase = random.random() * 10

    def cargar(self):
        if self.tipo == "imagen":
            im = Image.open(self.archivo).convert("RGB")
            # trabajar a una resolución que cubra 1080x1920 con margen para el zoom
            esc = max(self.W * 1.6 / im.width, self.H * 1.6 / im.height, 1.0)
            if esc > 1.0:
                im = im.resize((int(im.width * esc), int(im.height * esc)), Image.LANCZOS)
            self.img = im
        else:
            n = max(1, round((self.t1 - self.t0) * self.fps)) + 2
            vf = (f"scale={int(self.W * 1.15)}:{int(self.H * 1.15)}:force_original_aspect_ratio=increase,"
                  f"crop={int(self.W * 1.15)}:{int(self.H * 1.15)},fps={self.fps}")
            p = subprocess.run(["ffmpeg", "-v", "error", "-stream_loop", "-1", "-i", str(self.archivo), "-vf", vf,
                                "-frames:v", str(n), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                               capture_output=True, check=True)
            w, h = int(self.W * 1.15), int(self.H * 1.15)
            self.video_frames = np.frombuffer(p.stdout, np.uint8).reshape(-1, h, w, 3)

    def liberar(self):
        self.img = None
        self.video_frames = None

    def _rect(self, t: float, src_w: int, src_h: int) -> tuple:
        """Rectángulo de la fuente que se ve en el instante t (0..1 del plano)."""
        aspect = self.W / self.H
        # rectángulo "cover" base
        if src_w / src_h > aspect:
            bh, bw = src_h, src_h * aspect
        else:
            bw, bh = src_w, src_w / aspect
        e = ease(t)
        k = 0.16 * self.intensidad
        z, cx, cy = self.z0, self.cx, self.cy
        if self.mov == "push_in":
            z *= 1 + k * e
        elif self.mov == "pull_out":
            z *= 1 + k * (1 - e)
        elif self.mov in ("pan_left", "pan_right"):
            z *= 1 + 0.6 * k
            d = 0.07 * self.intensidad * (e - 0.5)
            cx += d if self.mov == "pan_right" else -d
        elif self.mov in ("tilt_up", "tilt_down"):
            z *= 1 + 0.6 * k
            d = 0.05 * self.intensidad * (e - 0.5)
            cy += -d if self.mov == "tilt_up" else d
        else:  # drift
            z *= 1 + 0.5 * k * e
            cx += 0.015 * math.sin(2 * math.pi * (t * 0.5) + self.fase)
        # punch al entrar en el plano
        dur = max(self.t1 - self.t0, 0.01)
        tp = t * dur
        if self.punch and tp < 0.22:
            z *= 1 + 0.10 * (1 - ease_out(tp / 0.22))
        w, h = bw / z, bh / z
        x0 = min(max(cx * src_w - w / 2, 0), src_w - w)
        y0 = min(max(cy * src_h - h / 2, 0), src_h - h)
        return x0, y0, x0 + w, y0 + h

    def fotograma(self, tg: float) -> np.ndarray:
        dur = max(self.t1 - self.t0, 0.01)
        t = (tg - self.t0) / dur
        if self.tipo == "imagen":
            r = self._rect(t, self.img.width, self.img.height)
            fr = self.img.transform((self.W, self.H), Image.EXTENT, r, Image.BILINEAR)
            arr = np.asarray(fr).copy()
        else:
            i = min(int((tg - self.t0) * self.fps), len(self.video_frames) - 1)
            src = Image.fromarray(self.video_frames[i])
            r = self._rect(t, src.width, src.height)
            arr = np.asarray(src.transform((self.W, self.H), Image.EXTENT, r, Image.BILINEAR)).copy()
        tp = tg - self.t0
        # temblor de cámara
        if any(e in self.efectos for e in ("shake", "boom", "alarma")) and tp < 0.6:
            a = 22 * (1 - tp / 0.6) * self.intensidad
            dx = int(a * math.sin(tp * 71 + self.fase))
            dy = int(a * math.cos(tp * 53 + self.fase))
            arr = np.roll(arr, (dy, dx), axis=(0, 1))
        # destello blanco
        if "flash" in self.efectos and tp < 0.2:
            al = 0.85 * (1 - tp / 0.2)
            arr = (arr * (1 - al) + 255 * al).astype(np.uint8)
        # pulso rojo de alarma
        if "alarma" in self.efectos:
            al = 0.30 + 0.15 * math.sin(2 * math.pi * 2.2 * tp)
            rojo = np.array([255, 20, 20], np.float32)
            arr = (arr * (1 - al) + rojo * al).astype(np.uint8)
        return arr


def mascara_vineta(W: int, H: int, fuerza: float) -> np.ndarray:
    y, x = np.ogrid[0:H, 0:W]
    d = np.sqrt(((x - W / 2) / (W / 2)) ** 2 + ((y - H / 2) / (H / 2)) ** 2) / math.sqrt(2)
    m = 1 - fuerza * np.clip((d - 0.45) / 0.55, 0, 1) ** 1.6
    return m[..., None].astype(np.float32)


def renderizar_video(planos: list[Plano], dur_total: float, cfg: dict, destino: Path) -> None:
    v = cfg["video"]
    W, H, fps = v["ancho"], v["alto"], v["fps"]
    n_frames = round(dur_total * fps)
    vin = mascara_vineta(W, H, float(v.get("vineta", 0.45)))
    barra = cfg["video"].get("barra_progreso", True)
    col_barra = np.array(tuple(int(cfg["subtitulos"]["color_activo"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)), np.uint8)
    proc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                             "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
                             "-pix_fmt", "yuv420p", str(destino)], stdin=subprocess.PIPE)
    k = 0
    actual = None
    for f in range(n_frames):
        tg = f / fps
        while k + 1 < len(planos) and tg >= planos[k + 1].t0:
            k += 1
        p = planos[k]
        if actual is not p:
            if actual:
                actual.liberar()
            p.cargar()
            actual = p
        arr = p.fotograma(tg)
        arr = (arr.astype(np.float32) * vin).astype(np.uint8)
        if barra:
            ancho = int(W * (f + 1) / n_frames)
            arr[0:10, :, :] = (arr[0:10, :, :] * 0.4).astype(np.uint8)
            arr[0:10, :ancho, :] = col_barra
        proc.stdin.write(arr.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg falló al codificar los fotogramas")


# ================================================================== SUBTÍTULOS
def agrupar(palabras: list[dict], max_pal: int, max_chars: int) -> list[list[dict]]:
    grupos, actual = [], []
    for p in palabras:
        largo = sum(len(x["palabra"]) + 1 for x in actual) + len(p["palabra"])
        cambio_escena = actual and actual[-1]["escena"] != p["escena"]
        if actual and (len(actual) >= max_pal or largo > max_chars or cambio_escena):
            grupos.append(actual)
            actual = []
        actual.append(p)
        if p["palabra"].endswith(PUNTUACION_CORTE):
            grupos.append(actual)
            actual = []
    if actual:
        grupos.append(actual)
    return grupos


def ass_tiempo(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def limpiar(txt: str, mayus: bool) -> str:
    txt = re.sub(r"[{}\\]", "", txt)
    return txt.upper() if mayus else txt


def generar_ass(palabras: list[dict], guion: dict, tiempos: list[dict], escenas04: list[dict], cfg: dict,
                destino: Path, duracion_total: float) -> int:
    s = cfg["subtitulos"]
    W, H = cfg["video"]["ancho"], cfg["video"]["alto"]
    blanco, activo = hex_a_ass(s["color"]), hex_a_ass(s["color_activo"])
    g = cfg.get("gancho_pantalla", {})
    cab = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,{s['fuente']},{s['tamano']},{blanco},{blanco},{hex_a_ass(s['color_borde'])},&H90000000,0,0,0,0,100,100,1,0,1,{s['borde']},{s['sombra']},5,60,60,0,1
Style: Gancho,{s['fuente']},{g.get('tamano', 128)},{hex_a_ass(g.get('color_texto', '#000000'))},&H000000FF,{hex_a_ass(g.get('color_caja', '#FFE600'))},&H00000000,0,0,0,0,100,100,1,0,3,22,0,5,60,60,0,1
Style: Cuenta,{s['fuente']},420,{activo},{activo},&H00000000,&H90000000,0,0,0,0,100,100,0,0,1,18,8,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lineas = []
    # ---- tarjeta del gancho: la pregunta, en caja de color, durante la escena 1
    fin_gancho = 0.0
    if g.get("activo", True) and tiempos:
        fin_gancho = tiempos[0]["fin"]
        texto = limpiar(guion.get("texto_gancho") or guion.get("gancho", ""), True)
        palabras_g = texto.split()
        # máx. ~14 caracteres por línea
        filas, fila = [], ""
        for w in palabras_g:
            if fila and len(fila) + 1 + len(w) > int(g.get("caracteres_linea", 16)):
                filas.append(fila)
                fila = w
            else:
                fila = (fila + " " + w).strip()
        if fila:
            filas.append(fila)
        lineas.append(f"Dialogue: 2,{ass_tiempo(0)},{ass_tiempo(fin_gancho)},Gancho,,0,0,0,,"
                      f"{{\\an5\\pos({W // 2},{g.get('posicion_y', 520)})\\fscx20\\fscy20\\t(0,160,\\fscx108\\fscy108)"
                      f"\\t(160,260,\\fscx100\\fscy100)}}" + "\\N".join(filas))
    # ---- cuenta atrás (formato quiz)
    for e, t in zip(escenas04, tiempos):
        efs = e.get("efecto") or []
        efs = [efs] if isinstance(efs, str) else efs
        if "cuenta_atras" in efs:
            d = t["duracion"] / 3
            for k, num in enumerate(("3", "2", "1")):
                a, b = t["inicio"] + k * d, t["inicio"] + (k + 1) * d
                lineas.append(f"Dialogue: 3,{ass_tiempo(a)},{ass_tiempo(b)},Cuenta,,0,0,0,,"
                              f"{{\\an5\\pos({W // 2},{int(H * 0.40)})\\fscx160\\fscy160\\t(0,180,\\fscx100\\fscy100)\\fad(0,120)}}{num}")
    # ---- subtítulos karaoke (sin la escena del gancho si la tarjeta está activa)
    pal = [p for p in palabras if not (fin_gancho and p["escena"] == 1)]
    grupos = agrupar(pal, s["palabras_por_linea"], s["max_caracteres_linea"])
    for gi, gr in enumerate(grupos):
        sig_ini = grupos[gi + 1][0]["inicio"] if gi + 1 < len(grupos) else duracion_total
        fin_grupo = sig_ini if sig_ini - gr[-1]["fin"] < 0.7 else gr[-1]["fin"] + 0.25
        textos = [limpiar(p["palabra"], s["mayusculas"]) for p in gr]
        chars = sum(len(t) + 1 for t in textos)
        fs = s["tamano"] if chars <= s["max_caracteres_linea"] + 1 else int(s["tamano"] * (s["max_caracteres_linea"] + 1) / chars)
        for wi, p in enumerate(gr):
            ini = p["inicio"]
            fin = gr[wi + 1]["inicio"] if wi + 1 < len(gr) else fin_grupo
            if fin <= ini:
                fin = ini + 0.05
            partes = []
            for k, t in enumerate(textos):
                if k == wi:   # palabra que suena: amarilla y con rebote
                    partes.append(f"{{\\c{activo}\\fscx118\\fscy118\\t(0,90,\\fscx100\\fscy100)}}{t}{{\\c{blanco}\\fscx100\\fscy100}}")
                else:
                    partes.append(t)
            pop = "\\fscx80\\fscy80\\t(0,70,\\fscx100\\fscy100)" if wi == 0 else ""
            lineas.append(f"Dialogue: 1,{ass_tiempo(ini)},{ass_tiempo(fin)},Karaoke,,0,0,0,,"
                          f"{{\\an5\\pos({W // 2},{s['posicion_y']})\\fs{fs}{pop}}}" + " ".join(partes))
    destino.write_text(cab + "\n".join(lineas) + "\n", encoding="utf-8")
    return len(grupos)


# ================================================================== AUDIO
def leer_wav_mono(path: Path, sr: int = 44100) -> np.ndarray:
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
                       capture_output=True, check=True)
    return np.frombuffer(p.stdout, np.int16).astype(np.float32) / 32768


def pista_sfx(escenas04: list[dict], tiempos: list[dict], dur: float, cfg: dict, destino: Path) -> list[dict]:
    sr = 44100
    pista = np.zeros(int(sr * (dur + 1)), np.float32)
    sx = cfg.get("efectos_sonido", {})
    if not sx.get("activo", True):
        return []
    cache, eventos = {}, []

    def poner(nombre, t, vol):
        f = SFX_DIR / nombre
        if not f.exists():
            return
        if nombre not in cache:
            cache[nombre] = leer_wav_mono(f)
        s = cache[nombre] * vol
        i = int(t * sr)
        j = min(len(pista), i + len(s))
        if i < len(pista):
            pista[i:j] += s[: j - i]
            eventos.append({"sfx": nombre, "t": round(t, 2)})

    vol = float(sx.get("volumen", 0.5))
    poner("pop.wav", 0.0, vol * 0.8)
    for e, t in zip(escenas04, tiempos):
        efs = e.get("efecto") or []
        efs = [efs] if isinstance(efs, str) else efs
        if t["inicio"] > 0.05:
            poner("whoosh.wav", max(0, t["inicio"] - 0.12), vol * 0.55)
        if any(x in efs for x in ("boom", "flash", "alarma")):
            poner("boom.wav", t["inicio"], vol * 0.9)
        if "riser" in efs:
            poner("riser.wav", max(0, t["fin"] - 1.0), vol * 0.6)
        if "cuenta_atras" in efs:
            d = t["duracion"] / 3
            for k in range(3):
                poner("tick.wav", t["inicio"] + k * d, vol)
            poner("ding.wav", t["fin"] - 0.05, vol * 0.8)
    pista = np.clip(pista, -1, 1)
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((pista * 32000).astype(np.int16).tobytes())
    return eventos


def elegir_musica(cfg) -> Path | None:
    carpeta = RAIZ / cfg["musica"]["carpeta"]
    pistas = sorted(p for p in carpeta.glob("*") if p.suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg"))
    if not pistas:
        return None
    usadas = [h.get("musica") for h in historial()[-3:]]
    libres = [p for p in pistas if p.name not in usadas] or pistas
    return random.Random().choice(libres)


# ================================================================== CONTROL DE CALIDAD
def capturas(final: Path, tiempos: list[dict], carpeta: Path) -> list[str]:
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir()
    puntos = [("inicio", 0.5)]
    for t in tiempos:
        puntos.append((f"escena{t['escena']:02d}", t["inicio"] + t["duracion"] * 0.6))
    puntos.append(("final", tiempos[-1]["fin"] - 0.15))
    rutas = []
    for nombre, t in puntos:
        p = carpeta / f"{nombre}.jpg"
        ejecutar(["ffmpeg", "-y", "-ss", f"{max(t, 0):.2f}", "-i", str(final), "-frames:v", "1",
                  "-vf", "scale=540:960", "-q:v", "3", str(p)])
        rutas.append(p)
    cols = 4
    filas = (len(rutas) + cols - 1) // cols
    tw, th = 270, 480
    hoja = Image.new("RGB", (cols * tw, filas * (th + 30)), (30, 30, 30))
    dr = ImageDraw.Draw(hoja)
    for k, p in enumerate(rutas):
        im = Image.open(p).resize((tw, th))
        x, y = (k % cols) * tw, (k // cols) * (th + 30)
        hoja.paste(im, (x, y + 30))
        dr.text((x + 8, y + 6), p.stem, fill=(255, 255, 0))
    hoja.save(carpeta / "hoja.jpg", quality=85)
    base = Image.open(rutas[min(2, len(rutas) - 1)]).convert("RGBA")
    capa = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d2 = ImageDraw.Draw(capa)
    w, h = base.size
    d2.rectangle([0, int(h * 0.78), w, h], fill=(255, 0, 0, 90))
    d2.rectangle([int(w * 0.86), int(h * 0.42), w, int(h * 0.78)], fill=(255, 0, 0, 90))
    d2.rectangle([0, 0, w, int(h * 0.07)], fill=(255, 0, 0, 60))
    Image.alpha_composite(base, capa).convert("RGB").save(carpeta / "zonas_ui.jpg", quality=85)
    return [str(p.relative_to(carpeta.parent)) for p in rutas] + ["05_capturas/hoja.jpg", "05_capturas/zonas_ui.jpg"]


def detectar_negros(final: Path) -> list[dict]:
    r = ejecutar(["ffmpeg", "-hide_banner", "-i", str(final), "-vf", "blackdetect=d=0.08:pix_th=0.06",
                  "-an", "-f", "null", "-"])
    return [{"inicio": float(m.group(1)), "fin": float(m.group(2)), "duracion": float(m.group(3))}
            for m in re.finditer(r"black_start:([\d.]+) black_end:([\d.]+) black_duration:([\d.]+)", r.stderr)]


# ================================================================== MAIN
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tirada")
    ap.add_argument("--solo-capturas", action="store_true")
    a = ap.parse_args()
    tirada = tirada_desde_arg(a.tirada)
    requiere(tirada, SALIDAS[2], SALIDAS[3], "03_voz.mp3", SALIDAS[4])
    cfg = cargar_config()
    voz = leer_json(tirada / SALIDAS[3])
    esc_json = leer_json(tirada / SALIDAS[4])
    guion = leer_json(tirada / SALIDAS[2])
    escenas04 = esc_json["escenas"]
    if len(escenas04) != len(guion["escenas"]):
        parar("04_escenas.json no tiene todas las escenas del guion")
    no_ok = [e["escena"] for e in escenas04 if not e.get("revisado")]
    if no_ok:
        print(f"⚠️  Escenas sin revisar por el director: {no_ok}")
    for e in escenas04:
        if not (tirada / e["archivo"]).exists():
            parar(f"Falta el archivo de la escena {e['escena']}: {e['archivo']}")

    tiempos = voz["escenas"]
    final = tirada / SALIDAS[5]
    trabajo = tirada / "05_trabajo"
    musica, n_lineas, eventos = None, None, []
    if not a.solo_capturas:
        trabajo.mkdir(exist_ok=True)
        dur = tiempos[-1]["fin"]
        planos = [Plano(e, g, tirada / e["archivo"], t["inicio"], t["fin"], i, cfg)
                  for i, (e, g, t) in enumerate(zip(escenas04, guion["escenas"], tiempos))]
        for p in planos:
            print(f"  plano {planos.index(p) + 1:>2}: {p.tipo:<6} {p.mov:<9} {','.join(p.efectos) or '-':<14} "
                  f"{p.t0:6.2f}→{p.t1:6.2f}s")
        mudo = trabajo / "video_mudo.mp4"
        renderizar_video(planos, dur, cfg, mudo)

        ass = tirada / "05_subtitulos.ass"
        n_lineas = generar_ass(voz["palabras"], guion, tiempos, escenas04, cfg, ass, dur)
        sfx = trabajo / "sfx.wav"
        eventos = pista_sfx(escenas04, tiempos, dur, cfg, sfx)
        musica = elegir_musica(cfg)
        vol = cfg["musica"]["volumen"]
        ass_esc = str(ass).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
        fdir = str(FUENTES_DIR).replace(":", "\\:")
        grade = cfg["video"].get("grado_color", "eq=contrast=1.06:saturation=1.18,unsharp=5:5:0.6")
        entradas = ["-i", str(mudo), "-i", str(tirada / "03_voz.mp3"), "-i", str(sfx)]
        fc = (f"[0:v]{grade},ass='{ass_esc}':fontsdir='{fdir}'[v];"
              f"[1:a]aformat=sample_rates=44100:channel_layouts=stereo,asplit=2[voz][sc];"
              f"[2:a]aformat=sample_rates=44100:channel_layouts=stereo[fx];")
        if musica:
            entradas += ["-stream_loop", "-1", "-i", str(musica)]
            fc += (f"[3:a]aformat=sample_rates=44100:channel_layouts=stereo,volume={vol},"
                   f"afade=t=out:st={max(dur - 1.2, 0):.2f}:d=1.2[mus];"
                   f"[mus][sc]sidechaincompress=threshold=0.04:ratio=6:attack=15:release=350[duck];"
                   f"[voz][duck][fx]amix=inputs=3:duration=first:normalize=0,alimiter=limit=0.95,apad[a]")
        else:
            print("⚠️  No hay música en assets/music/: el vídeo irá con voz y efectos.")
            fc += "[sc]anullsink;[voz][fx]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95,apad[a]"
        v = cfg["video"]
        ejecutar(["ffmpeg", "-y", *entradas, "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
                  "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", v["preset"], "-crf", str(v["crf"]),
                  "-maxrate", "12M", "-bufsize", "24M", "-pix_fmt", "yuv420p", "-r", str(v["fps"]),
                  "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(final)])

    info = info_video(final)
    negros = detectar_negros(final)
    caps = capturas(final, tiempos, tirada / "05_capturas")
    problemas = []
    if (info["ancho"], info["alto"]) != (cfg["video"]["ancho"], cfg["video"]["alto"]):
        problemas.append(f"resolución {info['ancho']}x{info['alto']}")
    if info["duracion"] > cfg["guion"]["duracion_max_s"] + 2:
        problemas.append(f"dura {info['duracion']:.1f}s (máx {cfg['guion']['duracion_max_s']}s)")
    for n in negros:
        problemas.append(f"tramo negro {n['inicio']:.2f}-{n['fin']:.2f}s")
    previo = leer_json(tirada / "05_montaje.json") if (a.solo_capturas and (tirada / "05_montaje.json").exists()) else {}
    escribir_json(tirada / "05_montaje.json", {
        **previo,
        "fecha": ahora_iso(), "archivo": SALIDAS[5], "resolucion": f"{info['ancho']}x{info['alto']}",
        "fps": info["fps"], "duracion": round(info["duracion"], 2),
        "musica": (musica.name if musica else previo.get("musica")),
        "lineas_subtitulos": n_lineas or previo.get("lineas_subtitulos"),
        "efectos_sonido": eventos or previo.get("efectos_sonido"),
        "escenas": tiempos, "tramos_negros": negros, "capturas": caps,
        "problemas_automaticos": problemas, "revision_visual": previo.get("revision_visual"),
    })
    if not a.solo_capturas:
        shutil.rmtree(trabajo, ignore_errors=True)
    print(f"\n✅ {final.name} · {info['ancho']}x{info['alto']} · {info['fps']:.0f} fps · {info['duracion']:.1f}s")
    print("Problemas automáticos:", problemas or "ninguno")
    print("Revisa: 05_capturas/hoja.jpg y 05_capturas/zonas_ui.jpg (rojo = zona que tapa la interfaz)")


if __name__ == "__main__":
    main()
