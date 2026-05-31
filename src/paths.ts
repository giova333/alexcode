/** Resolve bundled resource locations (prompts, default config). */

import { fileURLToPath } from 'node:url';
import path from 'node:path';

// This file lives at <root>/src/paths.ts (dev) or <root>/dist/paths.js (build).
// In both cases the package root is one directory up from the containing dir.
const here = path.dirname(fileURLToPath(import.meta.url));
export const PACKAGE_ROOT = path.dirname(here);

export const PROMPTS_DIR = path.join(PACKAGE_ROOT, 'prompts');
export const CONFIG_DEFAULT_PATH = path.join(PACKAGE_ROOT, 'config.default.yaml');
