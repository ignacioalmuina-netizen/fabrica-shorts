"""Crea la carpeta de una tirada y su encargo (00_encargo.json).

Uso:
  python scripts/nueva_tirada.py                      # tema libre, idioma según rotación
  python scripts/nueva_tirada.py --tema "tiburones"   # tema forzado
  python scripts/nueva_tirada.py --idioma en          # fuerza idioma
  python scripts/nueva_tirada.py --simulacion         # material de prueba, sin APIs ni subida

Imprime la ruta de la tirada en la última línea.
"""
import argparse
import time
from datetime import datetime

from comun import RAIZ, SALIDAS, ahora_iso, cargar_config, escribir_json, historial


def elegir_idioma(cfg: dict, forzado: str | None) -> str:
    idi = cfg["idiomas"]
    if forzado:
        if forzado not in idi:
            raise SystemExit(f"Idioma desconocido: {forzado}. Opciones: {idi['orden']}")
        return forzado
    if idi.get("modo", "rotar") != "rotar":
        return idi["modo"]
    orden = idi["orden"]
    hist = [h for h in historial() if h.get("idioma") in orden]
    if not hist:
        return orden[0]
    ultimo = hist[-1]["idioma"]
    return orden[(orden.index(ultimo) + 1) % len(orden)]


def elegir_formato(cfg: dict, forzado: str | None) -> str:
    fm = cfg["formatos"]
    orden = fm["orden_rotacion"]
    if forzado:
        if forzado not in orden:
            raise SystemExit(f"Formato desconocido: {forzado}. Opciones: {orden}")
        return forzado
    hist = [h.get("formato_id") for h in historial() if h.get("formato_id") in orden]
    if not hist:
        return orden[0]
    return orden[(orden.index(hist[-1]) + 1) % len(orden)]   # nunca el mismo que el anterior


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tema", default=None)
    ap.add_argument("--idioma", default=None)
    ap.add_argument("--simulacion", action="store_true")
    ap.add_argument("--formato", default=None, help="que_pasaria_si | cuerpo_humano | datos_quiz")
    a = ap.parse_args()

    cfg = cargar_config()
    idioma = elegir_idioma(cfg, a.idioma)
    formato = elegir_formato(cfg, a.formato)
    nombre = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    tirada = RAIZ / "runs" / nombre
    while tirada.exists():  # dos tiradas en el mismo segundo (x3)
        time.sleep(1)
        nombre = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        tirada = RAIZ / "runs" / nombre
    tirada.mkdir(parents=True)
    escribir_json(tirada / SALIDAS[0], {
        "tirada": nombre,
        "creado": ahora_iso(),
        "canal": cfg["canal"]["nombre"],
        "tema_forzado": a.tema,
        "idioma": idioma,
        "regiones": cfg["idiomas"][idioma]["regiones"],
        "formato": formato,
        "formato_nombre": cfg["formatos"][formato]["nombre"],
        "estructura": cfg["formatos"][formato]["estructura"],
        "estilo_visual": cfg["formatos"][formato]["estilo_visual"],
        "simulacion": a.simulacion,
    })
    print(f"Tirada creada · formato={formato} · idioma={idioma} · tema={a.tema or 'libre'} · simulacion={a.simulacion}")
    print(tirada)


if __name__ == "__main__":
    main()
