# Plan de implementación

## Propósito

Construir **Video Transcriber** como un servicio autoalojable que obtiene
subtítulos o transcribe localmente el audio de un vídeo. El resultado es texto,
idioma y segmentos con marcas de tiempo para que cada aplicación cliente lo use
como necesite.

El servicio no interpreta el contenido como recetas, resúmenes u otro dominio;
esa responsabilidad pertenece al cliente que lo consume.

## Límites y privacidad

- No se conectará a APIs de OpenAI, Gemini ni a ningún proveedor externo de IA.
- `faster-whisper` ejecutará un modelo abierto localmente, en CPU o GPU de la
  máquina donde se despliegue el servicio.
- `yt-dlp` solo accede a la URL de vídeo que proporcione la persona usuaria para
  recuperar subtítulos o el audio necesario.
- OpenAPI no es un servicio externo: es el formato de documentación de la API
  propia. FastAPI puede generar `/docs` localmente a partir del código. Puede
  desactivarse en producción.
- No se conservarán audios, vídeos ni transcripciones después de su periodo de
  retención configurado.

## Arquitectura objetivo

```text
Aplicación cliente
        |
        | API HTTP propia: POST /v1/transcriptions
        v
Video Transcriber (FastAPI)
        |
        +-- valida token, URL y límites
        +-- registra un trabajo asíncrono
        |
        +-- busca subtítulos (yt-dlp)
        +-- o descarga audio temporal (yt-dlp)
        +-- transcribe localmente (faster-whisper)
        +-- guarda resultado temporal y segmentos
        v
Cliente consulta GET /v1/transcriptions/{id}
```

La API HTTP es una interfaz entre aplicaciones propias, no una integración con
una IA en la nube.

## Estructura inicial propuesta

```text
app/
  api/             # Rutas HTTP y dependencias de autenticación
  core/            # Configuración y errores comunes
  models/          # Modelos Pydantic y estados de un trabajo
  services/        # Validación, subtítulos, descarga y transcripción
  storage/         # Persistencia SQLite y limpieza de resultados
  workers/         # Ejecución limitada de trabajos asíncronos
tests/
docs/
Dockerfile
docker-compose.yml
pyproject.toml
.env.example
```

## Fases

### 1. Base ejecutable

- Crear el proyecto Python y sus dependencias: FastAPI, Uvicorn, Pydantic,
  `faster-whisper`, `yt-dlp` y el controlador SQLite elegido.
- Añadir `Dockerfile` y `docker-compose.yml` para una ejecución reproducible.
- Crear `.env.example` sin secretos y `.gitignore` para ignorar entornos,
  modelos, temporales, bases de datos y resultados.
- Implementar `GET /health`.

**Criterio de aceptación:** `docker compose up` inicia el servicio y
`GET /health` responde correctamente.

### 2. Contrato HTTP, configuración y seguridad

- Definir los modelos de solicitud, respuesta, error, segmento y trabajo.
- Implementar autenticación `Authorization: Bearer <token>`.
- Implementar `POST /v1/transcriptions`, que devuelve `202 Accepted` con un ID
  `trn_*` y estado `queued`.
- Validar HTTPS, dominios permitidos (YouTube en la primera versión), ausencia
  de localhost/IPs privadas y redirecciones inseguras para prevenir SSRF.
- Configurar token, dominios, duración máxima, tamaño máximo, retención y
  concurrencia mediante variables de entorno.

**Criterio de aceptación:** solicitudes sin token, con URL inválida o con un
proveedor no admitido se rechazan sin iniciar una descarga.

### 3. Ciclo de vida de trabajos

- Persistir trabajos y metadatos en SQLite para desarrollo.
- Implementar los estados `queued`, `downloading`, `transcribing`,
  `completed`, `failed` y `expired`.
- Implementar `GET /v1/transcriptions/{id}`.
- Implementar `DELETE /v1/transcriptions/{id}` para cancelar o borrar un
  resultado y sus temporales de forma idempotente.
- Ejecutar trabajos en segundo plano con concurrencia limitada. El diseño debe
  permitir sustituirlo por Redis y un worker independiente en producción.

**Criterio de aceptación:** un trabajo creado progresa por estados consultables
y puede cancelarse sin dejar archivos temporales.

### 4. Subtítulos y audio de YouTube

- Integrar `yt-dlp` detrás de un adaptador aislado y testeable.
- Intentar recuperar subtítulos antes de descargar audio.
- Normalizar subtítulos a texto y segmentos `{ start, end, text }`.
- Cuando no existan subtítulos, comprobar duración y descargar solo audio
temporal dentro de los límites configurados.

**Criterio de aceptación:** un vídeo compatible con subtítulos termina sin usar
el motor Whisper; uno sin subtítulos pasa a transcripción local.

### 5. Transcripción local

- Integrar `faster-whisper` con perfil inicial de CPU, modelo `small`
  cuantizado y selección opcional de GPU mediante configuración.
- Mantener el modelo cargado en el worker para no recargarlo por cada trabajo.
- Devolver `language`, `durationSeconds`, `text` y `segments` al completar.
- Clasificar los errores sin exponer detalles internos al consumidor.

**Criterio de aceptación:** un audio de prueba produce texto y segmentos
temporizados, sin realizar ninguna petición a un proveedor de IA externo.

### 6. Retención, límites y observabilidad

- Añadir limpieza programada de trabajos caducados y archivos temporales.
- Añadir límites por token y una cola con concurrencia configurable.
- Registrar eventos estructurados con ID, estado y duración, sin tokens, audio
ni contenido de la transcripción.
- Añadir métricas básicas de cola, trabajos activos, duración y errores.

**Criterio de aceptación:** al vencer el TTL, el trabajo queda `expired` y sus
datos ya no pueden recuperarse.

### 7. Pruebas y documentación operativa

- Pruebas unitarias de autenticación, validación de URL, transiciones de
  estado, expiración y borrado.
- Pruebas de integración para creación, consulta, finalización y cancelación.
- Usar adaptadores simulados de `yt-dlp` y Whisper en CI para evitar descargas
de vídeos y modelos durante las pruebas.
- Documentar variables de entorno, arranque Docker, límites y ejemplos `curl`.

**Criterio de aceptación:** la suite se ejecuta sin red y los ejemplos permiten
usar el servicio local.

## Endpoints previstos

| Método | Ruta | Resultado |
| --- | --- | --- |
| `GET` | `/health` | Estado del servicio. |
| `POST` | `/v1/transcriptions` | Crea un trabajo y devuelve `202`. |
| `GET` | `/v1/transcriptions/{id}` | Consulta estado o resultado. |
| `DELETE` | `/v1/transcriptions/{id}` | Cancela/elimina un trabajo. |

## Orden de entrega

1. Base Docker/FastAPI y configuración.
2. Autenticación, validación y contrato HTTP.
3. Trabajos asíncronos con SQLite.
4. Subtítulos y audio temporal de YouTube.
5. `faster-whisper` local y segmentos.
6. Limpieza, límites, logs y métricas.
7. Pruebas completas y guía de operación.

## Fuera de alcance inicial

- Extracción de recetas, resúmenes o análisis semántico de transcripciones.
- Proveedores de vídeo distintos de YouTube.
- APIs de IA externas y modelos entrenados por el proyecto.
- Persistencia permanente de contenido de usuarios.
