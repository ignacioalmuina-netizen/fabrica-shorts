# 🏭 Fábrica de YouTube Shorts con subagentes de Claude Code

Escribes `/nuevo-short` y 7 agentes hacen el resto, como una cadena de montaje:

```
cazador-tendencias → guionista → locutor → director-escenas → montador → disenador-miniaturas → publicador
   01_tendencia       02_guion    03_voz      04_escenas        05_final      06_miniaturas         07_publicación
```

Cada vídeo se fabrica en su propia carpeta `runs/<fecha-hora>/`. Cada agente lee el archivo que
dejó el anterior y deja el suyo. Si algo falla, la cadena se para y te dice en qué paso.

---

## 1. Instalar Python y ffmpeg

**Windows** (PowerShell):
```bash
winget install Python.Python.3.12
```
```bash
winget install Gyan.FFmpeg
```
**macOS**:
```bash
brew install python ffmpeg
```
**Linux (Ubuntu/Debian)**:
```bash
sudo apt install python3 python3-venv ffmpeg
```
Comprueba que funcionan (cierra y abre la terminal antes):
```bash
python --version
```
```bash
ffmpeg -version
```

## 2. Instalar el proyecto

Necesitas [Claude Code](https://code.claude.com) instalado. En la carpeta del proyecto:
```bash
python -m venv .venv
```
Actívalo (Windows: `.venv\Scripts\activate` · macOS/Linux: `source .venv/bin/activate`) e instala:
```bash
pip install -r requirements.txt
```
Copia el archivo de claves:
```bash
cp .env.example .env
```
(En Windows: `copy .env.example .env`.) Ahora rellena `.env` con las claves de los pasos siguientes.

Abre `config.yaml` y cambia al menos `canal.nombre`.

## 3. Clave de YouTube Data API (`YOUTUBE_API_KEY`) — obligatoria, gratis

Sirve para buscar qué Shorts están petando.
1. Entra en <https://console.cloud.google.com> y crea un proyecto (arriba, "Seleccionar proyecto" → "Proyecto nuevo"), p. ej. `fabrica-shorts`.
2. Menú → **APIs y servicios → Biblioteca** → busca **YouTube Data API v3** → **Habilitar**.
3. **APIs y servicios → Credenciales → Crear credenciales → Clave de API**.
4. Pulsa en la clave → "Restricciones de API" → restringe a *YouTube Data API v3* → Guardar.
5. Pégala en `.env` → `YOUTUBE_API_KEY=...`

Cuota gratis: 10.000 unidades al día. Cada tirada gasta unas 400 (ES/MX/AR/CO) o 200 (US/GB), así que
llega de sobra para 20+ Shorts al día. La búsqueda se guarda 6 horas para que `x3` no gaste el triple.

## 4. Pexels (`PEXELS_API_KEY`) — recomendada, gratis

Vídeo de stock vertical real.
1. Crea una cuenta en <https://www.pexels.com> y entra en <https://www.pexels.com/api/>.
2. Pulsa **Your API Key**, rellena para qué la usas (p. ej. "vídeos educativos para YouTube") y copia la clave.
3. `.env` → `PEXELS_API_KEY=...`

## 5. ElevenLabs (`ELEVENLABS_API_KEY`) — opcional, de pago (la mejor voz)

Sin ella se usa **edge-tts** (gratis, buena calidad) automáticamente.
1. Cuenta en <https://elevenlabs.io>. Para usar la voz en YouTube monetizado necesitas como mínimo el plan **Starter** (el gratuito no permite uso comercial).
2. Menú de tu perfil → **Developers / API Keys** → **Create API key** (con permiso de *Text to Speech*).
3. `.env` → `ELEVENLABS_API_KEY=...`
4. Voz: `config.yaml` ya trae **SAM ADAM** (`18GZPpJvaVG53Nt3H52N`, enérgica, latina neutra, hecha para curiosidades). Entra en **Voice Library**, búscala y pulsa "Add to my voices" para poder usarla por API. Para inglés, elige otra y pega su **Voice ID** en `idiomas.en.voz.elevenlabs_voice_id`.

## 6. OpenAI (`OPENAI_API_KEY`) — recomendada, de pago (imágenes IA 3D)

Es el proveedor visual por defecto (`visual.proveedor: openai`): una imagen por plano con el estilo del formato. ~11 planos por Short.
Alternativa: si en Claude Code tienes conectado **ElevenLabs** (conector de claude.ai), el director de escenas puede generar las imágenes con él e importarlas (`scripts/escenas.py --importar`).
1. <https://platform.openai.com/api-keys> → **Create new secret key**.
2. Añade saldo en *Billing*. Para el modelo `gpt-image-1` puede que te pida **verificar la organización** (Settings → Organization → Verify).
3. `.env` → `OPENAI_API_KEY=...`

Coste orientativo: ~0,04-0,06 $ por imagen en calidad `medium`.

## 7. Conectar tu canal (OAuth de Google) — para subir por API

> Si vas a usar el modo `navegador` (el de por defecto) puedes saltarte este paso de momento.

En el **mismo proyecto** de Google Cloud del paso 3:
1. **APIs y servicios → Pantalla de consentimiento de OAuth** (o "Google Auth Platform") → **Empezar**.
   - Nombre de la app: `Fabrica Shorts`, tu email de soporte, público **Externo**, tu email de contacto → Crear.
2. **Público → Usuarios de prueba → Add users** → añade el email de la cuenta de Google dueña del canal.
3. **Clientes → Crear cliente** → tipo **Aplicación de escritorio** → Crear → **Descargar JSON**.
4. Guarda ese archivo como `secrets/client_secret.json`.
5. Ejecuta:
   ```bash
   python scripts/upload.py --login
   ```
   Se abre el navegador → elige tu cuenta → "Google no ha verificado esta aplicación" → **Continuar** (es tu propia app) → acepta los permisos. Verás `✅ Canal conectado: <tu canal>`. El token queda en `secrets/token.json`.

Mientras la app esté en modo "Prueba", Google caduca el token cada 7 días: vuelve a ejecutar `--login` cuando te lo pida.

## 8. ⚠️ Subir por API: la auditoría de Google

Los vídeos subidos con la API desde un proyecto de Google Cloud **no auditado** quedan **bloqueados en PRIVADO para siempre** (aunque pidas "público"). Por eso el modo por defecto es **`navegador`**.

Para pasar a modo `api`:
1. Rellena el formulario **"YouTube API Services – Audit and Quota Extension Form"**: <https://support.google.com/youtube/contact/yt_api_form>
2. Indica: nombre y número del proyecto de Google Cloud, que es una herramienta interna que sube vídeos **solo a tu propio canal**, el flujo (generación → `videos.insert` → `thumbnails.set`), y que cumples las Políticas de Servicios de API de YouTube. Puede que te pidan capturas o un vídeo del flujo de autorización.
3. Espera la respuesta (de días a varias semanas).
4. Cuando lo aprueben, en `config.yaml`:
   ```yaml
   publicacion:
     modo: api
     proyecto_auditado: true
   ```

## 9. Modo `navegador` (por defecto): Claude in Chrome

El publicador abre YouTube Studio en **tu** Chrome y sube el vídeo como lo harías tú.
1. Instala la extensión **Claude in Chrome** desde la Chrome Web Store e inicia sesión con tu cuenta de Claude.
2. En ese Chrome, entra en <https://studio.youtube.com> con la cuenta del canal.
3. Arranca Claude Code con Chrome conectado (`claude --chrome`, o el comando `/chrome` dentro de Claude Code).

Si el navegador no está disponible, el publicador no rompe nada: deja el paquete listo en `runs/<tirada>/07_paquete/` (vídeo, miniatura y `metadatos.txt` para copiar y pegar). Cuando lo subas a mano, apunta el enlace:
```bash
python scripts/upload.py runs/<tirada> --registrar --url https://youtube.com/shorts/XXXX
```

Modo `manual`: igual, pero sin intentar el navegador.

## 10. Música y efectos

- `assets/music/pulso_cinematico.wav` es una base sintética sin derechos (`python scripts/musica_base.py`). Para subir de nivel, añade música **sin derechos** de la Biblioteca de audio de YouTube Studio (filtro "Atribución no obligatoria"): el montador elige una al azar sin repetir las 3 últimas.
- `assets/sfx/` trae whoosh, boom, pop, tick, ding y riser sintetizados (`python scripts/sfx.py`). Puedes sustituirlos por los tuyos con el mismo nombre.

## 11. ¡Tu primer Short!

Abre Claude Code en la carpeta del proyecto:
```bash
claude
```
1. Primero, una **prueba sin gastar nada** (material sintético, no se sube):
   ```
   /nuevo-short --prueba
   ```
2. El primero de verdad:
   ```
   /nuevo-short
   ```
3. Otras formas:
   ```
   /nuevo-short tiburones          ← tema concreto
   /nuevo-short x3                 ← tres Shorts seguidos
   /nuevo-short --en               ← fuerza inglés
   /nuevo-short --formato datos_quiz   ← fuerza uno de los 3 formatos
   ```

Al final te da: tema, gancho, duración, miniatura ganadora y enlace.

---

## Los 3 formatos (rotan solos)

| Formato | Estructura (inspirada en, sin copiar) | Look |
|---|---|---|
| `que_pasaria_si` | What If / Zack D. Films: pregunta hipotética → consecuencias que escalan → giro → pregunta de vuelta | Render 3D cinematográfico hiperrealista |
| `cuerpo_humano` | Helix²: "¿qué le pasa a tu cuerpo si…?" → viaje por dentro / línea temporal → mito roto | Cuerpo 3D translúcido tipo rayos X, órganos iluminados |
| `datos_quiz` | BIG Facts / Trivia: pregunta → cuenta atrás 3-2-1 "comenta" → revelación con golpe → 2 datos extra | Foto cinematográfica de alto contraste |

Nunca se repite la misma plantilla dos veces seguidas (`scripts/nueva_tirada.py` lleva la rotación).

**Reglas que la cadena hace cumplir** (si no, `verificar_guion.py` para la cadena):
1. Gancho = UNA sola pregunta en la escena 1 (≤ 9 palabras, cabe en 2 s) y en pantalla en caja amarilla.
2. 18-30 segundos en total.
3. Formato rotado; nunca la misma plantilla seguida.
4. Ángulo y aporte propios, ganchos que no se repiten (política de *inauthentic content*).
5. Cada dato verificado con fuentes antes de generar nada.
6. Contenido sintético marcado automáticamente cuando hay imágenes IA realistas.

**El montaje** (`scripts/montaje.py`) renderiza fotograma a fotograma: un plano por frase (cortes cada ~2 s), movimiento de cámara con curva (push-in, pull-out, paneos), golpe de zoom en cada corte, temblor, destellos, pulso rojo de alarma, viñeta, barra de progreso, subtítulos que rebotan palabra a palabra, whoosh/boom/pop/tic-tac sincronizados y música con *ducking*.

## Qué hace cada agente

| Agente | Qué hace | Deja |
|---|---|---|
| cazador-tendencias | Busca Shorts de los últimos 7 días (≤ 180 s), ordena por views/hora y views/suscriptor, elige 1 tema que no esté en el historial y explica por qué funciona. | `01_tendencia.json` |
| guionista | Guion de 18-30 s en el formato que toca, gancho = una pregunta, 1 frase por plano (7-14 planos) con prompt, movimiento y efecto. Verifica cada dato en internet. | `02_guion.json` |
| locutor | Voz (ElevenLabs o edge-tts) con tiempo de cada palabra, 1.08x, −14 LUFS. | `03_voz.mp3`, `03_palabras.json` |
| director-escenas | Una imagen IA por plano con el estilo del formato (OpenAI, o el conector de ElevenLabs), elige encuadre/movimiento/efecto, mira cada fotograma y rehace lo que no encaja. | `04_escenas/`, `04_escenas.json` |
| montador | Motor propio 1080x1920 30 fps: cámara animada, punch, shake, flash, alarma, gancho en pantalla, subtítulos con rebote, efectos de sonido y música; revisa capturas. | `05_final.mp4` |
| disenador-miniaturas | 10 conceptos distintos, hoja de contacto a tamaño móvil, notas 1-10 + métricas de contraste y colorido, ganadora. | `06_miniaturas/`, `06_miniaturas.json` |
| publicador | Título < 60, descripción, tags; sube (navegador / api / manual); apunta en el historial. | `07_metadatos.json`, `07_publicacion.json` |

Todo lo ajustable está en `config.yaml`. La explicación técnica de la cadena está en `CLAUDE.md`.

## Idiomas

`config.yaml > idiomas.modo: rotar` alterna español (neutro, para España y Latinoamérica) e inglés en cada tirada.
YouTube recomienda **un canal por idioma**: si mezclar idiomas en un canal te baja la retención, pon `modo: es` (o `en`) y usa otro proyecto/carpeta para el otro canal.

## Problemas frecuentes

- **"❌ PARADA: Falta YOUTUBE_API_KEY"** → revisa `.env` (paso 3).
- **"Cuota de YouTube Data API agotada"** → espera a mañana (se renueva a medianoche, hora del Pacífico) o baja `idiomas.es.regiones`.
- **La voz sale con edge-tts aunque pagué ElevenLabs** → clave mal copiada o sin saldo; el locutor usa edge-tts de respaldo y lo avisa.
- **El vídeo subido por API está en privado y no se puede cambiar** → proyecto no auditado (paso 8). Usa modo `navegador`.
- **"thumbnails.set falló"** → tu canal aún no tiene miniaturas personalizadas en Shorts (o falta verificar el canal por teléfono en youtube.com/verify). El vídeo se publica igual.
- **Ver en qué paso se quedó una tirada**: `python scripts/estado.py runs/<tirada>`
