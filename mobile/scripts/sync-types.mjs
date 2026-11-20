// The wire types are owned by the web app (frontend/src/types.ts). The phone app keeps
// a copy so Metro never has to read outside its own folder; this script refreshes the
// copy and `--check` (run by `npm test`) fails when the two have drifted.
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const source = join(here, '..', '..', 'frontend', 'src', 'types.ts');
const target = join(here, '..', 'src', 'api', 'types.ts');
const header =
  '// GENERATED — a copy of frontend/src/types.ts. Do not edit here.\n' +
  '// Refresh with `npm run sync-types`; `npm test` fails when it is out of date.\n';

const want = header + readFileSync(source, 'utf8').replace(/\r\n/g, '\n');
if (process.argv.includes('--check')) {
  let have = '';
  try { have = readFileSync(target, 'utf8').replace(/\r\n/g, '\n'); } catch { /* missing */ }
  if (have !== want) {
    console.error('src/api/types.ts is out of date with frontend/src/types.ts — run `npm run sync-types`');
    process.exit(1);
  }
  console.log('types in sync');
} else {
  writeFileSync(target, want, 'utf8');
  console.log('wrote', target);
}
