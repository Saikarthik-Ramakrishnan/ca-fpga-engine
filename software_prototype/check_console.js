// check_console.js
//
// Headless checks for cellnet_console.html. A browser is not always
// available (CI has none, and neither does the sandbox this was written
// in), so this loads the page under jsdom and asserts the things that
// actually break when the single-file console is edited by hand.
//
// What it does NOT do is look at pixels. Layout, spacing and colour still
// need a human eye. Everything below is structure and behaviour.
//
//   node check_console.js          (needs: npm install jsdom@24)
//
// Checks:
//   1. the file parses and the DOM has balanced structure
//   2. no uncaught script errors while the page initialises
//   3. all four tabs exist and switching views works
//   4. the boards render the expected number of dots
//   5. the Life rule bank matches the masks the Verilog uses
//   6. seed and rule packets encode to exactly the bytes on the wire
//   7. no em-dashes or en-dashes in the visible copy

const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('jsdom');

const FILE = path.join(__dirname, 'cellnet_console.html');
const html = fs.readFileSync(FILE, 'utf8');

let failures = 0;
let checks = 0;

function check(name, fn) {
  checks++;
  try {
    fn();
    console.log(`  ok    ${name}`);
  } catch (err) {
    failures++;
    console.log(`  FAIL  ${name}`);
    console.log(`        ${err.message}`);
  }
}

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

function eq(got, want, msg) {
  if (got !== want) throw new Error(`${msg}: got ${got}, want ${want}`);
}

// ---------------------------------------------------------------- load
const pageErrors = [];
const virtualConsole = new VirtualConsole();
virtualConsole.on('jsdomError', (e) => pageErrors.push(e.message));
virtualConsole.on('error', (m) => pageErrors.push(String(m)));

// pretendToBeVisual is deliberately off: it installs requestAnimationFrame,
// and the console's run loop would then hold the node event loop open
// forever. The teardown at the bottom closes the window for the same
// reason (the Engine tab's setInterval survives the last check otherwise).
const dom = new JSDOM(html, {
  runScripts: 'dangerously',
  virtualConsole,
});
const { window } = dom;
const { document } = window;

console.log(`cellnet_console.html  ${html.length} bytes\n`);

// ------------------------------------------------------------- 1 and 2
check('page initialises with no script errors', () => {
  assert(pageErrors.length === 0,
    `${pageErrors.length} error(s):\n        ` + pageErrors.join('\n        '));
});

check('div tags balance', () => {
  const open = (html.match(/<div\b/g) || []).length;
  const close = (html.match(/<\/div>/g) || []).length;
  eq(open, close, 'div open vs close');
});

check('no stray unclosed script or style', () => {
  eq((html.match(/<script\b/g) || []).length,
     (html.match(/<\/script>/g) || []).length, 'script tags');
  eq((html.match(/<style\b/g) || []).length,
     (html.match(/<\/style>/g) || []).length, 'style tags');
});

// ------------------------------------------------------------------- 3
const EXPECTED_TABS = ['engine', 'wildfire', 'live', 'displays'];

check('all four tabs exist', () => {
  const tabs = [...document.querySelectorAll('.tab')].map(t => t.dataset.view);
  eq(tabs.join(','), EXPECTED_TABS.join(','), 'tab list');
  for (const view of EXPECTED_TABS) {
    assert(document.getElementById('view-' + view), `missing #view-${view}`);
  }
});

check('tab switching activates exactly one view', () => {
  for (const view of EXPECTED_TABS) {
    const tab = document.querySelector(`.tab[data-view="${view}"]`);
    tab.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    const active = [...document.querySelectorAll('.view')]
      .filter(v => v.classList.contains('active'))
      .map(v => v.id);
    eq(active.length, 1, `active views after clicking ${view}`);
    eq(active[0], 'view-' + view, `active view after clicking ${view}`);
  }
});

// ------------------------------------------------------------------- 4
check('engine board renders one dot per cell', () => {
  const board = document.getElementById('board');
  assert(board, 'no #board element');
  const dots = board.querySelectorAll('.dot, .cell, div').length;
  assert(dots > 0, 'board has no children');
  const cols = window.COLS !== undefined ? window.COLS : null;
  const rows = window.ROWS !== undefined ? window.ROWS : null;
  if (rows && cols) {
    eq(board.children.length, rows * cols, 'board children');
  }
});

// ------------------------------------------------------------------- 5
// The rule bank is shared with golden_rule.py's RULES and with
// rule_loader.v's reset default. If these masks drift, the console and
// the fabric stop describing the same automaton.
const EXPECTED_RULES = {
  conway:   { notation: 'B3/S23',       birth: 0b000001000, survive: 0b000001100 },
  highlife: { notation: 'B36/S23',      birth: 0b001001000, survive: 0b000001100 },
  daynight: { notation: 'B3678/S34678', birth: 0b111001000, survive: 0b111011000 },
  seeds:    { notation: 'B2/S',         birth: 0b000000100, survive: 0b000000000 },
  maze:     { notation: 'B3/S12345',    birth: 0b000001000, survive: 0b000111110 },
};

check('rule bank matches the masks the Verilog uses', () => {
  const proto = window.cellnetProtocol;
  assert(proto, 'window.cellnetProtocol is not exposed');
  const keys = Object.keys(EXPECTED_RULES);
  for (const key of keys) {
    const { birth, survive } = proto.ruleMasks(key);
    eq(birth, EXPECTED_RULES[key].birth, `${key} birth mask`);
    eq(survive, EXPECTED_RULES[key].survive, `${key} survive mask`);
  }
});

check('rule select is populated from the rule bank', () => {
  const sel = document.getElementById('hwRule');
  assert(sel, 'no #hwRule select');
  eq(sel.options.length, Object.keys(EXPECTED_RULES).length, 'rule options');
});

// ------------------------------------------------------------------- 6
check('rule packets encode to the exact bytes on the wire', () => {
  const proto = window.cellnetProtocol;
  eq(proto.CMD_RULE, 0x33, 'CMD_RULE');
  eq(proto.CMD_SEED, 0x55, 'CMD_SEED');

  // Conway: birth 0b000001000 = 0x008, survive 0b000001100 = 0x00C
  const conway = proto.encodeRulePacket(0b000001000, 0b000001100);
  eq(proto.hexBytes(conway), '33 08 0C 00', 'Conway rule packet');

  // Day & Night exercises both bit-8 flags: birth 0b111001000 = 0x1C8,
  // survive 0b111011000 = 0x1D8, so byte 2 must be 0b11 = 0x03.
  const dn = proto.encodeRulePacket(0b111001000, 0b111011000);
  eq(proto.hexBytes(dn), '33 C8 D8 03', 'Day & Night rule packet');

  eq(conway.length, 4, 'rule packet length');
});

check('seed packets encode to the exact bytes on the wire', () => {
  const proto = window.cellnetProtocol;
  const rows = 8, cols = 8;
  const cells = new Uint8Array(rows * cols);

  // empty grid: command byte plus 8 zero bytes
  let p = proto.encodeSeedPacket(cells, rows, cols);
  eq(p.length, 1 + (rows * cols) / 8, 'seed packet length');
  eq(proto.hexBytes(p), '55 00 00 00 00 00 00 00 00', 'empty seed packet');

  // cell (r=0,c=0) is bit 0, so it must land in payload byte 0, bit 0.
  cells[0] = 1;
  // cell (r=1,c=0) is bit 8, so it must land in payload byte 1, bit 0.
  cells[cols] = 1;
  p = proto.encodeSeedPacket(cells, rows, cols);
  eq(proto.hexBytes(p), '55 01 01 00 00 00 00 00 00', 'two-cell seed packet');
});

check('packet inspector renders on send with no port attached', () => {
  document.querySelector('.tab[data-view="live"]')
    .dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
  document.getElementById('sendRuleBtn')
    .dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
  const text = document.getElementById('packetInspector').textContent;
  assert(/33 /.test(text), `inspector shows no rule packet: ${JSON.stringify(text)}`);
  assert(/4 bytes/.test(text), `inspector missing byte count: ${JSON.stringify(text)}`);
});

// ------------------------------------------------------------------- 7
check('no em-dashes or en-dashes in the copy', () => {
  const bad = [];
  html.split('\n').forEach((line, i) => {
    if (/[–—]/.test(line)) bad.push(`line ${i + 1}: ${line.trim().slice(0, 80)}`);
  });
  assert(bad.length === 0, `${bad.length} line(s):\n        ` + bad.slice(0, 8).join('\n        '));
});

// ---------------------------------------------------------------- report
console.log();
console.log('-------------------------------------------------------------');
console.log(`${checks - failures} passed / ${checks} checks`);
console.log('Structure and behaviour only. Pixels still need an eyeball pass.');

// the page leaves timers running; close the window and exit explicitly
// rather than waiting for an event loop that never drains.
dom.window.close();
if (failures > 0) {
  console.log('RESULT: FAILED');
  process.exit(1);
}
console.log('RESULT: all green');
process.exit(0);
