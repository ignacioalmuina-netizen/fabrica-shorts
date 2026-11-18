"""Genera la librería de efectos de sonido base en assets/sfx/ (sin derechos, sintetizados).

Uso: python scripts/sfx.py
Puedes sustituir cualquiera por uno tuyo con el mismo nombre (whoosh.wav, boom.wav, pop.wav,
tick.wav, ding.wav, riser.wav).
"""
import math
import random
import struct
import wave

from comun import RAIZ

SR = 44100
DIR = RAIZ / "assets" / "sfx"


def guardar(nombre: str, muestras: list[float]) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    pico = max(1e-9, max(abs(s) for s in muestras))
    with wave.open(str(DIR / nombre), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", int(32000 * s / pico * 0.9)) for s in muestras))


def whoosh(d=0.42):
    n = int(SR * d)
    out, y = [], 0.0
    for i in range(n):
        t = i / n
        fc = 250 + 5500 * math.sin(math.pi * t) ** 2        # barrido de filtro
        a = 1 - math.exp(-2 * math.pi * fc / SR)
        y += a * (random.uniform(-1, 1) - y)
        out.append(y * math.sin(math.pi * t) ** 1.5)
    return out


def boom(d=1.1):
    n = int(SR * d)
    out, fase, y = [], 0.0, 0.0
    for i in range(n):
        t = i / SR
        f = 38 + 60 * math.exp(-t * 9)
        fase += 2 * math.pi * f / SR
        y += 0.02 * (random.uniform(-1, 1) - y)
        out.append((math.sin(fase) + 0.6 * y * math.exp(-t * 20)) * math.exp(-t * 3.2))
    return out


def pop(d=0.12):
    n = int(SR * d)
    return [math.sin(2 * math.pi * (700 + 900 * math.exp(-i / SR * 60)) * i / SR) * math.exp(-i / SR * 45)
            for i in range(n)]


def tick(d=0.05):
    n = int(SR * d)
    return [math.sin(2 * math.pi * 2100 * i / SR) * math.exp(-i / SR * 90) for i in range(n)]


def ding(d=0.9):
    n = int(SR * d)
    return [(math.sin(2 * math.pi * 1318.5 * i / SR) + 0.5 * math.sin(2 * math.pi * 1975.5 * i / SR)
             + 0.25 * math.sin(2 * math.pi * 2637 * i / SR)) * math.exp(-i / SR * 5) for i in range(n)]


def riser(d=1.0):
    n = int(SR * d)
    out, y = [], 0.0
    for i in range(n):
        t = i / n
        fc = 200 + 7000 * t ** 2
        a = 1 - math.exp(-2 * math.pi * fc / SR)
        y += a * (random.uniform(-1, 1) - y)
        out.append(y * t ** 2)
    return out


if __name__ == "__main__":
    random.seed(3)
    for nombre, f in [("whoosh.wav", whoosh), ("boom.wav", boom), ("pop.wav", pop), ("tick.wav", tick),
                      ("ding.wav", ding), ("riser.wav", riser)]:
        if not (DIR / nombre).exists():
            guardar(nombre, f())
            print("creado", DIR / nombre)
