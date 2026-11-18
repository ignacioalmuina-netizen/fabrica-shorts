"""Utilidades compartidas por todos los scripts de la fábrica de Shorts."""
from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CONFIG_PATH = RAIZ / "config.yaml"
HISTORIAL_PATH = RAIZ / "canal" / "historial.json"

# Archivo de salida de cada paso de la cadena
SALIDAS = {
    0: "00_encargo.json",
    1: "01_tendencia.json",
    2: "02_guion.json",
    3: "03_palabras.json",       # + 03_voz.mp3
    4: "04_escenas.json",        # + 04_escenas/
    5: "05_final.mp4",
    6: "06_miniaturas.json",     # + 06_miniaturas/
    7: "07_publicacion.json",    # + 07_metadatos.json
}
EXTRA = {3: ["03_voz.mp3"], 4: ["04_escenas"], 6: ["06_miniaturas"], 7: ["07_metadatos.json"]}


# ---------------------------------------------------------------- config / env
def cargar_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(RAIZ / ".env")
    except ImportError:  # sin python-dotenv: parseo mínimo
        p = RAIZ / ".env"
        if p.exists():
            for linea in p.read_text(encoding="utf-8").splitlines():
                if "=" in linea and not linea.strip().startswith("#"):
                    k, v = linea.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def cargar_config() -> dict:
    import yaml
    cargar_env()
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def clave(nombre: str) -> str | None:
    cargar_env()
    v = os.environ.get(nombre, "").strip()
    return v or None


# ---------------------------------------------------------------- json / errores
def leer_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def escribir_json(path: Path, data) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def parar(msg: str, codigo: int = 2) -> None:
    print(f"\n❌ PARADA: {msg}", file=sys.stderr)
    sys.exit(codigo)


def requiere(tirada: Path, *nombres: str) -> None:
    """Comprueba que existen los archivos que dejó el paso anterior."""
    faltan = [n for n in nombres if not (Path(tirada) / n).exists()]
    if faltan:
        parar(f"Faltan archivos del paso anterior en {tirada}: {', '.join(faltan)}. "
              "No sigo hasta que el paso anterior los genere.")


def tirada_desde_arg(arg: str) -> Path:
    p = Path(arg)
    if not p.is_absolute():
        p = (Path.cwd() / p) if (Path.cwd() / p).exists() else (RAIZ / p)
    if not p.is_dir():
        parar(f"No existe la carpeta de la tirada: {arg}")
    return p.resolve()


def encargo(tirada: Path) -> dict:
    requiere(tirada, SALIDAS[0])
    return leer_json(Path(tirada) / SALIDAS[0])


def es_simulacion(tirada: Path) -> bool:
    return bool(encargo(tirada).get("simulacion"))


def ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def historial(incluir_simulaciones: bool = False) -> list:
    """Vídeos ya hechos (canal/historial.json). Las tiradas de prueba no cuentan."""
    if not HISTORIAL_PATH.exists():
        return []
    try:
        datos = leer_json(HISTORIAL_PATH)
    except json.JSONDecodeError:
        return []
    return datos if incluir_simulaciones else [h for h in datos if not h.get("simulacion")]


# ---------------------------------------------------------------- ffmpeg
def ejecutar(cmd: list[str], silencioso: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("Comando fallido:", " ".join(map(str, cmd)), file=sys.stderr)
        print(r.stderr[-3000:], file=sys.stderr)
        raise RuntimeError(f"Falló {cmd[0]}")
    if not silencioso:
        print(r.stdout)
    return r


def duracion_media(path: Path) -> float:
    r = ejecutar(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                  "-of", "default=nw=1:nk=1", str(path)])
    return float(r.stdout.strip())


def info_video(path: Path) -> dict:
    r = ejecutar(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                  "stream=width,height,r_frame_rate", "-show_entries", "format=duration",
                  "-of", "json", str(path)])
    d = json.loads(r.stdout)
    s = d["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    return {"ancho": s["width"], "alto": s["height"], "fps": float(num) / float(den),
            "duracion": float(d["format"]["duration"])}


# ---------------------------------------------------------------- texto
def normalizar(palabra: str) -> str:
    s = unicodedata.normalize("NFKD", palabra.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9ñ]", "", s)


def tokenizar(texto: str) -> list[str]:
    return [t for t in re.split(r"\s+", texto.strip()) if t]


def palabras_guion(guion: dict) -> list[tuple[int, str]]:
    """Lista (indice_escena, palabra) con todas las palabras del guion en orden."""
    out = []
    for i, esc in enumerate(guion["escenas"]):
        for w in tokenizar(esc["narracion"]):
            out.append((i, w))
    return out


def alinear_escenas(guion: dict, palabras_voz: list[dict]) -> list[int]:
    """Asigna a cada palabra de la voz el índice de escena del guion.

    Usa SequenceMatcher sobre palabras normalizadas, así funciona aunque el TTS
    trocee distinto (números, signos, contracciones)."""
    pg = palabras_guion(guion)
    a = [normalizar(w) for _, w in pg]
    b = [normalizar(p["palabra"]) for p in palabras_voz]
    escena_de_b = [None] * len(b)
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            escena_de_b[blk.b + k] = pg[blk.a + k][0]
    # Rellenar huecos con la escena anterior conocida (o la siguiente al principio)
    ultima = None
    for i in range(len(escena_de_b)):
        if escena_de_b[i] is None:
            escena_de_b[i] = ultima
        else:
            ultima = escena_de_b[i]
    siguiente = 0
    for i in range(len(escena_de_b) - 1, -1, -1):
        if escena_de_b[i] is None:
            escena_de_b[i] = siguiente
        else:
            siguiente = escena_de_b[i]
    # Monotonía: una escena nunca vuelve atrás
    for i in range(1, len(escena_de_b)):
        escena_de_b[i] = max(escena_de_b[i], escena_de_b[i - 1])
    return escena_de_b


def tiempos_escenas(guion: dict, palabras: list[dict], duracion_audio: float,
                    cola: float = 0.35) -> list[dict]:
    """Inicio/fin de cada escena según cuándo la voz empieza a decir su parte."""
    n = len(guion["escenas"])
    inicios = [None] * n
    for p in palabras:
        e = p["escena"]
        if inicios[e] is None:
            inicios[e] = p["inicio"]
    # Escenas sin palabras alineadas: repartir entre vecinas
    for i in range(n):
        if inicios[i] is None:
            prev = next((inicios[j] for j in range(i - 1, -1, -1) if inicios[j] is not None), 0.0)
            nxt = next((inicios[j] for j in range(i + 1, n) if inicios[j] is not None), duracion_audio)
            inicios[i] = (prev + nxt) / 2
    inicios[0] = 0.0
    fin_total = max(duracion_audio, (palabras[-1]["fin"] if palabras else 0) + cola)
    out = []
    for i in range(n):
        fin = inicios[i + 1] if i + 1 < n else fin_total
        out.append({"escena": i + 1, "inicio": round(inicios[i], 3), "fin": round(fin, 3),
                    "duracion": round(fin - inicios[i], 3)})
    return out


if __name__ == "__main__":
    # Uso: python scripts/comun.py requiere runs/X 01_tendencia.json
    if len(sys.argv) >= 4 and sys.argv[1] == "requiere":
        requiere(tirada_desde_arg(sys.argv[2]), *sys.argv[3:])
        print("OK")
