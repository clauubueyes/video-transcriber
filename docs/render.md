# Prueba en Render Free

La web y la API se publican juntas en un único servicio Docker. La inferencia
usa Groq; no hay que subir un modelo Whisper ni configurar Vercel.

## Desplegar desde el panel

1. Sube a GitHub la versión que quieras probar, incluyendo `render.yaml`.
   No subas `.env`, modelos, bases de datos ni archivos de usuarios.
2. En [Render](https://dashboard.render.com/), elige **New > Blueprint**,
   conecta `clauubueyes/video-transcriber` y selecciona la rama correspondiente.
3. Render leerá `render.yaml`. Comprueba que el único servicio tiene plan
   **Free** y región Frankfurt.
4. Introduce `VIDEO_TRANSCRIBER_GROQ_API_KEY` copiando su valor desde tu `.env`
   local. Render genera un token privado para la API automáticamente.
5. Despliega y espera a que el servicio esté **Live**. Abre la URL HTTPS que
   Render asigne al servicio.

Si prefieres **New > Web Service**, usa el repositorio, runtime **Docker**,
plan **Free**, health check `/ready` y copia las variables de `render.yaml`.
Configura también Docker Command:

```sh
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

En esta modalidad debes generar tú un `VIDEO_TRANSCRIBER_TOKEN` largo y privado.
No añadas un disco ni un worker separado para esta prueba.

## Comprobación

- `/health` debe devolver `{"status":"ok"}`.
- `/ready` debe devolver `{"status":"ready"}`.
- `/` debe mostrar la interfaz sin pedir el token privado.
- Sube primero un audio corto MP3, WAV o M4A inferior a 25 MB y comprueba
  que el trabajo llega a `completed` y muestra texto.
- Después prueba una URL de YouTube de menos de 10 minutos. Si YouTube
  bloquea la IP del centro de datos, la subida directa permite comprobar
  la transcripción independientemente del acceso a YouTube.

## Si falla una URL de YouTube

El contenedor incluye Deno y `yt-dlp[default]` (con los scripts EJS) para
resolver los desafíos JavaScript de YouTube. Si aparece `Failed to extract
any player response`, sube estos cambios y ejecuta **Manual Deploy > Clear
build cache & deploy** en Render para reconstruir la imagen. Los logs de
construcción muestran las versiones de Deno y yt-dlp instaladas. Este error
por sí solo no confirma un bloqueo de IP.

Si falla la consulta de metadatos, la API devuelve un 502 con un mensaje que
recomienda probar otro vídeo o subir el archivo. En **Render > Logs**, busca
`video_metadata_failed`: el traceback conserva la causa de yt-dlp. Si aparece
`Sign in to confirm you're not a bot`, YouTube está rechazando el acceso desde
el servidor; cambiar la clave de Groq no resuelve ese bloqueo. Prueba una subida
directa para comprobar la transcripción sin depender de YouTube.

### Configurar cookies para el bloqueo antibot

La aplicación admite `VIDEO_TRANSCRIBER_YOUTUBE_COOKIE_FILE` en la consulta de
duración, los subtítulos y la descarga de audio, tanto en la API como en el worker.
Las cookies pueden ayudar a autenticar la sesión, pero no garantizan resolver
un bloqueo de la IP del servidor.

1. Exporta únicamente las cookies de `youtube.com` en formato Netscape siguiendo
   la [guía oficial de yt-dlp](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies).
   La guía recomienda una sesión privada que se cierre después de exportar para
   evitar que YouTube rote las cookies. Advierte también del riesgo de bloqueo
   de la cuenta al usarla con yt-dlp; evita utilizar tu cuenta principal.
2. En **Render > Environment > Secret Files**, añade `youtube-cookies.txt` y
   pega el contenido del archivo. No lo subas a GitHub ni lo compartas en el chat.
3. Añade la variable de entorno:

   ```env
   VIDEO_TRANSCRIBER_YOUTUBE_COOKIE_FILE=/etc/secrets/youtube-cookies.txt
   ```

4. Despliega el código actualizado y vuelve a probar la URL. La aplicación usa
   una copia temporal por operación porque yt-dlp actualiza el archivo al cerrar;
   el secreto original no se modifica. Renueva el secreto cuando caduque la sesión.

Render monta los secretos en `/etc/secrets/`, según su
[documentación](https://render.com/docs/configure-environment-variables#secret-files).
Si el bloqueo persiste, utiliza la subida directa o ejecuta el servicio localmente.
En local configura la variable con la ruta del archivo exportado.

Si el trabajo se crea pero falla después, busca `job_failed`. Comprueba que
`VIDEO_TRANSCRIBER_GROQ_API_KEY` está configurada en **Render > Environment**:
el `.env` local no se copia al despliegue.

## Límites de esta prueba

Render Free tiene 512 MB de RAM y se suspende después de 15 minutos sin
peticiones. SQLite, trabajos, resultados y archivos temporales se pierden
al suspenderse, reiniciarse o redesplegarse; descarga los resultados que quieras
conservar. El siguiente acceso puede tardar aproximadamente un minuto.

El Blueprint limita las subidas a 25 MB, los vídeos remotos a 10 minutos,
la concurrencia a un trabajo y la cuota pública a 10 trabajos por hora.
La duración no garantiza que el audio descargado de YouTube ocupe menos de
25 MB: Groq puede rechazarlo si supera su límite. Groq también tiene sus
propias cuotas; usa una cuenta Free si quieres mantener esta prueba gratuita.
El audio sin subtítulos y los archivos subidos se envían a Groq para inferencia.

Documentación oficial:
[Render Free](https://render.com/docs/free),
[Blueprints](https://render.com/docs/blueprint-spec) y
[Groq Speech to Text](https://console.groq.com/docs/speech-to-text).
