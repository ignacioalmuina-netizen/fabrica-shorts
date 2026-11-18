"""Genera una pista de fondo sin derechos (pulso cinematográfico) en assets/music/.

Uso: python scripts/musica_base.py
Sirve para empezar. Lo ideal es poner música de la Biblioteca de audio de YouTube en assets/music/.
"""
import numpy as np
import wave

from comun import RAIZ

SR = 44100
BPM = 100
COMPASES = 16                   # 16 compases de 4/4 a 100 BPM ≈ 38 s
ACORDES = [(57, 60, 64), (53, 57, 60), (48, 52, 55), (55, 59, 62)]   # Am F C G


def nota(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def main():
    beat = 60 / BPM
    n = int(SR * beat * 4 * COMPASES)
    t = np.arange(n) / SR
    mix = np.zeros(n, np.float32)
    rng = np.random.default_rng(5)
    for c in range(COMPASES):
        acorde = ACORDES[(c // 2) % 4]
        ini = int(c * 4 * beat * SR)
        fin = int((c + 1) * 4 * beat * SR)
        tt = t[ini:fin] - t[ini]
        # colchón (pad) con ataque lento
        pad = sum(np.sin(2 * np.pi * nota(m) * tt) + 0.4 * np.sin(2 * np.pi * nota(m + 12) * tt * 1.002) for m in acorde)
        env = np.minimum(1, tt / 0.6) * np.minimum(1, (tt[-1] - tt + 0.01) / 0.3)
        mix[ini:fin] += 0.05 * pad * env
        # bajo en corcheas
        raiz = nota(acorde[0] - 24)
        for k in range(8):
            a = ini + int(k * beat / 2 * SR)
            L = int(beat / 2 * SR * 0.9)
            tb = np.arange(L) / SR
            mix[a:a + L] += 0.22 * np.tanh(2 * np.sin(2 * np.pi * raiz * tb)) * np.exp(-tb * 5)
        # bombo en cada tiempo, hi-hat en contratiempo
        for k in range(4):
            a = ini + int(k * beat * SR)
            L = int(0.35 * SR)
            tk = np.arange(L) / SR
            f = 45 + 110 * np.exp(-tk * 30)
            mix[a:a + L] += 0.55 * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tk * 9)
            h = a + int(beat / 2 * SR)
            Lh = int(0.05 * SR)
            ruido = rng.uniform(-1, 1, Lh)
            ruido = ruido - np.convolve(ruido, np.ones(4) / 4, mode="same")      # paso alto barato
            mix[h:h + Lh] += 0.12 * ruido * np.exp(-np.arange(Lh) / SR * 70)
    mix /= np.max(np.abs(mix)) + 1e-9
    destino = RAIZ / "assets" / "music" / "pulso_cinematico.wav"
    destino.parent.mkdir(parents=True, exist_ok=True)
    estereo = np.stack([mix, mix], axis=1)
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((estereo * 30000).astype(np.int16).tobytes())
    print("creado", destino)


if __name__ == "__main__":
    main()
