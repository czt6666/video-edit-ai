/**
 * Platform-mode bootstrap for claudecodeui.
 *
 * In platform mode (VITE_IS_PLATFORM=true) claudecodeui bypasses its own login
 * and trusts whoever reaches it (our gateway enforces auth). It still expects
 * ONE active user row to exist (getFirstUser). This script:
 *   1. ensures exactly one active, onboarding-complete user exists;
 *   2. leaves project creation to the entrypoint (via the HTTP API once the
 *      server is up), which keeps the DB + ~/.claude/projects in sync.
 *
 * Idempotent: safe to run on every boot. Opens the app's own SQLite DB with
 * the bundled better-sqlite3, so it must run with cwd = /opt/claudecodeui.
 */
import { mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname } from 'node:path';

// better-sqlite3 lives in claudecodeui's node_modules, which is a different tree
// from this script. ESM bare-specifier resolution walks up from THIS file, so we
// must resolve the CommonJS module relative to the claudecodeui install instead.
const ccuiDir = process.env.CCUI_DIR || '/opt/claudecodeui';
const require = createRequire(ccuiDir + '/package.json');
const Database = require('better-sqlite3');

const dbPath = process.env.DATABASE_PATH;
if (!dbPath) {
  console.error('[platform-init] DATABASE_PATH is not set');
  process.exit(1);
}

mkdirSync(dirname(dbPath), { recursive: true });

// The app creates the schema on first boot; this script runs AFTER that, but
// guard anyway in case ordering changes.
const db = new Database(dbPath);

function usersTableExists() {
  const row = db
    .prepare("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    .get();
  return Boolean(row);
}

if (!usersTableExists()) {
  console.error('[platform-init] users table missing — start the server once first');
  process.exit(2);
}

const count = db.prepare('SELECT COUNT(*) AS n FROM users').get().n;
if (count === 0) {
  const username = process.env.PLATFORM_USER || 'workspace';
  // Password is irrelevant in platform mode (login is bypassed); store a
  // non-usable placeholder so the column is never null.
  const placeholder = 'platform-mode-no-login';
  db.prepare(
    'INSERT INTO users (username, password_hash, is_active, has_completed_onboarding) VALUES (?, ?, 1, 1)'
  ).run(username, placeholder);
  console.log(`[platform-init] seeded platform user '${username}'`);
} else {
  // Make sure the existing user is active + past onboarding so no wizard shows.
  db.prepare(
    'UPDATE users SET is_active = 1, has_completed_onboarding = 1 WHERE id = (SELECT id FROM users LIMIT 1)'
  ).run();
  console.log('[platform-init] platform user already present');
}

db.close();
