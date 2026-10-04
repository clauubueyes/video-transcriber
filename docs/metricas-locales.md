# Métricas locales y pruebas de rendimiento

El servicio registra el tiempo de procesamiento de cada trabajo completado en
SQLite. Se empieza a medir cuando el worker reclama el trabajo y se termina
cuando el procesador devuelve el resultado. Incluye descarga, preparación,
carga del modelo e inferencia cuando corresponda; excluye espera en cola,
recepción de la subida, validación previa y escritura final del resultado.

## Métricas durante el uso habitual

Las respuestas de `/v1/transcriptions/{id}` y `/web/jobs/{id}` añaden:

| Campo | Significado |
| --- | --- |
| `processingSeconds` | Tiempo de procesamiento, en segundos. |
| `processingMethod` | `subtitles`, `whisper_local` o `groq`. |
| `processingSpeed` | Duración del audio dividida entre tiempo de procesamiento. Un valor de 10 equivale a diez segundos de audio por segundo de procesamiento. |

La interfaz muestra «Procesado en … s» junto a la duración del resultado.
Los logs JSON también incluyen estos campos, con nombres en `snake_case`.

`processingSpeed` es una relación con la duración del audio; no es una mejora
respecto a otra versión. En el flujo habitual, algunos adaptadores estiman
la duración mediante el último segmento con texto, por lo que los silencios
finales pueden afectar la cifra. Para publicar resultados, utiliza el comando
de prueba descrito abajo: obtiene la duración completa con FFprobe.

Para consultar los agregados desde PowerShell:

```powershell
$headers = @{ Authorization = "Bearer <tu-token-local>" }
Invoke-RestMethod -Uri "http://127.0.0.1:8000/v1/transcriptions/metrics" -Headers $headers |
  ConvertTo-Json -Depth 5
```

`performanceByMethod` separa los trabajos por método. Cada grupo contiene:

- `completedJobs`: trabajos completados que siguen conservados.
- `measuredJobs`: trabajos que tienen un tiempo de procesamiento registrado.
- `averageProcessingSeconds`: media de esos tiempos, sin sustituir datos
  ausentes por cero.
- `processingSpeed`: suma de duraciones dividida entre suma de tiempos, usando
  únicamente los trabajos con duración y tiempo positivos. No promedia ratios
  individuales, que darían más peso a trabajos muy cortos.

Las bases existentes se migran automáticamente al arrancar el servicio. Los
trabajos anteriores pueden tener método y tiempos nulos; no se reconstruyen
mediciones a partir de sus fechas. Si no se conoce el método, el grupo tiene
`method: null`. La velocidad es nula si no se puede calcular.

Los conteos reflejan trabajos actualmente guardados, no un histórico acumulado.
Al caducar un resultado se borran también sus métricas de rendimiento; al
eliminarlo deja de contar. La ruta de agregados requiere el token de servicio
y no devuelve URLs, nombres de archivos, claves ni texto transcrito.

## Prueba repetible con un archivo real

El comando crea su propio transcriptor y procesa directamente un archivo.
No necesita iniciar la API, no modifica la cola ni elimina el archivo original.
Por defecto usa Whisper local, incluso si `.env` contiene una clave de Groq.

Necesitas un modelo local compatible con faster-whisper y FFprobe en `PATH`.
El modelo se indica con `VIDEO_TRANSCRIBER_MODEL_PATH` o `--model-path`.
Los ajustes de CPU, dispositivo, tipo de cómputo y búsqueda se leen de `.env`.

Para añadir la medición opcional de memoria, instala el extra `benchmark`:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,benchmark]"
.\.venv\Scripts\python.exe -m app.benchmark "C:\ruta\audio.wav" --runs 3 --language es --output data/benchmarks/audio-local.json
```

El informe JSON contiene la duración completa del archivo, su tamaño, modelo,
proveedor, ajustes locales, sistema operativo, CPU y resultados por intento.
No guarda la transcripción, contenido del audio, ruta del archivo, tokens ni
claves. Si la carpeta del modelo tiene un nombre personalizado, ese nombre
aparecerá en `model`; revisa los metadatos antes de compartir el informe.

Se conserva cada intento, incluidos los fallidos, y se devuelve código 1 si
alguno falla. `summary` calcula medianas sobre los intentos completados;
los fallos siguen contando en `attempts`, `failed` y `success_rate`. La tasa
de éxito mide finalización, no precisión de las palabras transcritas.

La primera ejecución queda registrada en `runs[0]` e incluye la carga del
modelo local. `subsequent_runs_summary` resume las siguientes, reutilizando
el mismo transcriptor. Con una única ejecución ese resumen está vacío. Si
falla la carga del modelo, otro intento puede volver a cargarlo; no presupongas
que todos los intentos posteriores tienen el modelo ya cargado.

`peak_rss_bytes` y `max_sampled_rss_bytes` son máximos muestreados de la suma
de RSS del proceso y sus descendientes cada 50 ms, incluida la memoria ya
ocupada al iniciar el intento. No representan memoria adicional por trabajo:
pueden sumar páginas compartidas y perder picos más cortos que el intervalo.
No miden VRAM ni memoria del proveedor remoto. Si `psutil` no está instalado,
las cifras de memoria quedan nulas y la medición de tiempo sigue funcionando.

Para medir explícitamente Groq con la clave de `.env`:

```powershell
.\.venv\Scripts\python.exe -m app.benchmark "C:\ruta\audio.wav" --provider groq --runs 3 --language es --output data/benchmarks/audio-groq.json
```

Este modo envía el archivo a Groq y consume cuota en cada intento. Su tiempo
incluye preparación y red, pero no descarga de YouTube, subida a esta API ni
cola. La memoria corresponde al proceso local de la prueba.

## Qué publicar en LinkedIn

Prueba archivos de 5, 15 y 30 minutos, con el mismo idioma y configuración,
y guarda un informe independiente para cada caso. Mantén el equipo sin otras
cargas intensivas. Identifica siempre proveedor, modelo, equipo, número de
intentos y si incluyes la primera ejecución.

Una frase para completar con los resultados reales:

> En mi equipo, un audio de [X] minutos se procesó en [Y] segundos con
> [modelo/proveedor]. Mediana de [N] intentos completados, [incluyendo o
> excluyendo] la primera ejecución. Completados: [N] de [total de intentos].

Para una cifra de «antes y después», ejecuta ambas versiones con el mismo
archivo, modelo, configuración y condiciones. La reducción de tiempo es
`(tiempo_anterior - tiempo_nuevo) / tiempo_anterior * 100`. Recuperar subtítulos
y transcribir audio son operaciones distintas: publica sus tiempos por
separado. Conserva el informe original para respaldar la cifra.
