"""Comprueba qué pasos de una tirada están completos.

Uso:
  python scripts/estado.py runs/X            # tabla con todos los pasos
  python scripts/estado.py runs/X --paso 3   # exit 0 si el paso 3 dejó su salida, 1 si no
"""
import argparse
import sys

from comun import EXTRA, SALIDAS, tirada_desde_arg

NOMBRES = {0: "encargo", 1: "cazador-tendencias", 2: "guionista", 3: "locutor",
           4: "director-escenas", 5: "montador", 6: "diseñador-miniaturas", 7: "publicador"}


def completo(tirada, paso: int) -> tuple[bool, list[str]]:
    faltan = []
    for n in [SALIDAS[paso]] + EXTRA.get(paso, []):
        p = tirada / n
        if not p.exists() or (p.is_file() and p.stat().st_size == 0) or (p.is_dir() and not any(p.iterdir())):
            faltan.append(n)
    return (not faltan), faltan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tirada")
    ap.add_argument("--paso", type=int)
    a = ap.parse_args()
    t = tirada_desde_arg(a.tirada)
    if a.paso is not None:
        ok, faltan = completo(t, a.paso)
        print(f"Paso {a.paso} ({NOMBRES[a.paso]}): {'OK' if ok else 'FALTA ' + ', '.join(faltan)}")
        sys.exit(0 if ok else 1)
    for paso in SALIDAS:
        ok, faltan = completo(t, paso)
        print(f"{'✅' if ok else '⬜'} {paso} {NOMBRES[paso]:<22} {'' if ok else 'falta: ' + ', '.join(faltan)}")


if __name__ == "__main__":
    main()
