"""Crea la carpeta de una tirada y su encargo (00_encargo.json).

Uso:
  python scripts/nueva_tirada.py                        # canal al que le toca (el que lleva más sin publicar)
  python scripts/nueva_tirada.py --canal bone_logic     # canal concreto (id, nombre o @handle)
  python scripts/nueva_tirada.py --canal "Lost Files" --idioma es --tema "Mary Celeste"
  python scripts/nueva_tirada.py --formato lista        # fuerza formato (del canal)
  python scripts/nueva_tirada.py --simulacion           # material de prueba, sin APIs ni subida

Reglas: cada canal (canales.yaml) rota sus 4 formatos (nunca el mismo dos veces seguidas)
y alterna idioma (en/es). Imprime la ruta de la tirada en la última línea.
"""
import argparse
import time
from datetime import datetime

from comun import RAIZ, SALIDAS, ahora_iso, cargar_config, cargar_marcas, escribir_json, historial, normalizar


def resolver_canal(marcas: dict, texto: str) -> str:
    t = normalizar(texto.replace("@", ""))
    for mid, m in marcas.items():
        if t in (normalizar(mid), normalizar(m["nombre"]), normalizar(m.get("handle", "").replace("@", ""))):
            return mid
    for mid, m in marcas.items():  # coincidencia parcial ("bone", "lost")
        if t and (t in normalizar(mid) or t in normalizar(m["nombre"])):
            return mid
    raise SystemExit(f"Canal desconocido: {texto}. Opciones: {', '.join(m['nombre'] for m in marcas.values())}")


def canal_que_toca(marcas: dict) -> str:
    """El canal que lleva más tiempo sin vídeo (o el primero que nunca ha publicado)."""
    ultimo = {}
    for i, h in enumerate(historial()):
        if h.get("marca") in marcas:
            ultimo[h["marca"]] = i
    return min(marcas, key=lambda m: ultimo.get(m, -1))


def siguiente(opciones: list, usados: list) -> str:
    """Siguiente en la rotación, nunca igual al último usado."""
    usados = [u for u in usados if u in opciones]
    if not usados:
        return opciones[0]
    return opciones[(opciones.index(usados[-1]) + 1) % len(opciones)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--canal", default=None)
    ap.add_argument("--tema", default=None)
    ap.add_argument("--idioma", default=None)
    ap.add_argument("--formato", default=None)
    ap.add_argument("--simulacion", action="store_true")
    a = ap.parse_args()

    cfg = cargar_config()
    marcas = (cargar_marcas().get("marcas") or {})
    if not marcas:
        raise SystemExit("No hay canales.yaml con marcas")
    mid = resolver_canal(marcas, a.canal) if a.canal else canal_que_toca(marcas)
    m = marcas[mid]
    hist = [h for h in historial() if h.get("marca") == mid]

    idioma = a.idioma or siguiente(m["idiomas"], [h.get("idioma") for h in hist])
    if idioma not in m["idiomas"]:
        raise SystemExit(f"{m['nombre']} publica en {m['idiomas']}, no en {idioma}")
    formatos = list(m["formatos"])
    if a.formato:
        if a.formato not in formatos:
            raise SystemExit(f"Formato desconocido para {m['nombre']}: {a.formato}. Opciones: {formatos}")
        formato = a.formato
    else:
        formato = siguiente(formatos, [h.get("formato_id") for h in hist])
    f = m["formatos"][formato]

    nombre = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    tirada = RAIZ / "runs" / nombre
    while tirada.exists():  # dos tiradas en el mismo segundo
        time.sleep(1)
        nombre = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        tirada = RAIZ / "runs" / nombre
    tirada.mkdir(parents=True)
    voz = (m.get("voz") or {})
    escribir_json(tirada / SALIDAS[0], {
        "tirada": nombre,
        "creado": ahora_iso(),
        "marca": mid,
        "canal": m["nombre"],
        "handle": m.get("handle"),
        "tema_forzado": a.tema,
        "idioma": idioma,
        "regiones": cfg["idiomas"][idioma]["regiones"],
        "estilo_idioma": (voz.get(idioma) or {}).get("estilo") or cfg["idiomas"][idioma].get("estilo"),
        "tono_voz": voz.get("tono"),
        "tematica": m["tematica"],
        "que_se_sube": m["que_se_sube"],
        "reglas": m["reglas"],
        "descripcion_obligatoria": (m.get("descripcion_obligatoria") or {}).get(idioma),
        "etiqueta_fija": (m.get("etiqueta_fija") or {}).get(idioma),
        "ejemplos_titulos": (m.get("ejemplos_titulos") or {}).get(idioma, []),
        "formato": formato,
        "formato_nombre": f["nombre"],
        "estructura": f["estructura"],
        "estilo_visual": (m.get("estilo_visual", "") + " " + f.get("estilo_visual", "")).strip(),
        "paleta": ((m.get("config") or {}).get("miniaturas") or {}).get("colores", []),
        "simulacion": a.simulacion,
    })
    print(f"Tirada creada · canal={m['nombre']} · formato={formato} · idioma={idioma} · "
          f"tema={a.tema or 'libre'} · simulacion={a.simulacion}")
    print(tirada)


if __name__ == "__main__":
    main()
