"""Paso 7 · Publicador: sube el Short a YouTube.

Uso:
  python scripts/upload.py --login                    # conecta tu canal (OAuth), una sola vez
  python scripts/upload.py runs/X --validar           # valida 07_metadatos.json
  python scripts/upload.py runs/X                     # publica según publicacion.modo de config.yaml
  python scripts/upload.py runs/X --modo manual       # fuerza un modo (api | navegador | manual)
  python scripts/upload.py runs/X --registrar --url https://youtube.com/shorts/ID [--miniatura ok|error|no_disponible]
                                                      # tras subir por navegador o a mano

Modos:
  navegador (por defecto): prepara 07_paquete/ y el agente lo sube con Claude in Chrome.
  api:    videos.insert (OAuth) + thumbnails.set cuando YouTube termina de procesar.
          ⚠️ Con un proyecto de Google Cloud NO auditado el vídeo queda PRIVADO para siempre.
  manual: prepara 07_paquete/ y lo subes tú.
"""
import argparse
import os
import shutil
import sys
import time
from pathlib import Path

from comun import (RAIZ, SALIDAS, ahora_iso, cargar_config, escribir_json, leer_json, parar,
                   requiere, tirada_desde_arg)
from historial import apuntar

SECRETS = RAIZ / "secrets"
CLIENT_SECRET = SECRETS / "client_secret.json"
TOKEN = SECRETS / "token.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube"]


# ------------------------------------------------------------------ OAuth
def ruta_token(marca: str | None) -> Path:
    """Un token OAuth por canal: secrets/token_<marca>.json (o token.json si no hay marca)."""
    return SECRETS / (f"token_{marca}.json" if marca else "token.json")


def credenciales(interactivo: bool = False, marca: str | None = None):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    TOKEN = ruta_token(marca)
    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES) if TOKEN.exists() else None
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN.write_text(creds.to_json())
        except Exception:  # noqa: BLE001
            creds = None
    if creds and creds.valid:
        return creds
    if not interactivo:
        parar("No hay sesión de YouTube válida para este canal. Ejecuta: "
              f"python scripts/upload.py --login --canal {marca or '<canal>'}")
    if not CLIENT_SECRET.exists():
        parar(f"Falta {CLIENT_SECRET}. Descárgalo de Google Cloud (README, paso 5).")
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True, prompt="consent",
                                  authorization_prompt_message="Abre este enlace para autorizar tu canal:\n{url}\n")
    SECRETS.mkdir(exist_ok=True)
    TOKEN.write_text(creds.to_json())
    try:
        os.chmod(TOKEN, 0o600)
    except OSError:
        pass
    return creds


def youtube(creds):
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def login(marca: str | None = None):
    yt = youtube(credenciales(interactivo=True, marca=marca))
    r = yt.channels().list(part="snippet", mine=True).execute()
    if not r.get("items"):
        parar("La cuenta no tiene canal de YouTube. Crea uno en youtube.com primero.")
    print(f"✅ Canal conectado: {r['items'][0]['snippet']['title']} (token en {ruta_token(marca)})")


# ------------------------------------------------------------------ metadatos
def validar_metadatos(tirada: Path, cfg: dict) -> dict:
    requiere(tirada, "07_metadatos.json")
    m = leer_json(tirada / "07_metadatos.json")
    err = []
    t = m.get("titulo", "")
    if not t:
        err.append("falta titulo")
    elif len(t) >= 60:
        err.append(f"el título tiene {len(t)} caracteres (debe ser < 60)")
    if "<" in t or ">" in t:
        err.append("el título no puede llevar < ni >")
    if not m.get("descripcion"):
        err.append("falta descripcion")
    elif len(m["descripcion"]) > 5000:
        err.append("descripción > 5000 caracteres")
    tags = m.get("tags") or []
    if not tags:
        err.append("faltan tags")
    if sum(len(x) + (2 if " " in x else 0) for x in tags) + len(tags) > 500:
        err.append("los tags suman más de 500 caracteres")
    if len(tags) > cfg["publicacion"]["max_tags"]:
        err.append(f"más de {cfg['publicacion']['max_tags']} tags")
    for h in cfg["publicacion"]["hashtags_fijos"]:
        if h.lower() not in m.get("descripcion", "").lower():
            err.append(f"la descripción debe incluir el hashtag fijo {h}")
    obligatoria = leer_json(tirada / SALIDAS[0]).get("descripcion_obligatoria")
    if obligatoria and obligatoria.lower() not in m.get("descripcion", "").lower():
        err.append(f"la descripción debe incluir el texto obligatorio del canal: {obligatoria!r}")
    if err:
        parar("07_metadatos.json no válido:\n - " + "\n - ".join(err))
    return m


def contenido_sintetico(tirada: Path, cfg: dict) -> bool:
    v = cfg["publicacion"]["contiene_contenido_sintetico"]
    if isinstance(v, bool):
        return v
    esc = leer_json(tirada / SALIDAS[4])["escenas"]
    return any(e.get("fuente") in ("openai", "ia", "elevenlabs", "cloudflare") for e in esc)


def preparar_paquete(tirada: Path, meta: dict, cfg: dict, sintetico: bool) -> Path:
    p = tirada / "07_paquete"
    p.mkdir(exist_ok=True)
    shutil.copy(tirada / SALIDAS[5], p / "video.mp4")
    gan = tirada / "06_miniaturas" / "ganadora.jpg"
    if gan.exists():
        shutil.copy(gan, p / "miniatura.jpg")
    pub = cfg["publicacion"]
    (p / "metadatos.txt").write_text(
        f"TÍTULO:\n{meta['titulo']}\n\nDESCRIPCIÓN:\n{meta['descripcion']}\n\n"
        f"TAGS (separados por comas):\n{', '.join(meta['tags'])}\n\n"
        f"AJUSTES EN YOUTUBE STUDIO:\n"
        f"- Audiencia: «No, no es contenido creado para niños» (made_for_kids={pub['made_for_kids']})\n"
        f"- Contenido alterado o sintético: {'SÍ' if sintetico else 'NO'}\n"
        f"- Visibilidad: {pub['privacidad']}\n"
        f"- Miniatura: miniatura.jpg (si tu canal ya permite miniaturas en Shorts)\n"
        f"- Categoría: {pub['categoria_id']} · Idioma: {meta.get('idioma', '')}\n",
        encoding="utf-8")
    return p


# ------------------------------------------------------------------ modos
def subir_api(tirada: Path, meta: dict, cfg: dict, sintetico: bool) -> dict:
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
    pub = cfg["publicacion"]
    if not pub["proyecto_auditado"] and pub["privacidad"] != "private":
        print("⚠️  publicacion.proyecto_auditado=false: YouTube bloqueará este vídeo en PRIVADO para siempre.\n"
              "    Pide la auditoría (README, paso 8) o usa modo navegador.")
    yt = youtube(credenciales(marca=leer_json(tirada / SALIDAS[0]).get("marca")))
    body = {
        "snippet": {"title": meta["titulo"], "description": meta["descripcion"], "tags": meta["tags"],
                    "categoryId": pub["categoria_id"], "defaultLanguage": meta.get("idioma"),
                    "defaultAudioLanguage": meta.get("idioma")},
        "status": {"privacyStatus": pub["privacidad"], "selfDeclaredMadeForKids": bool(pub["made_for_kids"]),
                   "containsSyntheticMedia": sintetico, "embeddable": True},
    }
    media = MediaFileUpload(str(tirada / SALIDAS[5]), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media, notifySubscribers=True)
    resp, intentos = None, 0
    while resp is None:
        try:
            estado, resp = req.next_chunk()
            if estado:
                print(f"  subiendo… {int(estado.progress() * 100)}%")
        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504) and intentos < 5:
                intentos += 1
                time.sleep(2 ** intentos)
                continue
            parar(f"videos.insert falló: {e}")
    vid = resp["id"]
    print(f"✅ Subido: https://youtube.com/shorts/{vid}")
    res = {"modo": "api", "video_id": vid, "url": f"https://youtube.com/shorts/{vid}", "estado": "subido",
           "privacidad": resp.get("status", {}).get("privacyStatus"),
           "bloqueado_privado_probable": not pub["proyecto_auditado"]}

    # Esperar a que termine de procesar y poner la miniatura
    limite = time.time() + pub["esperar_procesado_min"] * 60
    procesado = False
    while time.time() < limite:
        r = yt.videos().list(part="processingDetails,status", id=vid).execute()
        it = (r.get("items") or [{}])[0]
        pst = it.get("processingDetails", {}).get("processingStatus")
        if pst == "succeeded" or it.get("status", {}).get("uploadStatus") == "processed":
            procesado = True
            break
        if pst == "failed" or it.get("status", {}).get("uploadStatus") in ("failed", "rejected"):
            res["estado"] = "procesado_fallido"
            break
        time.sleep(20)
    res["procesado"] = procesado
    gan = tirada / "06_miniaturas" / "ganadora.jpg"
    if not gan.exists():
        res["miniatura"] = "no_hay_archivo"
    elif not procesado:
        res["miniatura"] = "no_puesta_video_sin_procesar"
    else:
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(gan), mimetype="image/jpeg")).execute()
            res["miniatura"] = "ok"
            print("✅ Miniatura puesta")
        except HttpError as e:  # canal sin miniaturas en Shorts, sin verificar, etc. -> se registra y se sigue
            res["miniatura"] = "error"
            res["miniatura_error"] = str(e)[:500]
            print(f"⚠️  thumbnails.set falló (se sigue sin miniatura): {e}")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tirada", nargs="?")
    ap.add_argument("--login", action="store_true")
    ap.add_argument("--canal", help="con --login: vice_intel | odd_atlas | bone_logic | lost_files")
    ap.add_argument("--modo", choices=["api", "navegador", "manual"])
    ap.add_argument("--validar", action="store_true")
    ap.add_argument("--registrar", action="store_true")
    ap.add_argument("--url")
    ap.add_argument("--miniatura", default="desconocido")
    a = ap.parse_args()
    if a.login:
        return login(a.canal)
    if not a.tirada:
        parar("Indica la carpeta de la tirada o --login")
    tirada = tirada_desde_arg(a.tirada)
    cfg = cargar_config(tirada)
    requiere(tirada, SALIDAS[4], SALIDAS[5], SALIDAS[6])
    meta = validar_metadatos(tirada, cfg)
    if a.validar:
        print("✅ 07_metadatos.json válido")
        return
    enc = leer_json(tirada / SALIDAS[0])
    sintetico = contenido_sintetico(tirada, cfg)
    salida = tirada / SALIDAS[7]

    if a.registrar:
        if not a.url:
            parar("--registrar necesita --url")
        res = leer_json(salida) if salida.exists() else {}
        vid = a.url.rstrip("/").split("/")[-1].split("?v=")[-1].split("?")[0]
        res.update({"video_id": vid, "url": a.url, "estado": "publicado", "miniatura": a.miniatura,
                    "privacidad": cfg["publicacion"]["privacidad"], "registrado": ahora_iso()})
        escribir_json(salida, res)
        e = apuntar(tirada)
        print(f"✅ Registrado {a.url} · historial actualizado ({e['tema']})")
        return

    modo = a.modo or cfg["publicacion"]["modo"]
    paquete = preparar_paquete(tirada, meta, cfg, sintetico)
    base = {"modo": modo, "fecha": ahora_iso(), "titulo": meta["titulo"], "contiene_contenido_sintetico": sintetico,
            "made_for_kids": bool(cfg["publicacion"]["made_for_kids"]), "paquete": str(paquete.relative_to(tirada))}
    if enc.get("simulacion"):
        res = {**base, "estado": "simulacion_no_subido", "video_id": None, "url": None,
               "nota": f"Tirada de prueba: no se sube nada. Modo configurado: {modo}."}
    elif modo == "api":
        res = {**base, **subir_api(tirada, meta, cfg, sintetico)}
    elif modo == "navegador":
        res = {**base, "estado": "pendiente_navegador", "video_id": None, "url": None,
               "instrucciones": "Subir 07_paquete/video.mp4 en studio.youtube.com con los datos de metadatos.txt "
                                "y después: python scripts/upload.py <tirada> --registrar --url <url>"}
    else:
        res = {**base, "estado": "pendiente_manual", "video_id": None, "url": None,
               "instrucciones": f"Sube {paquete}/video.mp4 desde YouTube Studio copiando metadatos.txt. "
                                "Luego: python scripts/upload.py <tirada> --registrar --url <url>"}
    escribir_json(salida, res)
    e = apuntar(tirada)
    print(f"Modo {modo} · estado: {res['estado']} · paquete en {paquete}")
    print(f"📒 Historial: {e['tema']}")


if __name__ == "__main__":
    main()
