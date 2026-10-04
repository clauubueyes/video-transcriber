const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

const html = readFileSync(join(__dirname, '../app/web/index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const context = vm.createContext({});
// Comprueba la sintaxis de toda la interfaz y ejecuta las funciones de formato.
new vm.Script(script);
vm.runInContext(script.slice(0, script.indexOf("    for (const id of ['format-select'")), context);
const evaluate = expression => JSON.parse(JSON.stringify(vm.runInContext(expression, context)));
const options = { mode: 'paragraphs', timestamps: true, chapters: true };
const sections = (job, settings = options) => evaluate(
  `buildTranscriptSections(${JSON.stringify(job)}, ${JSON.stringify(settings)})`
);

test('timestamps support minutes and videos longer than an hour', () => {
  assert.equal(evaluate('formatTimestamp(0)'), '00:00');
  assert.equal(evaluate('formatTimestamp(65.9)'), '01:05');
  assert.equal(evaluate('formatTimestamp(3665.9)'), '01:01:05');
});

test('chapter boundaries and gaps preserve every segment exactly once', () => {
  const job = {
    chapters: [
      { start: 5, end: 10, title: 'Introducción' },
      { start: 10, end: 20, title: 'Desarrollo' },
      { start: 30, end: 40, title: 'Cierre' }
    ],
    segments: [
      { start: 10, end: 12, text: 'Desarrollo.' },
      { start: 0, end: 3, text: 'Antes.' },
      { start: 8, end: 11, text: 'Cruza el límite.' },
      { start: 22, end: 25, text: 'Entre capítulos.' },
      { start: 30, end: 35, text: 'Cierre.' },
      { start: 42, end: 43, text: 'Después.' }
    ]
  };
  const result = sections(job);
  assert.deepEqual(result.map(section => section.title), [
    'Sin capítulo', 'Introducción', 'Desarrollo', 'Sin capítulo', 'Cierre', 'Sin capítulo'
  ]);
  assert.deepEqual(result.flatMap(section => section.paragraphs.map(paragraph => paragraph.text)), [
    'Antes.', 'Cruza el límite.', 'Desarrollo.', 'Entre capítulos.', 'Cierre.', 'Después.'
  ]);
});

test('paragraph breaks use pauses while keeping actual start times', () => {
  const result = sections({ segments: [
    { start: 5, end: 7, text: 'Hola' },
    { start: 7, end: 10, text: 'mundo.' },
    { start: 15, end: 17, text: 'Otra idea.' }
  ] });
  assert.deepEqual(result[0].paragraphs, [
    { start: 5, text: 'Hola mundo.' }, { start: 15, text: 'Otra idea.' }
  ]);
});

test('all reading modes preserve words and allow chapters to be disabled', () => {
  const job = {
    chapters: [{ start: 0, end: 20, title: 'Capítulo' }],
    segments: [
      { start: 0, end: 1, text: ' Primera frase. ' },
      { start: 4, end: 5, text: 'Segunda frase.' }
    ]
  };
  for (const mode of ['paragraphs', 'segments', 'continuous']) {
    const result = sections(job, { mode, chapters: false });
    assert.equal(result.length, 1);
    assert.equal(result[0].title, null);
    assert.equal(result[0].paragraphs.map(paragraph => paragraph.text).join(' '), 'Primera frase. Segunda frase.');
    assert.equal(result[0].paragraphs.length, mode === 'continuous' ? 1 : 2);
  }
});

test('text without timings stays readable without inventing timestamps or chapters', () => {
  const text = Array.from({ length: 300 }, (_, index) => `palabra${index}`).join(' ');
  const result = sections({ text, chapters: [{ start: 0, end: 10, title: 'Capítulo' }] });
  assert.equal(result[0].title, null);
  assert.ok(result[0].paragraphs.length > 1);
  assert.ok(result[0].paragraphs.every(paragraph => paragraph.start === null));
  assert.equal(result[0].paragraphs.map(paragraph => paragraph.text).join(' '), text);
  assert.deepEqual(sections({}), [{ title: null, start: null, end: null, paragraphs: [] }]);
});

test('copy and TXT export retain paragraph spacing, titles and optional timestamps', () => {
  const result = [{ title: 'Introducción', start: 65, end: 90, paragraphs: [
    { start: 66.5, text: 'Hola mundo.' }, { start: 75, text: 'Otra idea.' }
  ] }];
  assert.equal(evaluate(`transcriptAsText(${JSON.stringify(result)}, true)`),
    '[01:05 – 01:30] Introducción\n\n[01:06] Hola mundo.\n\n[01:15] Otra idea.');
  assert.equal(evaluate(`transcriptAsText(${JSON.stringify(result)}, false)`),
    'Introducción\n\nHola mundo.\n\nOtra idea.');
});
