# Fábrica de YouTube Shorts

> **Si el usuario (o una tarea programada) pide hacer shorts/vídeos en lenguaje normal** ("haz shorts",
> "hazme 3 shorts de tiburones", "saca los vídeos de hoy"), ejecuta la skill `hacer-shorts`
> (= flujo de `.claude/commands/nuevo-short.md`) **sin preguntar nada**. El usuario quiere cero intervención.

Cadena de montaje de 7 subagentes. El usuario escribe `/nuevo-short` y el agente principal
(orquestador, `.claude/commands/nuevo-short.md`) llama a los subagentes **en orden** con la
herramienta Agent. Cada subagente hace UNA tarea: lee lo que dejó el anterior en la carpeta de
la tirada y deja su resultado. Se comunican **solo por archivos**.

## La tirada
Cada vídeo vive en `runs/<AAAA-MM-DD_HHMMSS>/`, creada por `scripts/nueva_tirada.py`.

| Paso | Agente (`.claude/agents/`) | Script (`scripts/`) | Lee | Deja |
|---|---|---|---|---|
| 0 | orquestador | `nueva_tirada.py` | config | `00_encargo.json` (idioma, regiones, tema forzado, simulación) |
| 1 | `cazador-tendencias` | `tendencias.py` | 00 | `01_candidatos.json` (script), `01_tendencia.json` (agente) |
| 2 | `guionista` | `verificar_guion.py` | 01 | `02_guion.json` |
| 3 | `locutor` | `voz.py` | 02 | `03_voz.mp3`, `03_palabras.json` (palabras con inicio/fin/escena + tiempos de escena) |
| 4 | `director-escenas` | `escenas.py` | 02, 03 | `04_escenas/` (escena_XX.mp4/png, frame_XX.jpg), `04_escenas.json` |
| 5 | `montador` | `montaje.py` | 02, 03, 04 | `05_final.mp4`, `05_subtitulos.ass`, `05_capturas/`, `05_montaje.json` |
| 6 | `disenador-miniaturas` | `miniaturas.py` | 02, 04 | `06_conceptos.json`, `06_puntuaciones.json`, `06_miniaturas/`, `06_miniaturas.json` |
| 7 | `publicador` | `upload.py`, `historial.py` | 01, 02, 05, 06 | `07_metadatos.json`, `07_paquete/`, `07_publicacion.json`, entrada en `canal/historial.json` |

- `python scripts/estado.py runs/X` → qué pasos están hechos. `--paso N` → exit 0/1 (lo usa el orquestador).
- Si falta el archivo del paso anterior, el script/agente **para** y lo dice (exit 2, "❌ PARADA").
- Reparto: el **script** hace la parte técnica (APIs, ffmpeg, Pillow, métricas); el **agente** pone el criterio (elegir, escribir, mirar imágenes, puntuar).

## Archivos clave
- `config.yaml`: todo lo ajustable (canal, idiomas/regiones/voces, búsquedas, duración, proveedor visual, subtítulos, música, miniaturas, modo de subida, privacidad, hashtags).
- `.env`: claves (`YOUTUBE_API_KEY`, `ELEVENLABS_API_KEY`, `PEXELS_API_KEY`, `OPENAI_API_KEY`). Nunca leerlo ni imprimirlo.
- `secrets/client_secret.json` y `secrets/token.json`: OAuth de YouTube. Nunca leerlos ni imprimirlos.
- `canal/historial.json`: vídeos hechos (evita repetir temas y formatos; las tiradas de prueba se ignoran).
- `canal/clips_usados.json`: clips de Pexels ya usados. `canal/cache_tendencias/`: búsquedas cacheadas.
- `assets/music/` música sin derechos · `assets/fonts/Anton-Regular.ttf` subtítulos y miniaturas.

## Formatos y reglas de contenido
- 3 formatos en `config.yaml > formatos` (`que_pasaria_si`, `cuerpo_humano`, `datos_quiz`) con estructura y `estilo_visual`. `nueva_tirada.py` los rota: nunca la misma plantilla seguida.
- Gancho = UNA pregunta en la escena 1 (≤ 9 palabras); 18-30 s; 1 escena = 1 plano = 1 frase; cada dato verificado; contenido sintético marcado si hay IA realista.
- Cada escena puede llevar `movimiento` (push_in, pull_out, pan_left, pan_right, tilt_up, tilt_down, drift), `efecto` (flash, boom, shake, alarma, riser, cuenta_atras) y `recorte` [cx, cy, zoom].
- `scripts/escenas.py --escena N --importar img.png` mete material generado fuera (p. ej. conector ElevenLabs); `--recorte/--movimiento/--efecto` ajustan el plano.
- `assets/sfx/` (scripts/sfx.py) y `assets/music/` (scripts/musica_base.py) los usa el motor de `montaje.py`.

## Reglas importantes
- **Cuota YouTube API**: 10.000 unidades/día; `search.list` = 100. Una búsqueda por región y consulta por tirada, con caché de 6 h. No relanzar búsquedas.
- **Subida**: modo por defecto `navegador` (Claude in Chrome en YouTube Studio). Con `api`, un proyecto de Google Cloud NO auditado deja los vídeos en PRIVADO para siempre.
- **Miniaturas en Shorts** pueden no estar disponibles en el canal: si `thumbnails.set` falla se registra y se sigue.
- **Contenido repetitivo**: el guionista varía formato y aporta algo propio; `verificar_guion.py` bloquea repetir el formato de las 2 últimas tiradas.
- **Datos verdaderos**: el guionista verifica con WebSearch y guarda las fuentes.
- **Simulación** (`/nuevo-short --prueba`): imágenes de prueba, voz edge-tts (flite solo si no hay red), sin APIs de pago ni subida. Sirve para probar la cadena, NO para juzgar la calidad.
