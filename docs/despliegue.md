# Despliegue operativo

## Web pública con HTTPS

La página está incluida en la API en `/`. Los visitantes pegan el enlace y
reciben el texto sin configurar nada ni conocer el token privado.

Para publicarla, necesitas un servidor con Docker y un dominio cuyo DNS apunte
a ese servidor. Añade a `.env`:

```env
TRANSCRIBER_DOMAIN=transcriber.tudominio.com
VIDEO_TRANSCRIBER_PUBLIC_WEB_ENABLED=true
VIDEO_TRANSCRIBER_PUBLIC_JOBS_PER_HOUR=30
```

## Despliegue Gratuito (0€/mes) con Groq API

Si deseas alojar la aplicación sin un servidor de pago ni requisitos de GPU o alta memoria RAM:

1. Obtén una clave de API gratuita en [Groq Console](https://console.groq.com).
2. Añade a tu archivo `.env`:

```env
VIDEO_TRANSCRIBER_GROQ_API_KEY=gsk_tu_clave_de_groq_aqui
VIDEO_TRANSCRIBER_GROQ_MODEL=whisper-large-v3-turbo
```

Al configurar la clave de Groq, la aplicación **no necesita descargar ni cargar modelos locales** (0 MB de RAM ocupados por el modelo local). La transcripción de vídeos y archivos multimedia se realiza en la nube a velocidad ultra rápida (~2 segundos por vídeo) usando la cuota gratuita de Groq.

Groq evita cargar el modelo local, pero no elimina la necesidad de almacenar
trabajos y archivos temporales ni de ejecutar el procesamiento en segundo plano.
El coste y la disponibilidad dependen de las cuotas del proveedor y del alojamiento.

### Vercel

La aplicación actual no está preparada para desplegarse íntegramente en Vercel:

- `app/main.py` crea una base SQLite en `data/transcriber.sqlite3` al arrancar.
  Los trabajos necesitan almacenamiento persistente compartido entre instancias;
  mover SQLite a `/tmp` no resuelve este requisito.
- La API procesa la cola mediante tareas de fondo y un ejecutor local. Ese
  procesamiento debe adaptarse al ciclo de vida y al tiempo máximo de las
  funciones, o ejecutarse en un backend separado.
- Las funciones de Vercel admiten cuerpos de petición de hasta 4,5 MB, mientras
  que la aplicación permite subidas de hasta 500 MB. Para conservar esas subidas
  se necesita almacenamiento externo con subida directa o un backend separado.
- El modo Whisper local requiere un modelo y ffmpeg; configurar Groq no elimina
  automáticamente las dependencias Python locales del proyecto.

Consulta los [límites de Vercel Functions](https://vercel.com/docs/functions/limitations)
antes de configurar el despliegue.

Una opción que conserva la arquitectura actual es publicar la interfaz HTML
en Vercel y alojar la API y el worker en un servidor con disco persistente.
La interfaz debe dirigir sus solicitudes a ese backend, mediante un proxy o
una URL configurada con CORS. El token privado y la clave de Groq deben
permanecer exclusivamente en el backend.

Para alojar también la API en Vercel, primero hay que sustituir SQLite por
almacenamiento compartido, adaptar el procesamiento y resolver las subidas
grandes. Un `vercel.json` por sí solo no realiza estos cambios.

Ejecuta en el servidor:

```powershell
docker compose -f compose.web.yml up -d --build
```

Abre `https://transcriber.tudominio.com`. Caddy gestiona los certificados HTTPS;
los puertos 80 y 443 deben ser accesibles para emitirlos. La API solo es accesible
a través del proxy y el worker se ejecuta como proceso independiente.

Las cuotas se guardan en memoria y son por proceso: este despliegue utiliza una
sola API. Reiniciarla reinicia las cuotas. Para escalar a varias réplicas se
necesitan límites y cola compartidos.

## Antes de exponer el servicio

1. Crea un token aleatorio y guárdalo solo en el gestor de secretos o en el
   archivo `.env` del servidor, nunca en Git.
2. Ejecuta la API y el worker con la misma ruta persistente para `data/` y
   `tmp/`. Para producción se recomienda el worker separado:

   ```env
   VIDEO_TRANSCRIBER_PROCESS_JOBS_IN_API=false
   VIDEO_TRANSCRIBER_MAX_CONCURRENT_JOBS=1
   ```

3. Publica únicamente un proxy inverso HTTPS (Caddy, Nginx o Traefik). El
   puerto 8000 no debe quedar abierto directamente a Internet.
4. Conserva copias de `data/transcriber.sqlite3` mientras uses SQLite. Si se
   necesitan varias réplicas de API o worker, migra la cola a un almacén de
   trabajos compartido antes de escalarlas.

## Comprobaciones tras desplegar

```powershell
Invoke-RestMethod https://transcriber.example.com/health
Invoke-RestMethod https://transcriber.example.com/ready
```

`/ready` debe devolver `{"status":"ready"}`. Si responde `503`, revisa el
volumen de `data/`, los permisos del proceso y los logs del contenedor.

Comprueba también el estado del contenedor y los logs estructurados:

```powershell
docker compose ps
docker compose logs --tail=100 video-transcriber video-transcriber-worker
```

Los logs no contienen tokens, URLs, audio ni texto transcrito; sí incluyen el
identificador del trabajo y los eventos de recuperación, caducidad y limpieza.

## Actualización y recuperación

Antes de actualizar, crea una copia consistente de la base SQLite y detén los
workers. Tras desplegar la nueva versión, inicia primero la API y después el
worker. Los trabajos que el proceso anterior hubiera dejado en curso se
reencolan al superar `VIDEO_TRANSCRIBER_STALE_JOB_TIMEOUT_SECONDS`.

No elimines `tmp/` manualmente mientras haya trabajos pendientes. El worker
elimina las subidas cuando terminan, se cancelan o se detectan como huérfanas.
