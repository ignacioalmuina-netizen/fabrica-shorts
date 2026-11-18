"""Paso 2 · Valida el 02_guion.json que escribe el guionista.

Uso: python scripts/verificar_guion.py runs/X

Reglas que hace cumplir:
- Escena 1 = UNA sola pregunta irresistible, corta (cabe en ≤2 s).
- Duración total estimada entre guion.duracion_min_s y duracion_max_s (por defecto 18-30 s).
- 1 escena = 1 plano = 1 frase corta (7-14 escenas), con prompt de imagen y movimiento/efecto válidos.
- Formato = el que asignó la rotación en 00_encargo.json (nunca la misma plantilla seguida).
- Ángulo y aporte propios, 3 ganchos alternativos, fuentes con URL y "verificado": true.
"""
import argparse
import re

from comun import (SALIDAS, cargar_config, encargo, historial, leer_json, normalizar, parar, requiere,
                   tirada_desde_arg, tokenizar)

CAMPOS_ESCENA = ["narracion", "visual", "prompt_imagen"]
MOVIMIENTOS = {"push_in", "pull_out", "pan_left", "pan_right", "tilt_up", "tilt_down", "drift"}
EFECTOS = {"flash", "shake", "boom", "alarma", "cuenta_atras", "riser", "punch", "ninguno"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tirada")
    a = ap.parse_args()
    tirada = tirada_desde_arg(a.tirada)
    requiere(tirada, SALIDAS[1], SALIDAS[2])
    cfg = cargar_config()
    g_cfg = cfg["guion"]
    enc = encargo(tirada)
    g = leer_json(tirada / SALIDAS[2])
    errores, avisos = [], []

    for campo in ["titulo_trabajo", "idioma", "formato", "angulo_propio", "aporte_propio", "gancho",
                  "texto_gancho", "ganchos_alternativos", "estilo_visual", "escenas", "fuentes"]:
        if not g.get(campo):
            errores.append(f"falta '{campo}'")
    if enc.get("formato") and g.get("formato") != enc["formato"]:
        errores.append(f"formato '{g.get('formato')}' ≠ el asignado por la rotación '{enc['formato']}'")
    previos = [h.get("formato_id") for h in historial() if h.get("formato_id")]
    if previos and g.get("formato") == previos[-1]:
        errores.append(f"formato '{g['formato']}' igual que el del vídeo anterior: rota de plantilla")

    escenas = g.get("escenas") or []
    if not (g_cfg["escenas_min"] <= len(escenas) <= g_cfg["escenas_max"]):
        errores.append(f"tiene {len(escenas)} escenas; deben ser {g_cfg['escenas_min']}-{g_cfg['escenas_max']} "
                       "(1 escena = 1 plano de ~2 s)")
    for i, e in enumerate(escenas, 1):
        for c in CAMPOS_ESCENA:
            if not str(e.get(c, "")).strip():
                errores.append(f"escena {i}: falta '{c}'")
        if e.get("busqueda_stock") and re.search(r"[áéíóúñ¿¡]", e["busqueda_stock"].lower()):
            errores.append(f"escena {i}: busqueda_stock debe estar en inglés")
        if e.get("movimiento") and e["movimiento"] not in MOVIMIENTOS:
            errores.append(f"escena {i}: movimiento '{e['movimiento']}' no válido ({', '.join(sorted(MOVIMIENTOS))})")
        efs = e.get("efecto") or []
        for ef in ([efs] if isinstance(efs, str) else efs):
            if ef not in EFECTOS:
                errores.append(f"escena {i}: efecto '{ef}' no válido ({', '.join(sorted(EFECTOS))})")
        n = len(tokenizar(e.get("narracion", "")))
        if n > 16:
            avisos.append(f"escena {i}: {n} palabras; un plano de Short dura ~2-3 s (≤12 palabras). Pártela.")

    # ---- gancho: una sola pregunta, corta
    primera = escenas[0]["narracion"].strip() if escenas else ""
    if primera.count("?") != 1 or not primera.endswith("?"):
        errores.append("la escena 1 debe ser UNA sola pregunta (y nada más): p. ej. '¿Qué pasa si te tragas un chicle?'")
    if enc.get("idioma", "es") == "es" and primera and not primera.startswith("¿"):
        errores.append("en español la pregunta del gancho empieza por '¿'")
    if len(tokenizar(primera)) > g_cfg["max_palabras_gancho"]:
        errores.append(f"el gancho tiene {len(tokenizar(primera))} palabras (máx {g_cfg['max_palabras_gancho']}): "
                       "tiene que caber en 2 segundos")
    if g.get("gancho") and normalizar(g["gancho"]) != normalizar(primera):
        errores.append("'gancho' debe ser exactamente la narración de la escena 1")
    low = primera.lower().lstrip("¡¿ ")
    for mal in g_cfg["ganchos_prohibidos"]:
        if low.startswith(mal.lstrip("¡¿ ")):
            errores.append(f"el gancho empieza con una fórmula prohibida: '{mal}'")
    if len(g.get("texto_gancho", "").split()) > 7:
        errores.append("texto_gancho (la pregunta en pantalla) debe tener ≤7 palabras")
    alt = g.get("ganchos_alternativos") or []
    if len(alt) < 3:
        errores.append("hacen falta 3 ganchos alternativos (todos preguntas)")
    elif any("?" not in x for x in alt):
        errores.append("los ganchos alternativos también deben ser preguntas")
    if not g.get("justificacion_gancho"):
        errores.append("falta 'justificacion_gancho'")

    # ---- duración
    total_palabras = sum(len(tokenizar(e.get("narracion", ""))) for e in escenas)
    dur = total_palabras / g_cfg["palabras_por_segundo"]
    if not (g_cfg["duracion_min_s"] <= dur <= g_cfg["duracion_max_s"]):
        errores.append(f"duración estimada {dur:.1f}s ({total_palabras} palabras); "
                       f"debe estar entre {g_cfg['duracion_min_s']} y {g_cfg['duracion_max_s']}s")

    # ---- verdad
    fuentes = g.get("fuentes") or []
    if any(not f.get("url") or not f.get("dato") for f in fuentes):
        errores.append("cada fuente necesita 'dato' y 'url'")
    if g.get("verificado") is not True:
        errores.append("falta 'verificado': true (comprueba cada dato con WebSearch antes)")

    # ---- anti contenido clonado: ganchos casi iguales a los últimos vídeos
    for h in historial()[-10:]:
        if h.get("gancho") and normalizar(h["gancho"]) == normalizar(primera):
            errores.append(f"gancho idéntico a un vídeo anterior ({h['gancho']!r})")

    for av in avisos:
        print("⚠️ ", av)
    if errores:
        parar("02_guion.json no válido:\n - " + "\n - ".join(errores))
    print(f"✅ Guion válido · formato {g['formato']} · {len(escenas)} planos · {total_palabras} palabras · ≈{dur:.1f}s")


if __name__ == "__main__":
    main()
