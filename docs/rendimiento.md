# Rendimiento y duración máxima

El límite para vídeos remotos pasa de 10 minutos a una hora en `render.yaml`
y de 30 minutos a una hora en la configuración local por defecto. Este límite
se comprueba antes de encolar URLs. Las subidas conservan su límite por bytes;
no tienen una comprobación previa de duración. En Render siguen siendo 25 MB.

## Problemas encontrados y cambios

| Problema | Cambio | Efecto |
| --- | --- | --- |
| Groq leía el archivo entero y lo concatenaba al cuerpo HTTP. | Multipart iterable con `Content-Length` y lecturas de 64 KB. | Evita varias copias completas en RAM. |
| Una hora de audio puede superar el máximo por solicitud de Groq. | Archivos grandes y vídeo se extraen como FLAC mono 16 kHz, por fragmentos secuenciales. | Cada solicitud queda por debajo de 25 MB; no se carga el vídeo en RAM. |
| API y archivos locales construían transcriptores independientes. | Ambos comparten una instancia de Whisper. | Evita cargar dos modelos cuando se usan URLs y subidas. |
| Solicitudes simultáneas podían construir varios runners. | Inicialización protegida por un bloqueo por aplicación. | Conserva un único semáforo de concurrencia por proceso. |
| La cola podía crecer pese al límite de trabajos simultáneos. | Máximo de trabajos pendientes y activos, comprobado dentro de una transacción SQLite. | Rechaza trabajo nuevo con 503 sin saturar la cola. |
| Whisper local no exponía sus ajustes de rendimiento. | Hilos de CPU y tamaño de búsqueda configurables. | Permite ajustar consumo y velocidad al hardware. |

Los subtítulos de YouTube ya eran la primera opción y se mantienen: cuando
están disponibles no hace falta inferencia. La inferencia remota sigue usando
`whisper-large-v3-turbo`; no se aumenta la concurrencia en Render.

## Segundo ajuste de velocidad

| Paso anterior | Paso actual | Límite de recursos |
| --- | --- | --- |
| Hasta tres extracciones de metadatos para duración, subtítulos y audio. | Una extracción compartida cuando los metadatos siguen vigentes. | Caché por proceso de 4 MB de JSON, 16 entradas y cinco minutos de vida. |
| Se iniciaba yt-dlp para buscar subtítulos incluso si ya se sabía que no existían. | Se pasa directamente al audio cuando los metadatos descartan el idioma solicitado. | Mantiene la prioridad de subtítulos disponibles. |
| Se convertían todos los MP4 y WebM, incluidos los pequeños. | Se envían directamente los formatos compatibles de menos de 20 MB. | El cuerpo HTTP mantiene lecturas de 64 KB. |
| Preparación y transcripción de fragmentos una después de otra. | Se prepara el siguiente mientras Groq procesa el actual. | Un encoder, una solicitud a Groq y hasta dos archivos temporales por trabajo. |

La caché conserva copias independientes para que yt-dlp no modifique los
metadatos de otro trabajo. Si un enlace temporal falla, se invalida y se vuelve
a extraer una vez; un error 429 no genera otra solicitud. Las extracciones
nuevas se serializan por proceso y las peticiones simultáneas al mismo vídeo
comparten el resultado. Una cola que tarde más de cinco minutos puede necesitar
una extracción nueva al procesar el trabajo. La caché no se comparte entre la
API y un worker que corran en procesos separados.

Estas optimizaciones se activan con el código actualizado y no requieren
variables de entorno adicionales. El límite de una hora y la concurrencia de
un trabajo se conservan. El envío directo evita la conversión local, aunque
puede enviar más bytes que una versión FLAC reducida del mismo archivo.

## Medición local

Con un archivo sintético de **12.000.000 bytes**, `tracemalloc` midió el pico de
asignaciones de Python durante la construcción y consumo del cuerpo HTTP:

| Versión | Pico de memoria |
| --- | ---: |
| Código anterior | 36.002.417 bytes |
| Envío por bloques | 202.311 bytes |

La reducción en esta operación es de aproximadamente **99,4 %**. La respuesta
del proveedor se simuló y no se enviaron datos externos. Esto no mide la RAM
total del proceso, FFmpeg, yt-dlp, Node, la red ni el tiempo de inferencia.
No hay todavía un porcentaje de aceleración medido en Render.

La segunda revisión comparó la versión anterior y actual con esperas
controladas, sin hacer llamadas externas. Mediana de tres ejecuciones para
seis fragmentos, simulando 50 ms de preparación y 80 ms de proveedor por
fragmento:

| Operación simulada | Antes | Ahora |
| --- | ---: | ---: |
| Seis fragmentos | 789,1 ms | 536,3 ms |
| Tres pasos con extracción de metadatos de 60 ms | 181,0 ms; tres extracciones | 60,7 ms; una extracción |

El flujo de fragmentos redujo su tiempo aproximadamente un **32 % en esta
simulación**. Las esperas son artificiales: este dato valida el solapamiento
de etapas y no predice la aceleración en Render o en una llamada real a Groq.

Los logs `job_completed` incluyen `processing_seconds` junto a la duración del
audio. Para medir velocidad real, compara el mismo vídeo y el mismo idioma
antes y después, separando los resultados que aprovechan subtítulos de los que
transcriben audio. Prueba primero un vídeo corto y luego uno de 45–60 minutos,
observando también la memoria de Render y la disponibilidad de `/ready`.

Los tiempos también se guardan en SQLite y los agregados de
`/v1/transcriptions/metrics` separan subtítulos, Whisper local y Groq.
La guía [metricas-locales.md](metricas-locales.md) incluye el comando
`python -m app.benchmark` para medir archivos reales y guardar informes.

## Configuración

Perfil para Render con Groq:

```env
VIDEO_TRANSCRIBER_MAX_DURATION_SECONDS=3600
VIDEO_TRANSCRIBER_MAX_CONCURRENT_JOBS=1
VIDEO_TRANSCRIBER_MAX_PENDING_JOBS=5
VIDEO_TRANSCRIBER_GROQ_CHUNK_SECONDS=600
VIDEO_TRANSCRIBER_GROQ_TIMEOUT_SECONDS=120
```

`MAX_PENDING_JOBS` cuenta también el trabajo en curso: cinco equivale, con
concurrencia uno, a un máximo de cuatro esperando y uno procesándose. Limita
los trabajos, no el total de bytes almacenados. El multipart de entrada ya se
ha recibido cuando la ruta comprueba capacidad; esta protección evita la copia
adicional al almacén propio y el registro de trabajo, pero no sustituye un
límite de cuerpo HTTP en el proxy si se necesitan subidas grandes.

Para otro límite de duración, cambia `MAX_DURATION_SECONDS`; por ejemplo,
`7200` para dos horas. No cambies `MAX_CONCURRENT_JOBS` para ampliar duración.
Las cuotas públicas e individuales siguen siendo independientes. Los límites
de uso de Groq se consultan en su consola: el fraccionamiento no los amplía.

En un servicio Render existente, actualiza sus variables **Environment** y
vuelve a desplegar el código. `render.yaml` prepara nuevos despliegues; cambiar
solo `.env.example` o el `.env` local no actualiza el servidor publicado.

Para Whisper local:

```env
VIDEO_TRANSCRIBER_WHISPER_DEVICE=cpu
VIDEO_TRANSCRIBER_WHISPER_COMPUTE_TYPE=int8
VIDEO_TRANSCRIBER_WHISPER_CPU_THREADS=2
VIDEO_TRANSCRIBER_WHISPER_BEAM_SIZE=5
```

`BEAM_SIZE=1` permite una búsqueda más rápida, con posible pérdida de precisión.
El valor por defecto conserva 5. Ajusta los hilos a las CPU disponibles;
mantén margen para la API. Esta configuración no afecta a Groq.
Seleccionar el idioma conocido evita trabajo de detección.

## Límites prácticos y validación

FFmpeg y FFprobe están incluidos en Docker. Para ejecución local con Groq,
instálalos y asegúrate de que ambos estén en `PATH` antes de procesar vídeos
o archivos grandes. El entorno de esta revisión no tenía esos ejecutables:
se verificaron los comandos y el ensamblado mediante adaptadores simulados,
y el envío multipart con una conexión HTTP local real. También se ejecutó
yt-dlp real contra un servidor HTTP local para verificar que los metadatos
reutilizados seleccionan y descargan únicamente audio o los subtítulos
solicitados. No se ejecutó inferencia real ni una prueba de carga en Render.

Cada fragmento se elimina tras su transcripción; como máximo se prepara uno
adicional durante la espera del proveedor. Los dos temporales se eliminan
también si falla la conversión o la solicitud. Se añade un
segundo de contexto por borde; los segmentos se asignan al fragmento que
contiene su punto medio y las marcas de tiempo se recortan a ese intervalo.
Las fronteras pueden afectar algunas palabras: revisa el texto si necesitas
exactitud. Una cuota 429 o fallo de un fragmento hace fallar el trabajo completo;
no hay reanudación ni reintentos automáticos que consuman cuota sin control.

Los límites de concurrencia son por proceso. Mantén un solo proceso Uvicorn;
para escalar la API, usa el worker separado con `PROCESS_JOBS_IN_API=false` y
almacenamiento compartido, revisando la capacidad global de los workers.
La duración máxima es una política de admisión, no una garantía de que una hora
se procese en un tiempo determinado o sin reinicios del proveedor de hosting.

Fuentes oficiales consultadas:
[Groq: formatos, tamaño y preparación de audio](https://console.groq.com/docs/speech-to-text),
[faster-whisper: rendimiento y parámetros](https://github.com/SYSTRAN/faster-whisper),
[FFmpeg: opciones de extracción](https://ffmpeg.org/ffmpeg.html).
