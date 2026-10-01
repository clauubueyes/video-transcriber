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

## Procesamiento

1. El servicio consulta la duración sin descargar contenido y rechaza vídeos
   sin duración conocida o que superen el límite configurado.
2. Intenta descargar subtítulos VTT. El texto se normaliza para corregir
   codificación errónea y solapamientos comunes de YouTube Live.
3. Si no hay subtítulos útiles, descarga solo audio temporal y lo transcribe
   con el modelo local de `faster-whisper`.
4. Los resultados se guardan temporalmente en SQLite. Al vencer su TTL pasan a
   `expired` y se elimina texto, segmentos y duración.

El valor `VIDEO_TRANSCRIBER_MAX_CONCURRENT_JOBS` limita procesamientos locales
simultáneos para no saturar CPU o GPU.

## Worker separado

La API procesa la cola localmente por defecto. Para usar un proceso independiente
con la misma base SQLite, detén la API o evita crear trabajos mientras verificas
la configuración y ejecuta una pasada:

```powershell
.\.venv\Scripts\python.exe -m app.workers.cli --once
```

Para un worker permanente, ejecútalo sin `--once`; un supervisor de procesos
debe encargarse de reiniciarlo si se detiene:

```powershell
.\.venv\Scripts\python.exe -m app.workers.cli
```

## Logs y privacidad

Los logs son JSON y solo contienen evento, ID de trabajo, estado y duración.
No incluyen tokens, URL de origen, audio ni texto transcrito.

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m pytest -q
```
