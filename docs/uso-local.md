# Uso local

## Requisitos

- Python 3.11 o posterior.
- Un entorno virtual con las dependencias del proyecto.
- `yt-dlp` se instala como dependencia y accede únicamente a la URL de YouTube
  solicitada.
- Para vídeos sin subtítulos, un modelo CTranslate2 compatible con
  `faster-whisper` ya instalado en disco. El servicio no descarga modelos de
  Whisper automáticamente.

## Arranque

Desde la raíz del repositorio:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Edita `.env` y sustituye el token de ejemplo por un valor propio. No compartas
ni versiones este archivo.

```env
VIDEO_TRANSCRIBER_TOKEN=un-secreto-local-largo
VIDEO_TRANSCRIBER_MAX_DURATION_SECONDS=1800
VIDEO_TRANSCRIBER_MAX_CONCURRENT_JOBS=1
VIDEO_TRANSCRIBER_MAX_JOBS_PER_TOKEN=10
VIDEO_TRANSCRIBER_RATE_LIMIT_WINDOW_SECONDS=3600
VIDEO_TRANSCRIBER_ORPHAN_UPLOAD_AGE_SECONDS=3600
VIDEO_TRANSCRIBER_STALE_JOB_TIMEOUT_SECONDS=7200
VIDEO_TRANSCRIBER_MODEL_PATH=models/whisper-small
```

Inicia la API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Comprueba el estado en `http://127.0.0.1:8000/health` y explora la API en
`http://127.0.0.1:8000/docs`.

## Docker Compose

Con Docker instalado, crea `.env` como en el apartado anterior y ejecuta:

```powershell
docker compose up --build
```

La base SQLite se conserva en `data/`; los modelos locales se montan de solo
lectura desde `models/`. Para usar Whisper sin subtítulos, coloca el modelo en
`models/whisper-small` o ajusta `VIDEO_TRANSCRIBER_MODEL_PATH` a una ruta bajo
ese volumen.

Para usar el worker separado con Docker, configura la API para que solo encole
trabajos y arranca ambos servicios:

```env
VIDEO_TRANSCRIBER_PROCESS_JOBS_IN_API=false
```

```powershell
docker compose --profile worker up --build
```

## Crear y consultar un trabajo

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

Consulta el trabajo hasta que alcance `completed`, `failed` o `expired`:

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/v1/transcriptions/$($job.id)" `
  -Headers $headers
```

Para cancelar o eliminar un trabajo:

```powershell
Invoke-RestMethod -Method Delete `
  -Uri "http://127.0.0.1:8000/v1/transcriptions/$($job.id)" `
  -Headers $headers
```

## Subir un archivo local

La alternativa a una URL es subir explícitamente un archivo de audio o vídeo.
La API acepta `aac`, `flac`, `m4a`, `mp3`, `mp4`, `ogg`, `opus`, `wav` y `webm`.
El límite se configura mediante `VIDEO_TRANSCRIBER_MAX_UPLOAD_BYTES` (500 MB
por defecto). El archivo se guarda solo de forma temporal, se procesa con
Whisper local y se borra al acabar o al cancelar el trabajo.

```powershell
$headers = @{ Authorization = "Bearer un-secreto-local-largo" }

$job = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/v1/transcriptions/upload" `
  -Headers $headers `
  -Form @{ file = Get-Item "C:\ruta\a\audio-o-video.webm"; language = "es" }

$job
```

Consulta y, si es necesario, cancela el trabajo con las mismas rutas `GET` y
`DELETE` mostradas en el apartado anterior. En PowerShell 5.1, que no dispone
de `-Form`, usa `curl.exe -F "file=@C:\ruta\a\archivo.webm" -F "language=es"`
y la cabecera `Authorization: Bearer ...`.

## Procesamiento

1. El servicio consulta la duración sin descargar contenido y rechaza vídeos
   sin duración conocida o que superen el límite configurado.
2. Intenta descargar subtítulos VTT. El texto se normaliza para corregir
   codificación errónea y solapamientos comunes de YouTube Live.
3. Si no hay subtítulos útiles, descarga solo audio temporal y lo transcribe
   con el modelo local de `faster-whisper`.
4. Los resultados se guardan temporalmente en SQLite. Al vencer su TTL pasan a
   `expired` y se elimina texto, segmentos y duración.

Para archivos subidos, no se usa `yt-dlp`: Whisper recibe el fichero temporal
directamente. Ningún paso de este flujo llama a OpenAI, Gemini ni otro proveedor
de IA remoto.

El valor `VIDEO_TRANSCRIBER_MAX_CONCURRENT_JOBS` limita procesamientos locales
simultáneos para no saturar CPU o GPU.

`VIDEO_TRANSCRIBER_MAX_JOBS_PER_TOKEN` limita cuántos trabajos puede crear un
token durante `VIDEO_TRANSCRIBER_RATE_LIMIT_WINDOW_SECONDS`. Si se supera, la
API devuelve `429 Too Many Requests` junto con la cabecera `Retry-After`.

## Worker separado

La API procesa la cola localmente por defecto. Para usar un proceso independiente
con la misma base SQLite, establece lo siguiente en `.env` y reinicia la API:

```env
VIDEO_TRANSCRIBER_PROCESS_JOBS_IN_API=false
```

Después ejecuta una pasada:

```powershell
.\.venv\Scripts\python.exe -m app.workers.cli --once
```

Para un worker permanente, ejecútalo sin `--once`; un supervisor de procesos
debe encargarse de reiniciarlo si se detiene:

```powershell
.\.venv\Scripts\python.exe -m app.workers.cli
```

La API y el worker deben usar el mismo `VIDEO_TRANSCRIBER_TEMPORARY_DIRECTORY`;
es imprescindible para que el worker pueda leer una subida que recibió la API.

Al arrancar, el worker también limpia archivos temporales `upload-*` que ya no
estén referenciados por ningún trabajo SQLite y que tengan al menos la antigüedad
indicada por `VIDEO_TRANSCRIBER_ORPHAN_UPLOAD_AGE_SECONDS` (una hora por
defecto). Este margen evita interferir con subidas en curso; los archivos de
trabajos pendientes no se borran. Si el servicio se interrumpió durante una
subida, reinicia el worker para que pueda recuperar ese espacio cuando venza el
periodo configurado.

Si el proceso se interrumpe mientras descarga o transcribe, el worker vuelve a
encolar esos trabajos cuando llevan más de
`VIDEO_TRANSCRIBER_STALE_JOB_TIMEOUT_SECONDS` sin actualizarse (dos horas por
defecto). Ajusta ese valor por encima del tiempo máximo real de procesamiento
de tus vídeos para evitar repetir un trabajo todavía activo.

En cada pasada, el worker también caduca los resultados cuyo TTL haya vencido,
sin esperar a que un cliente vuelva a consultar el trabajo.

## Logs y privacidad

Los logs son JSON y solo contienen evento, ID de trabajo, estado y duración.
No incluyen tokens, URL de origen, audio ni texto transcrito.

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m pytest -q
```
