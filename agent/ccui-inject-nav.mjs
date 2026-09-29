/**
 * Inject our unified cross-navigation into a built claudecodeui index.html.
 *
 * Idempotent: it looks for a marker and skips if already injected. Run as a
 * post-build step (Dockerfile) and by scripts/dev-agent.sh so local + container
 * behave identically.
 *
 *   node ccui-inject-nav.mjs <path-to-index.html> [<nav-snippet.html>]
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const indexPath = process.argv[2];
const navPath = process.argv[3] || join(here, 'ccui-nav.html');

if (!indexPath) {
  console.error('usage: node ccui-inject-nav.mjs <index.html> [nav.html]');
  process.exit(1);
}

const MARKER = 'id="veai-nav"';
let html = readFileSync(indexPath, 'utf8');
if (html.includes(MARKER)) {
  console.log('[inject-nav] already present, skipping');
  process.exit(0);
}

const snippet = readFileSync(navPath, 'utf8');
// Insert just before </body> so it is outside <div id="root">.
if (html.includes('</body>')) {
  html = html.replace('</body>', snippet + '\n</body>');
} else {
  html += snippet;
}
writeFileSync(indexPath, html);
console.log(`[inject-nav] injected nav into ${indexPath}`);
