/**
 * SFDA Copilot — Incremental markdown rendering
 *
 * Re-parsing the whole buffer every token is cheap for `marked` (~1ms on 8KB),
 * but swapping innerHTML at 30Hz destroys text selection, restarts CSS
 * animations and forces a full-subtree layout on every frame.
 *
 * So the buffer is split at the last "safe boundary" — a blank line that is not
 * inside an open code fence. Everything before it is markdown-complete, is
 * parsed once and appended forever (.md-committed). Only the short tail after
 * it is re-parsed each frame (.md-pending).
 *
 * finish() does one final full re-parse. That is the correctness escape hatch:
 * it repairs anything that spanned a boundary — reference-style links, a table
 * whose delimiter row arrived after a blank line — and guarantees the streamed
 * DOM matches what the non-streaming path would have produced.
 */

import { marked } from 'https://cdn.jsdelivr.net/npm/marked@12.0.2/+esm';
import DOMPurify from 'https://cdn.jsdelivr.net/npm/dompurify@3.4.12/+esm';

const FENCE_LINE = /^\s{0,3}(```|~~~)/;

const sanitize = (html) => DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });

/** Split into [markdown-complete prefix, still-changing tail]. */
export function splitAtSafeBoundary(text) {
  const lines = text.split('\n');
  let insideFence = false;
  let safeEnd = 0;
  let cursor = 0;

  for (let i = 0; i < lines.length; i++) {
    if (FENCE_LINE.test(lines[i])) insideFence = !insideFence;
    cursor += lines[i].length + 1;
    // A blank line outside a fence, with content still to come, is a boundary.
    if (!insideFence && lines[i].trim() === '' && i < lines.length - 1) safeEnd = cursor;
  }

  return [text.slice(0, safeEnd), text.slice(safeEnd)];
}

/**
 * `marked` must never see half a fence: an unterminated ``` makes it emit a
 * runaway <pre> that swallows the rest of the answer. The synthetic closer is
 * added to the PARSE INPUT only, never to the buffer.
 */
export function stabilise(markdown) {
  const fences = markdown.match(/^\s{0,3}(```|~~~)/gm);
  return fences && fences.length % 2 ? `${markdown}\n\`\`\`` : markdown;
}

/** A lone "| cell" renders as a paragraph, then snaps to a <table> a frame
 *  later. Holding it back one frame avoids the flash. */
export function tableIsIncomplete(tail) {
  const lines = tail.trimEnd().split('\n');
  return lines.length === 1 && /^\s*\|/.test(lines[0]);
}

export class MarkdownStream {
  /**
   * @param {HTMLElement} contentEl the .message-content element
   * @param {(scope: HTMLElement) => void} [decorate] runs after each parse
   */
  constructor(contentEl, decorate) {
    this.root = contentEl;
    this.decorate = decorate || (() => {});

    this.committed = document.createElement('div');
    this.committed.className = 'md-committed';
    this.pending = document.createElement('div');
    this.pending.className = 'md-pending';
    contentEl.append(this.committed, this.pending);

    this.buffer = '';
    this.committedLength = 0;
    this.frame = 0;
    this.dirty = false;
  }

  push(chunk) {
    this.buffer += chunk;
    this._schedule();
  }

  /** Coalesce to at most one flush per animation frame, whatever the token rate. */
  _schedule() {
    if (this.frame) { this.dirty = true; return; }
    this.frame = requestAnimationFrame(() => {
      this.frame = 0;
      this._flush();
      if (this.dirty) { this.dirty = false; this._schedule(); }
    });
  }

  _flush() {
    const [safe, tail] = splitAtSafeBoundary(this.buffer);

    if (safe.length > this.committedLength) {
      const fresh = safe.slice(this.committedLength);
      this.committed.insertAdjacentHTML('beforeend', sanitize(marked.parse(fresh)));
      this.committedLength = safe.length;
      this.decorate(this.committed);
    }

    if (!tableIsIncomplete(tail)) {
      this.pending.innerHTML = sanitize(marked.parse(stabilise(tail)));
      this.decorate(this.pending);
    }
  }

  /**
   * Final full re-parse; returns the complete markdown that was rendered.
   *
   * @param {string|null} [canonicalText] the server's authoritative answer.
   *
   * The delta frames carry RAW model tokens, but the server post-processes the
   * answer before it decides anything about it — a model that reverts to
   * "[Source: Guide.pdf, Page: 14]" has that rewritten to "[1]" server-side.
   * Without this parameter the browser keeps the raw prose while the API
   * reports a citation of source 1, so the reader is told an answer cites a
   * passage and given no marker to click.
   *
   * Passing the canonical text here means the final re-parse — which this
   * method already performs as its correctness escape hatch — renders exactly
   * the string the citation indices were computed from.
   */
  finish(canonicalText = null) {
    if (this.frame) cancelAnimationFrame(this.frame);
    this.frame = 0;

    /* Any string replaces the buffer, including ''. Requiring truthiness meant
       a canonical EMPTY answer left the raw deltas on screen — the one case
       where the server is saying "there is no answer here" and the reader was
       shown fabricated text instead. */
    if (typeof canonicalText === 'string') this.buffer = canonicalText;

    this.committed.innerHTML = sanitize(marked.parse(this.buffer));
    this.pending.remove();
    this.decorate(this.committed);
    return this.buffer;
  }
}
