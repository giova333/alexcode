/** Token counting utilities. */

import { getEncoding, type Tiktoken } from 'js-tiktoken';

import type { ApiMessage } from './message.js';

let encoder: Tiktoken | null = null;

function getEncoder(): Tiktoken {
  if (encoder === null) {
    encoder = getEncoding('cl100k_base');
  }
  return encoder;
}

/** Count tokens in a text string. */
export function countTokens(text: string): number {
  return getEncoder().encode(text).length;
}

/** Estimate token count for a message dict (role + content blocks). */
export function countMessageTokens(message: ApiMessage): number {
  let total = 4; // overhead per message
  const content = message.content;
  if (typeof content === 'string') {
    total += countTokens(content);
  } else if (Array.isArray(content)) {
    for (const block of content) {
      if (block && typeof block === 'object' && block.type === 'text') {
        total += countTokens(block.text ?? '');
      } else {
        total += countTokens(JSON.stringify(block));
      }
    }
  }
  return total;
}
