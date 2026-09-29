# Video Transcriber

API autoalojable para transcribir vídeos desde una URL o un archivo y reutilizar el resultado desde cualquier aplicación.

El proyecto está pensado como un servicio independiente: no conoce recetas, Abuela's Kitchen ni una interfaz concreta. Sus consumidores pueden usar la transcripción para crear subtítulos, resúmenes, buscadores, notas o recetas.

## Objetivo

- Transcribir audio y vídeo de forma local, sin una API de transcripción de pago.
- Exponer una API HTTP versionada y documentada.
- Aceptar trabajos asíncronos, para no bloquear una petición mientras se procesa un vídeo largo.
- Entregar texto, idioma, segmentos y marcas de tiempo.
- Eliminar automáticamente los archivos temporales al finalizar.

## Alcance inicial

La primera versión admitirá URLs de YouTube y archivos que el usuario suba explícitamente. YouTube será una integración inicial, no una promesa de compatibilidad permanente: los proveedores pueden cambiar sus mecanismos de acceso y cada usuario debe respetar sus permisos y condiciones de uso.

Primero se buscarán subtítulos disponibles. Si no existen, el servicio descargará solo el audio necesario y lo transcribirá localmente.

No se entrenará un modelo de voz desde cero. Se ejecutará un modelo abierto de Whisper mediante `faster-whisper`, que permite inferencia local en CPU o GPU y modelos cuantizados.

## Arquitectura prevista

```text
Proyecto cliente
       |
       | POST /v1/transcriptions
       v
Video Transcriber API (FastAPI)
       |
       +-- valida URL, token, tamaño y duración
       +-- crea un trabajo asíncrono
       |
       +-- descarga subtítulos o audio temporal (yt-dlp)
       +-- transcribe localmente (faster-whisper)
       +-- guarda resultado temporal
       v
Cliente consulta GET /v1/transcriptions/{id}
```

La API no convertirá la transcripción en receta. Esa decisión pertenece a cada aplicación cliente. Abuela's Kitchen, por ejemplo, podrá enviar el texto a su propio extractor de recetas.

## API propuesta

La especificación OpenAPI será la fuente de verdad cuando se implemente el servidor.

### Crear una transcripción

`POST /v1/transcriptions`

```json
{
  "source": {
    "type": "url",
    "url": "https://www.youtube.com/watch?v=..."
  },
  "language": "es"
}
```

Respuesta inicial (`202 Accepted`):

```json
{
  "id": "trn_01H...",
  "status": "queued",
  "createdAt": "2026-09-30T10:00:00Z"
}
```

### Consultar un trabajo

`GET /v1/transcriptions/{id}`

Estados: `queued`, `downloading`, `transcribing`, `completed`, `failed`, `expired`.

Respuesta completada:

```json
{
  "id": "trn_01H...",
  "status": "completed",
  "language": "es",
  "durationSeconds": 482,
  "text": "...",
  "segments": [
    { "start": 0.0, "end": 4.2, "text": "..." }
  ],
  "expiresAt": "2026-10-01T10:00:00Z"
}
```

### Eliminar un trabajo

`DELETE /v1/transcriptions/{id}`

Elimina de inmediato el resultado y los archivos temporales asociados.

## Seguridad y privacidad

- Autenticación mediante token de servicio en `Authorization: Bearer <token>`.
- Lista inicial de dominios permitidos; nunca descargar URLs arbitrarias sin validación.
- Bloqueo de IPs privadas, localhost y redirecciones inseguras para evitar SSRF.
- Límites configurables de tamaño, duración y número de trabajos por token.
- Cola con concurrencia limitada para evitar saturar CPU/GPU.
- No guardar audio, vídeo o transcripciones más allá del periodo configurado.
- No versionar tokens, modelos descargados, audios ni resultados de usuarios en Git.

## Tecnología prevista

| Área | Elección inicial |
| --- | --- |
| API | Python + FastAPI |
| Ejecución | Docker Compose |
| Transcripción | faster-whisper / CTranslate2 |
| Obtención de audio o subtítulos | yt-dlp |
| Cola y estado | SQLite para desarrollo; Redis + worker en producción |
| Documentación | OpenAPI integrada en FastAPI |
| Observabilidad | logs estructurados sin contenido de transcripciones |

El perfil inicial será CPU con un modelo `small` cuantizado. GPU y modelos mayores serán opciones de despliegue, no requisitos para arrancar localmente.

## Integración con Abuela's Kitchen

Abuela's Kitchen no llamará directamente al transcriptor desde el navegador. Su backend enviará el trabajo a esta API con el token secreto, consultará el estado y devolverá la transcripción terminada a la interfaz. Así el token no queda expuesto y otros proyectos pueden reutilizar el mismo servicio.

Variables de entorno previstas en el proyecto consumidor:

```env
VIDEO_TRANSCRIBER_URL=https://transcriber.example.com
VIDEO_TRANSCRIBER_TOKEN=replace-with-a-secret
```

## Hoja de ruta

1. Crear la base FastAPI, Docker y comprobaciones de salud.
2. Definir los contratos OpenAPI y pruebas de autenticación.
3. Implementar trabajos, almacenamiento temporal y consulta de estado.
4. Añadir subtítulos y extracción de audio para YouTube.
5. Integrar `faster-whisper` y segmentos temporizados.
6. Añadir límites, limpieza automática, trazabilidad y pruebas de carga.
7. Conectar Abuela's Kitchen como primer cliente.

## Requisitos de ejecución

El software no requerirá una API de pago. Sí necesita una máquina que esté encendida mientras procese trabajos: el ordenador propio con Docker, un servidor propio o un VPS. Una web publicada no puede acceder por sí sola a un transcriptor que solo se ejecute en el ordenador local de otra persona.

## Estado

En fase de diseño. Aún no hay servidor ni endpoints implementados.
