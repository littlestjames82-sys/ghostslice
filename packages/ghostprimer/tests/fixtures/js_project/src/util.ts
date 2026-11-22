import { helper } from './lib/helper.js';
import { thing } from './thing';

const re = /'/g;
// import { ghost } from './ghost';
/* import { ghost } from './ghost'; */
const note = "import { ghost } from './ghost'";

export function utilFn(): string {
  return helper() + thing + note + re.source;
}

export async function loadLazy(): Promise<string> {
  const m = await import('./lazy');
  return m.lazyValue;
}
