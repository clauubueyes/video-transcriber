# Video Transcriber

Servicio local para obtener transcripciones de vídeos de YouTube o de archivos
de audio y vídeo. Primero intenta aprovechar los subtítulos disponibles; si no
los hay, usa un modelo local compatible con `faster-whisper`.

Incluye una interfaz web en `http://127.0.0.1:8000/`, una API FastAPI, trabajos
asíncronos guardados en SQLite y un worker opcional. No utiliza APIs de IA
remotas ni descarga modelos de Whisper automáticamente.

## Requisitos

- Python 3.11 o posterior.
- Deno (recomendado) o Node.js 22 o posterior disponible en el `PATH` para
  resolver los desafíos JavaScript de YouTube. El servicio habilita ambos;
  el contenedor Docker ya incluye Deno.
- `ffmpeg` disponible en el `PATH` para procesar audio y vídeo con Whisper.
- Un modelo CTranslate2 compatible con `faster-whisper` si se van a transcribir
  vídeos sin subtítulos o archivos subidos.
- Docker Desktop es opcional; puede usarse en lugar de Python local.

## Puesta en marcha local

Desde la raíz del repositorio, crea el entorno, instala las dependencias y
copia la configuración de ejemplo:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Edita `.env` antes de iniciar el servicio. Como mínimo, cambia el token:

```env
VIDEO_TRANSCRIBER_TOKEN=un-secreto-local-largo
```

Inicia la API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Después abre:

- `http://127.0.0.1:8000/` — interfaz web.
- `http://127.0.0.1:8000/docs` — documentación interactiva de la API.
- `http://127.0.0.1:8000/health` — confirma que el proceso HTTP está activo.
- `http://127.0.0.1:8000/ready` — confirma que SQLite está disponible.

La interfaz web pública no solicita token. Las rutas bajo
`/v1/transcriptions` sí requieren `Authorization: Bearer <token>`.

## Configuración

`.env.example` contiene todos los valores disponibles. Los más habituales son:

| Variable | Uso | Valor predeterminado |
| --- | --- | --- |
| `VIDEO_TRANSCRIBER_TOKEN` | Token requerido por la API privada. | Sin valor; obligatorio |
| `VIDEO_TRANSCRIBER_ALLOWED_DOMAINS` | Dominios permitidos al importar URLs. | Dominios de YouTube |
| `VIDEO_TRANSCRIBER_MAX_DURATION_SECONDS` | Duración máxima para vídeos remotos. | `1800` |
| `VIDEO_TRANSCRIBER_MODEL_PATH` | Ruta al modelo Whisper local. | `models/whisper-small` |
| `VIDEO_TRANSCRIBER_WHISPER_DEVICE` | Dispositivo de inferencia. | `cpu` |
| `VIDEO_TRANSCRIBER_WHISPER_COMPUTE_TYPE` | Tipo de cómputo de Whisper. | `int8` |
| `VIDEO_TRANSCRIBER_PROCESS_JOBS_IN_API` | Procesa la cola dentro de la API. | `true` |
| `VIDEO_TRANSCRIBER_MAX_UPLOAD_BYTES` | Tamaño máximo de archivos subidos. | `500000000` |

Para usar Whisper, coloca un modelo ya convertido en la ruta indicada o cambia
`VIDEO_TRANSCRIBER_MODEL_PATH`. Los directorios `models/`, `data/` y `tmp/` son
locales y están excluidos de Git, al igual que `.env`.

## Uso de la API

### Crear una transcripción desde una URL

```powershell
$headers = @{
  Authorization = "Bearer un-secreto-local-largo"
  "Content-Type" = "application/json"
}

$job = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/v1/transcriptions" `
  -Headers $headers `
  -Body '{"source":{"type":"url","url":"https://youtu.be/VIDEO_ID"},"language":"es"}'

$job
```

La respuesta tiene estado `queued`. Consulta el trabajo hasta que alcance
`completed`, `failed` o `expired`:

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/v1/transcriptions/$($job.id)" `
  -Headers $headers
```

Para borrar un trabajo y su resultado:

```powershell
Invoke-RestMethod -Method Delete `
  -Uri "http://127.0.0.1:8000/v1/transcriptions/$($job.id)" `
  -Headers $headers
```

### Subir un archivo

Se aceptan `aac`, `flac`, `m4a`, `mp3`, `mp4`, `ogg`, `opus`, `wav` y `webm`.
La subida se conserva solo mientras se procesa el trabajo.

```powershell
$headers = @{ Authorization = "Bearer un-secreto-local-largo" }

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/v1/transcriptions/upload" `
  -Headers $headers `
  -Form @{ file = Get-Item "C:\ruta\a\archivo.webm"; language = "es" }
```

En PowerShell 5.1, que no admite `-Form`, puede usarse `curl.exe -F` con la
misma cabecera de autorización.

## Worker separado

Por defecto, la API procesa los trabajos en segundo plano. Para ejecutar el
procesamiento en otro proceso, cambia esta variable en `.env`:

```env
VIDEO_TRANSCRIBER_PROCESS_JOBS_IN_API=false
```

Y arranca un worker desde otra terminal:

```powershell
.\.venv\Scripts\python.exe -m app.workers.cli
```

Para ejecutar una única pasada de la cola, añade `--once`. API y worker deben
compartir `.env`, `data/` y `tmp/`.

## Docker local

Con Docker Desktop instalado y `.env` configurado:

```powershell
docker compose up --build
```

Los datos SQLite, temporales y modelos se montan en `data/`, `tmp/` y
`models/`, respectivamente. Si se usa worker separado, establece
`VIDEO_TRANSCRIBER_PROCESS_JOBS_IN_API=false` y ejecuta:

```powershell
docker compose --profile worker up --build
```

## Prueba en Render Free

Para alojar la web y la API juntas con transcripción mediante Groq, utiliza
el Blueprint `render.yaml` y sigue [docs/render.md](docs/render.md).
En este plan los trabajos y resultados son temporales: se pierden cuando
Render suspende o reinicia el servicio.

## Publicación en Vercel

La interfaz puede alojarse en Vercel y conectarse a un backend HTTPS con disco
persistente. Sigue [docs/vercel.md](docs/vercel.md) para configurar el proyecto,
la URL del backend y CORS.

## Desarrollo

Ejecuta las comprobaciones antes de abrir un cambio:

```powershell
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m pytest -q
```

La guía ampliada de comportamiento local está en
[docs/uso-local.md](docs/uso-local.md). El plan histórico de implementación se
conserva en [docs/plan-implementacion.md](docs/plan-implementacion.md).

## Privacidad y límites

- Los resultados caducan según `VIDEO_TRANSCRIBER_RESULT_TTL_SECONDS`.
- Las URLs se validan contra los dominios permitidos y se bloquean destinos de
  red privada para evitar SSRF.
- El servicio limita duración, tamaño de subida, concurrencia y trabajos por
  token.
- Los logs no incluyen tokens, URLs de origen, audio ni texto transcrito.
