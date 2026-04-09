# Planificación — Sistema de feedback web

## Propósito

El proyecto CEND y los futuros proyectos audiovisuales requieren rondas de feedback de múltiples revisores sobre cada versión de cada pieza. Este sistema centraliza ese feedback en una web simple, lo estructura en datos accionables, y lo deja listo para que Claude genere automáticamente la lista de action items de la siguiente versión.

**Problema que resuelve:**
1. El feedback en lenguaje libre (mails, mensajes, llamadas) obliga a Claude a interpretar prosa, lo cual reduce dramáticamente la fracción de tareas que puede automatizar.
2. Sin anclaje a timecode, Claude no sabe sobre qué clip exacto opera.
3. Sin categorización, no puede enrutar el feedback a la herramienta correcta (ffmpeg para audio, MCP de Premiere para video, etc.).
4. Múltiples revisores en paralelo necesitan un punto único de captura.

**Resultado esperado:** Una web estática multi-proyecto donde los revisores ven los videos exportados (YouTube unlisted), dejan comentarios estructurados timecode-anchored, y los envían a un Google Sheet del que Claude lee para generar la lista de action items priorizada.

---

## Stack técnico

| Componente | Tecnología | Razón |
|---|---|---|
| Hosting web | GitHub Pages | Gratis, simple, ya tenemos GitHub |
| Frontend | HTML/CSS/JS vanilla | Sin build step, sin dependencias, fácil de mantener |
| Video player | YouTube IFrame API | Único hosting gratis con player API completo (currentTime + seekTo) |
| Backend | Google Apps Script + Google Sheet | Sin DB, sin límites, integra con ecosistema Drive |
| Persistencia local | localStorage | Para edit/delete antes de enviar y recuperar borradores |
| Idioma de UI | Inglés | Toda la interfaz para revisores |

---

## Arquitectura — Multi-proyecto

Cada proyecto vive en su propia carpeta dentro del repo. Agregar un proyecto nuevo = crear una carpeta con su `config.json`. El código HTML/JS es compartido y lee el config dinámicamente.

```
Feedback web/
├── index.html                        # Selector de proyectos disponibles
├── project.html                      # Home de un proyecto: ve sus piezas y versiones
├── piece.html                        # Página de revisión de una pieza
├── config.json                       # Config global: GAS endpoint + brand (compartido)
├── README.md                         # Instrucciones de uso y deploy
├── Planificación.md                  # Este documento
├── gas-endpoint.gs                   # Código Google Apps Script (deploy manual, único)
├── assets/
│   ├── css/
│   │   └── style.css                 # Estilos globales minimalistas
│   ├── js/
│   │   ├── config-loader.js          # Carga config.json del proyecto activo
│   │   ├── player.js                 # Wrapper sobre YouTube IFrame API
│   │   ├── transcript.js             # Lookup de frase del guión por timecode
│   │   ├── comments.js               # Estado de comentarios + localStorage
│   │   ├── form.js                   # Render del formulario de comentario
│   │   └── submit.js                 # POST al Google Apps Script endpoint
│   └── img/
│       └── (logo SideOutSticks cuando esté disponible)
└── projects/
    ├── cend/
    │   ├── config.json               # Datos del proyecto: piezas, versiones, video URLs
    │   └── transcripts/
    │       ├── manifesto-v0.json     # Word-level timecodes (ya generados con Whisper)
    │       └── commercial-v0.json
    └── [futuros proyectos]/
```

### Decisión de arquitectura: una sola Sheet + un solo endpoint para TODO el sitio

El `google_apps_script_endpoint` **no vive en la config de cada proyecto**, sino en un `config.json` global en la raíz de `Feedback web/`. Una única Sheet recibe los comentarios de todos los proyectos, disambiguados por la columna `project_id`. Esto evita:
- Duplicación del URL en N configs
- Tener que deployar un GAS nuevo por cada proyecto
- Fragmentación de datos (todos los feedbacks viven en el mismo lugar)

### `config.json` global (estructura)

```json
{
  "google_apps_script_endpoint": "https://script.google.com/macros/s/.../exec",
  "brand": {
    "name": "SideOutSticks",
    "short": "SOUTS",
    "tagline": "AI-powered content generation"
  }
}
```

### `projects/cend/config.json` (estructura)

```json
{
  "id": "cend",
  "name": "CEND",
  "client": "CEND",
  "branding": {
    "primary_color": "#000000"
  },
  "pieces": [
    {
      "id": "manifesto",
      "name": "Manifesto",
      "versions": [
        {
          "version": 0,
          "export_date": "2026-04-08 15:53",
          "youtube_id": "PENDING",
          "duration_seconds": 89.56,
          "transcript_file": "transcripts/manifesto-v0.json"
        }
      ]
    },
    {
      "id": "commercial",
      "name": "Commercial",
      "versions": [
        {
          "version": 0,
          "export_date": "2026-04-08 15:54",
          "youtube_id": "PENDING",
          "duration_seconds": 81.79,
          "transcript_file": "transcripts/commercial-v0.json"
        }
      ]
    }
  ]
}
```

---

## Flujo de uso

### Para Luca (cuando exporta una nueva versión)

Todo el proceso pesado está automatizado en `scripts/publish_version.py`:

1. Exporta la nueva versión desde Premiere a `Exports/[pieza]/` (cualquier nombre)
2. Corre un solo comando:
   ```bash
   python3 "Feedback web/scripts/publish_version.py" \
     --project cend --piece commercial \
     --file "Exports/Comercial/Comercial.mp4"
   ```
3. El script automáticamente:
   - Renombra el archivo siguiendo la convención (`CEND_[piece]_v[N]_[YYYYMMDD]_[HHMM].mp4`)
   - Copia a Drive y a local con el nombre correcto
   - Sube a YouTube como unlisted
   - **Elimina el video anterior de YouTube** (evita la acumulación)
   - Genera el transcript con Whisper
   - Actualiza `projects/cend/config.json` con el nuevo video_id
4. Commit + push manual (el script imprime los comandos exactos)
5. GitHub Pages se redepoya automáticamente → link listo para compartir

Ver `scripts/README.md` para el setup inicial de OAuth (una sola vez).

### Para el revisor
1. Abre el link → ve el branding del proyecto, el nombre de la pieza, la versión y la fecha
2. Lee la guía corta de instrucciones
3. Escribe su nombre en el campo "Reviewer name" (requerido para enviar)
4. Reproduce el video; cuando quiere comentar:
   - **Comment at this moment:** Pausa el video y hace click en "Add comment here". El timecode se captura automáticamente. El form muestra la frase del guión que corresponde a ese timecode como contexto.
   - **Comment on a range:** Click "Mark start" en un momento y "Mark end" en otro. El comentario queda anclado a un rango.
   - **General comment:** Click "General comment". Sin timecode.
5. En el formulario completa:
   - **Element:** Music / Dialogue / Sound / Video / Editing / Graphics
   - **Action:** Substitute / Improve / Modify
   - **Priority:** Must-fix / Nice-to-have / Suggestion
   - **Description:** Texto libre
6. El comentario aparece en el panel lateral. Puede editarlo o borrarlo.
7. Click en **"Submit feedback"**. Todos los comentarios se envían como un único POST al GAS endpoint, que los appendea al Sheet.
8. Recibe confirmación de envío.

### Para Claude (siguiente sesión)
1. Lee el Google Sheet del proyecto vía export CSV o vía API
2. Filtra por piece + version
3. Agrupa comentarios por elemento + tipo de acción
4. Genera lista de action items priorizada (must-fix primero)
5. Para cada action item, decide si es automatizable:
   - **Video → Substitute** + timecode → busca clip alternativo en inventario, lo coloca en V2
   - **Sound → Improve** → analiza con ffmpeg, propone fix
   - **Music → Substitute** → busca alternativa en bin Música
   - **Editing → Modify** → ajusta trimming/posición de clips existentes
   - **Graphics → Substitute** → reemplaza assets gráficos
6. Ejecuta lo automatizable, lista lo manual para Luca
7. Exporta nueva versión, sube a YouTube, actualiza config, ciclo se repite

---

## Estructura del Google Sheet

Una sola hoja con todas las columnas. Cada fila = un comentario.

| Columna | Tipo | Notas |
|---|---|---|
| timestamp | datetime | Fecha/hora de envío |
| project_id | string | "cend" |
| piece_id | string | "manifesto" / "commercial" |
| version | number | 0, 1, 2... |
| reviewer_name | string | El nombre que tipeó |
| comment_id | string | UUID local del navegador |
| timecode_start | number | Segundos. Vacío si es general comment |
| timecode_end | number | Segundos. Igual a start si es punto, distinto si es rango |
| transcript_excerpt | string | Frase del guión auto-generada para ese timecode |
| element | enum | Music / Dialogue / Sound / Video / Editing / Graphics |
| action | enum | Substitute / Improve / Modify |
| priority | enum | Must-fix / Nice-to-have / Suggestion |
| description | string | Texto libre del comentario |

---

## Decisiones de diseño y trade-offs

### Por qué YouTube unlisted y no Drive embed
- Drive iframe player **no expone eventos de playback** vía JavaScript. No podemos leer `currentTime` ni hacer `seekTo`. Eso elimina la posibilidad de timecode-anchoring automático, que es el corazón del sistema.
- YouTube IFrame API es la única opción gratuita con API completa.
- Trade-off: hay que subir manualmente cada export a YouTube. Es un click, aceptable.

### Por qué Google Apps Script y no email/Formspree
- GAS es completamente gratis y sin límites de submissions.
- Estructura los datos en filas de Sheet inmediatamente, listas para que Claude las lea.
- No hay servicio de terceros que pueda fallar o cambiar pricing.
- Único costo: el deploy inicial (5 clicks una vez por proyecto).

### Por qué multi-proyecto desde el inicio
- El refactor posterior es más caro que diseñarlo bien desde el principio.
- El overhead actual es mínimo: una carpeta más con config.json.
- Próximos proyectos cobran el beneficio sin pagar el costo.

### Por qué free text name y no autenticación
- Trust-based: las personas que reciben el link son personas de confianza del proyecto.
- Cualquier sistema de auth (Google login, magic link) agrega fricción que no se justifica para esta escala.

---

## Plan de implementación (orden)

### Fase A — Estructura base (esta sesión)
1. Crear estructura de carpetas en `Feedback web/`
2. Escribir este documento (Planificación.md)
3. Crear todas las páginas HTML
4. Crear estilos CSS
5. Crear módulos JS
6. Crear código GAS + instrucciones
7. Crear config.json del proyecto CEND
8. Copiar transcripts existentes al formato del repo
9. Crear README con instrucciones de deploy
10. Actualizar Bitácora del proyecto y Workflow

### Fase B — Deploy (próxima sesión, requiere acción de Luca)
1. Luca crea el repo en GitHub y sube el contenido de `Feedback web/`
2. Habilita GitHub Pages en la rama main
3. Sigue los pasos del README para deployar el GAS endpoint
4. Pega el endpoint URL en `config.json`
5. Sube los exports actuales (v0) a YouTube unlisted y pega los video IDs
6. Push → GitHub Pages publica

### Fase C — Verificación end-to-end
1. Abrir el link público desde otro navegador (modo incógnito)
2. Dejar comentarios de prueba de cada tipo
3. Submit
4. Verificar que aparezcan en el Sheet
5. Claude lee el Sheet y demuestra que puede generar action items

---

## Limitaciones conocidas

- **YouTube quota:** 10.000 unidades/día default. Un upload cuesta ~1.600, un delete ~50. Alcanza para ~6 uploads/día.
- **Sin autenticación:** Cualquiera con el link puede comentar. Aceptado por simplicidad y trust-based.
- **Sin live collaboration:** Si dos revisores comentan en paralelo, ambos verán solo sus propios comentarios pendientes hasta enviarlos. El Sheet acumula todos al final.
- **Sin notificaciones push:** Cuando llega feedback, hay que abrir el Sheet manualmente o pedirle a Claude que lo lea. Se podría agregar luego con un trigger en GAS.
- **Sin reproducción offline:** Si no hay internet, el revisor no puede comentar.

---

## Reutilización de código existente

- **Timecodes JSON:** Los archivos `Assets/Audio/Voz/Manifiesto/timecodes_manifiesto.json` y `Assets/Audio/Voz/Comercial/timecodes_comercial_v2.json` ya están en el formato exacto que `transcript.js` necesita (`[{word, start, end}]`). Solo se copian al repo.
- **Pipeline de Whisper:** El comando para regenerar timecodes en futuras versiones ya está documentado en `Documentación/Workflow y herramientas.md`.

---

*Documento vivo. Actualizar con cada cambio significativo del sistema.*
