import React from 'react';
import { utilFn } from './util';
import { helper } from './lib/helper.js';
import './polyfill';

export { thing } from './thing';

export async function start(): Promise<string> {
  const lazy = await import('./lazy');
  return utilFn() + helper() + lazy.lazyValue + String(React != null);
}
