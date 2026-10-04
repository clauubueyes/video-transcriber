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
python -m app.container_entrypoint uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
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
resolver los desafíos JavaScript de YouTube. También incluye Node y
`bgutil-ytdlp-pot-provider` 2.0.1 con su generador de PO Tokens de la misma
versión. El entrypoint de Docker mantiene su servidor HTTP activo en
`127.0.0.1:4416`, dentro del mismo contenedor y sin añadir otro servicio de
Render. Espera hasta dos minutos a que esté listo antes de arrancar la API o el
worker. Usa los clientes `mweb,tv,web_safari`, siguiendo la
[guía PO Token de yt-dlp](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide)
y las [instrucciones del proveedor](https://github.com/Brainicism/bgutil-ytdlp-pot-provider).
La generación de tokens y la descarga usan la misma salida de red.
El contenedor incluye `curl-cffi` y usa un perfil HTTP/TLS de Chrome mediante
`VIDEO_TRANSCRIBER_YOUTUBE_IMPERSONATE=chrome`, conforme a la
[configuración de impersonación de yt-dlp](https://github.com/yt-dlp/yt-dlp#impersonation).
Esto permite probar un perfil de navegador; tampoco garantiza resolver un
rechazo de la IP.

Si aparece `Failed to extract
any player response`, sube estos cambios y ejecuta **Manual Deploy > Clear
build cache & deploy** en Render para reconstruir la imagen. Los logs de
construcción muestran las versiones de Deno y yt-dlp instaladas. Este error
por sí solo no confirma un bloqueo de IP.

Si falla la consulta de metadatos, la API devuelve un 502 con un mensaje que
recomienda probar otro vídeo o subir el archivo. En **Render > Logs**, busca
`video_metadata_failed`: el traceback conserva la causa de yt-dlp. Si aparece
`Sign in to confirm you're not a bot`, YouTube está rechazando el acceso desde
el servidor; cambiar la clave de Groq no resuelve ese bloqueo. Comprueba la
integración de PO Tokens y, si persiste, configura otra salida de red como se
describe abajo.

### Activar y comprobar los PO Tokens

Publica el código actualizado y reconstruye la imagen. El Dockerfile establece
los valores por defecto, también para servicios existentes creados desde el
panel; no depende de que Render vuelva a importar `render.yaml`:

```env
VIDEO_TRANSCRIBER_YOUTUBE_PLAYER_CLIENTS=mweb,tv,web_safari
VIDEO_TRANSCRIBER_YOUTUBE_PO_TOKEN_SERVER_HOME=/opt/bgutil/server
VIDEO_TRANSCRIBER_YOUTUBE_PO_TOKEN_POLICY=always
VIDEO_TRANSCRIBER_YOUTUBE_PO_TOKEN_BASE_URL=http://127.0.0.1:4416
```

Si ya existen estas variables en Render, sus valores prevalecen sobre Docker.
En un servicio existente actualiza también **Settings > Docker Command** con
el comando indicado arriba: el override de Render puede omitir el entrypoint
de la imagen si conserva el comando antiguo que ejecutaba Uvicorn directamente.
Mantén el archivo de cookies que ya has configurado. No hace falta copiar tokens
manualmente: son temporales y el proveedor los genera cuando se necesitan.
La política `always` solicita también tokens para las llamadas iniciales al
player; `auto` puede omitirlos hasta encontrar una operación que los requiera.

Al pegar una URL, los logs pueden mostrar:

- `youtube_po_token_requested`: se ha solicitado generar un token; comprueba
  también que la consulta o descarga posterior termina correctamente. El evento
  por sí solo no confirma que se haya generado ni aceptado.
  El contexto `player` identifica consultas de formatos, `gvs` la descarga y
  `subs` los subtítulos.
- `youtube_po_token_provider_ready`: el servidor local está listo. Se arranca
  una vez y se reutiliza para evitar el timeout de 15 segundos del método
  script, que se ha observado en Render Free.
- `youtube_provider_warning` / `youtube_provider_error`: avisos del extractor,
  incluidos fallos del proveedor o de EJS. No se registran valores de los tokens
  ni credenciales del proxy.
- `youtube_subtitles_failed`: YouTube rechazó los subtítulos y se intenta
  transcribir el audio. Antes este fallo interrumpía el trabajo.

No expongas el puerto 4416 a Internet: el servicio solo escucha en localhost.
Para ejecución sin Docker puedes usar un proveedor HTTP ya arrancado con
`VIDEO_TRANSCRIBER_YOUTUBE_PO_TOKEN_BASE_URL`, o el método script configurando
solo `VIDEO_TRANSCRIBER_YOUTUBE_PO_TOKEN_SERVER_HOME`. El perfil WARP de abajo
utiliza este último método para reducir el consumo de memoria.

### Si la IP de Render sigue bloqueada

Un PO Token no garantiza que YouTube acepte una IP de centro de datos. La
documentación del proveedor lo indica expresamente. La aplicación permite
configurar un proxy HTTP/HTTPS o SOCKS para metadatos, subtítulos, audio y la
generación de tokens en API y worker:

```env
VIDEO_TRANSCRIBER_YOUTUBE_PROXY_URL=http://usuario:clave@host:puerto
```

Configúralo como variable secreta en Render con un proxy que controles o hayas
contratado y cuya salida pueda acceder a YouTube. Codifica los caracteres
reservados del usuario o contraseña en formato URL. La sesión de cookies debe
ser compatible con esa salida de red. No uses una lista de proxies públicos ni
subas sus credenciales al repositorio. La variable es opcional y no contrata ni
activa ningún servicio de pago por sí sola.

Para reproducir la comprobación desde el entorno de despliegue:

```sh
python -m app.youtube_check 'https://www.youtube.com/watch?v=tu2lkbYVjIk' --audio
```

El resultado incluye la duración y el tamaño del audio, y elimina la descarga
temporal al terminar. Una prueba local no confirma que la IP de Render funcione.

### Salida WARP con generación de tokens bajo demanda

El contenedor incluye `sing-box` 1.14.2, con checksum verificado durante la
construcción. Puede ejecutar WireGuard en espacio de usuario y ofrecer un
proxy solo en `127.0.0.1:40000`, sin un dispositivo TUN ni permisos elevados.
Este componente arranca únicamente si se configura
`VIDEO_TRANSCRIBER_YOUTUBE_WARP_CONFIG`. La aplicación supervisa el proxy y lo
cierra junto con la API. Las claves se escriben en un archivo temporal privado
y los logs del proxy están desactivados.

Para usar Cloudflare WARP hay que registrar previamente un dispositivo y
aceptar sus [condiciones](https://www.cloudflare.com/application/terms/).
El registro empleado en esta investigación se hizo con
[wgcf](https://github.com/ViRb3/wgcf), una herramienta independiente de
Cloudflare. Guarda la configuración WireGuard y el registro del dispositivo
como secretos; no los publiques en GitHub.

Configura en Render un JSON válido de sing-box como variable secreta
`VIDEO_TRANSCRIBER_YOUTUBE_WARP_CONFIG`. Debe contener un único inbound de tipo
`mixed`, con `listen=127.0.0.1` y `listen_port=40000`, un endpoint WireGuard con
`system=false`, y la ruta de salida y la resolución DNS a través del túnel.
Los campos y el formato están en la
[documentación de WireGuard de sing-box](https://sing-box.sagernet.org/configuration/endpoint/wireguard/).
El JSON contiene la clave privada del dispositivo. El registro y la conversión
se hacen una vez; el contenedor no registra dispositivos automáticamente.

El perfil para reducir el consumo de memoria en Render Free es:

```env
VIDEO_TRANSCRIBER_YOUTUBE_PROXY_URL=socks5h://127.0.0.1:40000
VIDEO_TRANSCRIBER_YOUTUBE_PLAYER_CLIENTS=mweb
VIDEO_TRANSCRIBER_YOUTUBE_IMPERSONATE=chrome
VIDEO_TRANSCRIBER_YOUTUBE_JS_RUNTIMES=node
VIDEO_TRANSCRIBER_YOUTUBE_PO_TOKEN_SERVER_HOME=/opt/bgutil/server
VIDEO_TRANSCRIBER_YOUTUBE_PO_TOKEN_MODE=script
VIDEO_TRANSCRIBER_YOUTUBE_PO_TOKEN_POLICY=auto
NODE_OPTIONS=--max-old-space-size=192 --max-semi-space-size=2
```

Selecciona `VIDEO_TRANSCRIBER_YOUTUBE_PO_TOKEN_MODE=script` en este perfil para
generar los tokens mediante procesos que terminan después de cada solicitud.
Este modo ignora la URL del proveedor HTTP incluida por defecto en Docker.
Así no permanece un servidor Node adicional en memoria mientras se resuelven
los desafíos JavaScript. El generador incluye un wrapper para responder a
`--version` sin cargar las bibliotecas de generación y evitar el timeout de
15 segundos del plugin en el arranque. `VIDEO_TRANSCRIBER_YOUTUBE_JS_RUNTIMES`
selecciona Node de forma explícita para API y worker; instalar Node junto a
Deno no basta para cambiar la selección del extractor.

Prueba este perfil sin `VIDEO_TRANSCRIBER_YOUTUBE_COOKIE_FILE` para vídeos
públicos, manteniendo guardado el secreto de cookies por si necesitas volver
al perfil autenticado. Usa el Docker Command indicado al principio de esta
guía, reconstruye y espera a que Render indique **Live** antes de comprobar
la transcripción completa. Cambiar la salida de red no garantiza que YouTube
acepte todos los vídeos ni que mantenga ese acceso indefinidamente.

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
Si el bloqueo persiste, comprueba los PO Tokens y la salida de red descritos
arriba. En local configura la variable con la ruta del archivo exportado.

Al probar una URL, busca estos eventos en los logs de la API o del worker:

- `youtube_cookie_file_not_configured`: el proceso recibió `None` como ruta;
  comprueba la variable `VIDEO_TRANSCRIBER_YOUTUBE_COOKIE_FILE` en ese servicio
  y vuelve a desplegar después de configurarla.
- `youtube_cookie_file_loaded`: el archivo se copió y se pasó a yt-dlp para esa
  operación. No confirma que las cookies sean válidas, que la sesión siga activa
  ni que YouTube acepte la IP del servidor.
- `youtube_cookie_file_missing`: la ruta configurada no existe.
- `youtube_cookie_file_unreadable`: la copia falló por otro error de acceso o
  de escritura; el evento indica el tipo de error y su código `errno`, y la
  operación falla.

Estos mensajes no incluyen el contenido de las cookies. La ausencia de
`youtube_cookie_file_missing` por sí sola no permite deducir que la variable
no se leyó: el archivo también puede haberse cargado correctamente.

Si aparece `youtube_cookie_file_missing` en los logs, la ruta configurada no
existe y la aplicación continúa sin cookies. Crea el archivo secreto con el
nombre exacto `youtube-cookies.txt`, o elimina
`VIDEO_TRANSCRIBER_YOUTUBE_COOKIE_FILE` si quieres trabajar sin cookies, y vuelve
a desplegar. Sin cookies, YouTube todavía puede exigir una verificación antibot.

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
