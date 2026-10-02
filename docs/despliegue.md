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

Coloca un modelo CTranslate2 de Whisper en `models/whisper-small`. Sin modelo,
los vídeos con subtítulos pueden funcionar, pero los que necesitan transcripción
de audio fallarán. El servicio no descarga el modelo automáticamente.

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
