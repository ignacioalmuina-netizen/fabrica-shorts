---
name: hacer-shorts
description: Fabrica YouTube Shorts de principio a fin con la cadena de 7 subagentes. Úsala SIEMPRE que el usuario o una tarea programada pida hacer, crear, generar o fabricar shorts o vídeos ("haz shorts", "hazme 3 shorts", "saca los vídeos de hoy", "make shorts"), con o sin tema y número.
---

Sigue EXACTAMENTE `.claude/commands/nuevo-short.md` (eres el orquestador), sin preguntar nada al usuario:

- Número de Shorts: el que pida ("3 shorts" → x3). Si no dice número, usa `automatizacion.shorts_por_tirada` de `config.yaml`.
- Tema: si lo da, tema forzado; si no, libre (el cazador elige lo que esté petando).
- Idioma y formato: déjalos a la rotación automática salvo que los pida.
- No pidas confirmaciones: el usuario quiere cero intervención. Si un paso falla dos veces, para ESE Short, apúntalo en el resumen y sigue con el siguiente.
- Si una clave falta (imágenes, YouTube), no inventes material: para la cadena en ese paso y di exactamente qué clave falta y dónde se pone (README).
- Al final, el resumen con tabla (formato · tema · gancho · duración · miniatura · link/estado).
