---
description: Fabrica un YouTube Short de principio a fin con 7 subagentes en cadena (tendencia → guion → voz → escenas → montaje → miniaturas → subida)
argument-hint: "[tema | xN] [--es|--en] [--prueba]"
---

Eres el **orquestador** de la fábrica de Shorts. NO haces el trabajo de los agentes: creas la tirada, llamas a los 7 subagentes EN ORDEN con la herramienta Agent, compruebas cada salida y al final das un resumen.

Argumentos recibidos: `$ARGUMENTS`

## 1. Interpretar los argumentos
- Vacío → 1 Short con tema libre (el cazador elige lo que más esté funcionando).
- `xN` (p. ej. `x3`) → N Shorts seguidos, uno detrás de otro, cada uno con su tirada. Tema libre.
- Cualquier otro texto → tema forzado (p. ej. `tiburones` o `agujeros negros`).
- `--es` / `--en` → fuerza el idioma (si no, se alterna según `config.yaml > idiomas`).
- `--formato que_pasaria_si|cuerpo_humano|datos_quiz` → fuerza el formato (si no, rota solo: nunca la misma plantilla seguida).
- `--prueba` → tirada de simulación: material de prueba, sin APIs de pago y sin subir nada.

## 2. Para cada Short (si es `xN`, repite este bloque N veces, de uno en uno)

### 2.1 Crear la tirada
```bash
python scripts/nueva_tirada.py [--tema "<tema>"] [--idioma es|en] [--formato <id>] [--simulacion]
```
La última línea que imprime es la ruta absoluta de la tirada → guárdala como `TIRADA`.

### 2.2 Llamar a los subagentes en este orden
| Paso | subagent_type | Salida obligatoria |
|---|---|---|
| 1 | `cazador-tendencias` | `01_tendencia.json` |
| 2 | `guionista` | `02_guion.json` |
| 3 | `locutor` | `03_voz.mp3` + `03_palabras.json` |
| 4 | `director-escenas` | `04_escenas/` + `04_escenas.json` |
| 5 | `montador` | `05_final.mp4` |
| 6 | `disenador-miniaturas` | `06_miniaturas/` + `06_miniaturas.json` |
| 7 | `publicador` | `07_metadatos.json` + `07_publicacion.json` |

Para cada paso:
1. Llama a Agent con `subagent_type` = el de la tabla y `run_in_background: false`, con un prompt así:
   `Tirada: <TIRADA>. Haz tu paso de la cadena siguiendo tus instrucciones. Los archivos de entrada están en esa carpeta.`
   (Añade cualquier dato útil, p. ej. "es una tirada de prueba" o el tema forzado.)
2. Al terminar, comprueba la salida:
   ```bash
   python scripts/estado.py <TIRADA> --paso <N>
   ```
3. Si falla (exit 1): **reintenta ese mismo agente UNA vez**, diciéndole qué archivo falta y el error que dio.
4. Si vuelve a fallar: **PARA la cadena** y dile al usuario: en qué paso (número y nombre del agente), qué archivo falta y el último mensaje del agente. No sigas con los pasos siguientes ni con más Shorts de un `xN`.

**Duración:** si el locutor responde "DURACIÓN EXCEDIDA", llama otra vez al `guionista` pasándole la duración real y los tiempos por escena para que recorte (los números leídos en voz alta alargan mucho), y después otra vez al `locutor`. Máximo 2 vueltas.

No modifiques tú los archivos de la tirada ni hagas el trabajo de un agente que falla.

### 2.3 Resumen del Short
Lee `01_tendencia.json`, `02_guion.json`, `05_montaje.json`, `06_miniaturas.json` y `07_publicacion.json` y da al usuario:
- **Formato** (de los 3 de la rotación) y **tema** (y por qué se eligió, 1 línea)
- **Gancho**
- **Duración**
- **Miniatura ganadora** (texto + nota) y ruta `06_miniaturas/ganadora.jpg`
- **Título**
- **Link** del vídeo (o el estado: pendiente en navegador / manual / simulación, con lo que tiene que hacer el usuario)
- Avisos importantes (vídeo bloqueado en privado por proyecto no auditado, miniatura no disponible, voz de respaldo…)

## 3. Si fueron varios (`xN`)
Al final, una tabla con una fila por Short: tema · gancho · duración · miniatura · link/estado.
