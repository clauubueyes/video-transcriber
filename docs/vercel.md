# Publicar la interfaz en Vercel

Vercel aloja la página; un backend HTTPS con disco persistente ejecuta FastAPI
y el worker. Las solicitudes del navegador van directamente a ese backend,
incluidas las subidas, sin exponer el token privado ni la clave de Groq.

## 1. Publicar el backend

Usa el despliegue Docker descrito en [despliegue.md](despliegue.md). Necesitas
un servidor con Docker, disco persistente y un dominio HTTPS. Un backend que
solo está en `localhost` no es accesible desde la web pública.

Configura en el entorno del proceso API (en `.env` si usas Docker Compose):

```env
VIDEO_TRANSCRIBER_CORS_ORIGINS=https://video-transcriber.vercel.app
VIDEO_TRANSCRIBER_PUBLIC_WEB_ENABLED=true
```

Sustituye el origen por el dominio real de tu proyecto de Vercel, sin barra
final. Se admiten varios orígenes separados por comas, por ejemplo un dominio
propio y un despliegue de preview concreto. Reinicia la API después de cambiar
esta variable. En ejecución local, expórtala en la terminal antes de iniciar
uvicorn; la configuración CORS se lee del entorno del proceso.

Comprueba `https://api.tudominio.com/health` y `/ready` y confirma que el worker
está funcionando antes de publicar la interfaz.

## 2. Crear el proyecto de Vercel

Importa el repositorio de GitHub y configura:

| Ajuste | Valor |
| --- | --- |
| Root Directory | `deploy/vercel` |
| Include source files outside of the Root Directory | Activado |
| Framework Preset | Other |
| Build Command | `node build.mjs` |
| Output Directory | `dist` |
| Install Command | Vacío; sin dependencias npm |

El archivo `deploy/vercel/vercel.json` contiene la configuración de build.
La inclusión de archivos fuera de la raíz es necesaria para leer
`app/web/index.html` sin mantener otra copia de la interfaz.

Añade esta variable de entorno para Production y los previews que quieras usar:

```env
TRANSCRIBER_API_URL=https://api.tudominio.com
```

Debe ser el origen HTTPS del backend, sin rutas ni credenciales. Esta URL es
pública y queda incluida en el HTML. Los secretos de transcripción pertenecen
solo al backend; no los añadas a la interfaz. Pulsa Deploy y añade el dominio
resultante a `VIDEO_TRANSCRIBER_CORS_ORIGINS` en el servidor.

## 3. Verificar

Abre la URL de Vercel, crea una transcripción desde YouTube y espera el
resultado. Prueba también la subida de un archivo corto. Ambas operaciones
deben crear un trabajo y consultar su estado con una clave de acceso propia.

Si aparece un error de red, revisa la URL del backend, su certificado HTTPS y
los orígenes CORS. Si los trabajos quedan en `queued`, revisa el worker. La
publicación de la página no inicia ni aloja el backend.

## Comprobar el build local

Desde la raíz del repositorio:

```powershell
$env:TRANSCRIBER_API_URL = "https://api.tudominio.com"
node deploy/vercel/build.mjs
```

La salida está en `deploy/vercel/dist/index.html` y se excluye de Git. El build
falla si falta la URL, para evitar publicar una interfaz sin backend.
