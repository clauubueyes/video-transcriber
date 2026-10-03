import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const raw = process.env.TRANSCRIBER_API_URL;
if (!raw) throw new Error('Configura TRANSCRIBER_API_URL con la URL HTTPS del backend.');
const backend = new URL(raw);
if (backend.protocol !== 'https:' || backend.username || backend.password ||
    backend.search || backend.hash || backend.pathname !== '/') {
  throw new Error('TRANSCRIBER_API_URL debe ser un origen HTTPS sin credenciales ni ruta.');
}

const source = await readFile(new URL('../../app/web/index.html', import.meta.url), 'utf8');
const marker = "const API_BASE = '';";
if (!source.includes(marker)) throw new Error('No se encuentra la configuración de API en el HTML.');
const safeOrigin = JSON.stringify(backend.origin).replaceAll('<', '\\u003c');
const html = source.replace(marker, `const API_BASE = ${safeOrigin};`);
const output = fileURLToPath(new URL('./dist/', import.meta.url));
await mkdir(output, { recursive: true });
await writeFile(new URL('./dist/index.html', import.meta.url), html);
console.log('Interfaz generada. Las solicitudes van directamente al backend HTTPS.');
