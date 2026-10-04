// Keep the version probe fast on small containers. The real generator only
// loads its DOM and BotGuard dependencies when a token is requested.
if (process.argv.includes('--version')) {
  console.log('2.0.1');
} else {
  await import('./generate_once.original.js');
}
