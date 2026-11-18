"""Genera pistas de fondo sin derechos para cada marca en assets/music/<marca>/.

Uso: python scripts/musica_base.py            # todas
     python scripts/musica_base.py lost_files  # una

Son bases sintéticas para empezar. Lo ideal es añadir música de la Biblioteca de audio
de YouTube en la carpeta de cada marca (el montador elige al azar dentro de ella).
"""
import sys
import wave

import numpy as np

from comun import RAIZ

SR = 44100
# nota MIDI de los acordes
AM, F, C, G, EM, D, DM, BB = (57, 60, 64), (53, 57, 60), (48, 52, 55), (55, 59, 62), (52, 55, 59), (50, 54, 57), (50, 53, 57), (46, 50, 53)
PRESETS = {
    # marca: (bpm, acordes, bombo, hats, bajo, pad, nombre)
    "vice_intel": dict(bpm=112, acordes=[AM, F, C, G], bombo=1.0, hats=1.0, bajo=1.0, pad=0.06, arpegio=True, nombre="neon_nocturno.wav"),
    "odd_atlas": dict(bpm=100, acordes=[C, G, AM, F], bombo=0.7, hats=0.8, bajo=0.7, pad=0.05, arpegio=True, nombre="curiosidad.wav"),
    "bone_logic": dict(bpm=88, acordes=[EM, C, G, D], bombo=0.5, hats=0.4, bajo=0.6, pad=0.06, arpegio=False, nombre="calma_gym.wav"),
    "lost_files": dict(bpm=60, acordes=[DM, DM, BB, AM], bombo=0.6, hats=0.0, bajo=0.4, pad=0.09, arpegio=False, latido=True, nombre="tension_suave.wav"),
}


def nota(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def generar(p: dict, compases: int = 16) -> np.ndarray:
    beat = 60 / p["bpm"]
    n = int(SR * beat * 4 * compases)
    mix = np.zeros(n, np.float32)
    rng = np.random.default_rng(7)
    for c in range(compases):
        ac = p["acordes"][(c // 2) % len(p["acordes"])]
        ini, fin = int(c * 4 * beat * SR), int((c + 1) * 4 * beat * SR)
        tt = np.arange(fin - ini) / SR
        pad = sum(np.sin(2 * np.pi * nota(m) * tt) + 0.35 * np.sin(2 * np.pi * nota(m + 12) * tt * 1.003) for m in ac)
        env = np.minimum(1, tt / 0.8) * np.minimum(1, (tt[-1] - tt + 0.01) / 0.4)
        mix[ini:fin] += p["pad"] * pad * env
        for k in range(8):                                   # bajo en corcheas
            a = ini + int(k * beat / 2 * SR)
            L = int(beat / 2 * SR * 0.9)
            tb = np.arange(L) / SR
            mix[a:a + L] += 0.2 * p["bajo"] * np.tanh(2 * np.sin(2 * np.pi * nota(ac[0] - 24) * tb)) * np.exp(-tb * 5)
        if p.get("arpegio"):                                 # arpegio en semicorcheas
            for k in range(16):
                a = ini + int(k * beat / 4 * SR)
                L = int(beat / 4 * SR)
                tb = np.arange(L) / SR
                m = ac[k % 3] + (12 if k % 8 >= 4 else 0)
                mix[a:a + L] += 0.05 * np.sign(np.sin(2 * np.pi * nota(m) * tb)) * np.exp(-tb * 18)
        for k in range(4):
            a = ini + int(k * beat * SR)
            if p["bombo"]:
                L = int(0.35 * SR)
                tk = np.arange(L) / SR
                f = 45 + 110 * np.exp(-tk * 30)
                golpe = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tk * 9)
                mix[a:a + L] += 0.5 * p["bombo"] * golpe
                if p.get("latido"):                         # segundo golpe tipo latido
                    b = a + int(0.22 * SR)
                    mix[b:b + L] += 0.35 * p["bombo"] * golpe[: len(mix[b:b + L])]
            if p["hats"]:
                h = a + int(beat / 2 * SR)
                Lh = int(0.05 * SR)
                r = rng.uniform(-1, 1, Lh)
                r = r - np.convolve(r, np.ones(4) / 4, mode="same")
                mix[h:h + Lh] += 0.11 * p["hats"] * r * np.exp(-np.arange(Lh) / SR * 70)
    return mix / (np.max(np.abs(mix)) + 1e-9)


def guardar(mix: np.ndarray, destino) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    estereo = np.stack([mix, mix], axis=1)
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((estereo * 30000).astype(np.int16).tobytes())
    print("creado", destino)


if __name__ == "__main__":
    for marca in (sys.argv[1:] or PRESETS):
        p = PRESETS[marca]
        guardar(generar(p), RAIZ / "assets" / "music" / marca / p["nombre"])
