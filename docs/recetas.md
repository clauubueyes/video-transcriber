# Extracción automática de recetas

Esta función convierte el texto de un trabajo completado en una receta
estructurada para Abuelas Kitchen. Es independiente de la transcripción: se
pueden seguir obteniendo subtítulos o usando Whisper local sin extraer recetas.

## Configuración

La API de recetas usa Groq y reutiliza la clave de audio si está configurada.
Puedes proporcionar una clave diferente, que tendrá prioridad:

```env
VIDEO_TRANSCRIBER_RECIPE_API_KEY=gsk_clave_privada
VIDEO_TRANSCRIBER_RECIPE_MODEL=openai/gpt-oss-20b
VIDEO_TRANSCRIBER_RECIPE_EXTRACTION_ENABLED=true
VIDEO_TRANSCRIBER_RECIPE_TIMEOUT_SECONDS=90
VIDEO_TRANSCRIBER_RECIPE_MAX_TRANSCRIPT_CHARS=120000
VIDEO_TRANSCRIBER_RECIPE_JOBS_PER_HOUR=30
```

Si falta `VIDEO_TRANSCRIBER_RECIPE_API_KEY`, se usa
`VIDEO_TRANSCRIBER_GROQ_API_KEY`. No pongas claves en variables públicas `VITE_`.
El modelo de texto es diferente de `VIDEO_TRANSCRIBER_GROQ_MODEL`, que selecciona
Whisper para audio. El modelo de recetas debe admitir
[JSON Schema estricto en Groq](https://console.groq.com/docs/structured-outputs).
No se necesitan paquetes nuevos. Reinicia la API si cambias su `.env`.

## API pública protegida por trabajo

Después de crear y completar un trabajo de `/web/jobs` o `/web/jobs/upload`:

```powershell
$headers = @{ "X-Job-Key" = $accessKey }
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/web/jobs/$jobId/recipe" `
  -Headers $headers
```

La solicitud no tiene cuerpo. El servidor obtiene el texto del trabajo
autorizado y devuelve:

```json
{
  "recipeFound": true,
  "title": "Tortilla de patatas",
  "description": "Tortilla con patatas y huevos.",
  "ingredients": [{ "item": "Patatas", "amount": "500 g" }],
  "steps": [{ "order": 1, "instruction": "Pelar y freír las patatas." }],
  "tags": ["Plato Principal"],
  "prepTimeMinutes": null,
  "servings": null,
  "notes": ["La transcripción no especifica las raciones."]
}
```

Las cantidades no especificadas son `""`; tiempos totales y raciones ausentes
son `null`. La duración del vídeo no se usa como tiempo de preparación. Los
pasos se redactan desde las acciones culinarias y no desde los capítulos.
Si no se identifica una receta, `recipeFound` es `false`, las listas están
vacías y `notes` explica el motivo. Abuelas Kitchen ofrece edición manual.

Una clave ausente o incorrecta devuelve `404`. Un trabajo pendiente o caducado
devuelve `409`. Una transcripción demasiado larga devuelve `422`. Si no hay
clave de Groq configurada, se devuelve `503`. Los fallos del proveedor son
mensajes seguros: no contienen claves ni el texto original. La transcripción
se conserva para reintentar o usarla manualmente.

## Recuperación, cuota y privacidad

La receta se guarda en SQLite junto al trabajo, con una migración automática
compatible con bases existentes. Repetir la solicitud recupera la receta
guardada sin llamar otra vez al modelo. No se añade tiempo de vida al resultado:
al caducar se elimina también el JSON de la receta y al borrar el trabajo
desaparece con él. Las recetas guardadas en Abuelas Kitchen se conservan en su
almacenamiento local y en sus copias de seguridad.

El servidor limita las nuevas extracciones a 30 por hora y a una llamada
simultánea al modelo por proceso. Las extracciones en caché no gastan esa cuota.
Los límites en memoria, como los de la transcripción, requieren una sola API
para representar una cuota compartida. El proveedor aplica además su propia
cuota y límites; se utiliza su API de texto sin prometer gratuidad ilimitada.

El texto se envía a Groq únicamente al solicitar la extracción. No se vuelve a
enviar audio ni vídeo, no se guarda la clave en la receta y las respuestas usan
`Cache-Control: no-store`. La transcripción es material de referencia: el prompt
indica al modelo que ignore instrucciones dentro de ese texto.

Revisa ingredientes, cantidades y pasos antes de guardar. La validación de
estructura no garantiza que el modelo haya interpretado correctamente el audio.
