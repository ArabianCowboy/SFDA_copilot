/**
 * SFDA Copilot — Console rendering
 *
 * Reads the DOM and writes to it. Decides nothing about access and fetches
 * nothing; it is handed an answer and shows it.
 *
 * The console starts hidden and is revealed only once the server has confirmed
 * an administrator. That ordering is why `#admin-console` carries `hidden` in
 * the template and is not merely styled away: DESIGN.md's rule is that content
 * is never hidden by a stylesheet on the promise that a script will unhide it —
 * but here the promise runs the other way. A dead module leaves the console
 * hidden, which is the safe failure.
 */

import { I18n } from '../modules/i18n.js';

const TABS = [
  { tab: 'tab-overview', panel: 'panel-overview' },
  { tab: 'tab-settings', panel: 'panel-settings' },
  { tab: 'tab-people', panel: 'panel-people' },
  { tab: 'tab-audit', panel: 'panel-audit' },
];

const el = (id) => document.getElementById(id);

/** Replace the access-check placeholder with a final message. */
export function showGateMessage(message) {
  const gate = el('admin-gate');
  if (!gate) return;
  gate.hidden = false;
  const text = gate.querySelector('.admin-gate-text');
  if (text) text.textContent = message;
}

/** Reveal the console. Only ever called after the server confirmed the role. */
export function revealConsole(identity) {
  const gate = el('admin-gate');
  const console_ = el('admin-console');
  if (gate) gate.hidden = true;
  if (!console_) return;
  console_.hidden = false;

  const whoami = el('admin-whoami');
  if (whoami && identity?.email) {
    whoami.hidden = false;
    // dir="ltr" on the element, not the page: an email address inside an
    // Arabic bar would otherwise be reordered by the bidi algorithm.
    whoami.setAttribute('dir', 'ltr');
    whoami.textContent = identity.email;
  }

  TABS.forEach(({ panel }) => {
    const body = el(panel)?.querySelector('.admin-panel-body');
    if (body && !body.textContent.trim()) {
      const empty = document.createElement('p');
      empty.className = 'admin-empty';
      empty.textContent = I18n.t('admin.empty');
      body.appendChild(empty);
    }
  });
}

/** Select one tab, updating both ARIA state and roving tabindex. */
export function selectTab(tabId) {
  TABS.forEach(({ tab, panel }) => {
    const isActive = tab === tabId;
    const tabEl = el(tab);
    const panelEl = el(panel);
    if (tabEl) {
      tabEl.setAttribute('aria-selected', String(isActive));
      // Roving tabindex: one stop for the whole tablist, then arrow keys move
      // within it. Leaving every tab focusable makes Tab walk the set, which is
      // the wrong shape for a tablist.
      tabEl.tabIndex = isActive ? 0 : -1;
    }
    if (panelEl) panelEl.hidden = !isActive;
  });
}

export function focusTab(tabId) {
  el(tabId)?.focus();
}

export const tabIds = () => TABS.map((entry) => entry.tab);

/* ── Settings ────────────────────────────────────────────────────────────── */

/**
 * The four generation settings, in the order an operator thinks about them:
 * which model, then how it behaves, then how much it is given.
 *
 * `numeric` marks the values that are machine-reported facts and take the mono
 * face with tabular figures — and, under RTL, an explicit LTR direction, since
 * a number beside Arabic text is otherwise reordered.
 */
const FIELDS = [
  { key: 'model', kind: 'select' },
  { key: 'reasoningEffort', name: 'reasoning_effort', kind: 'effort' },
  { key: 'temperature', kind: 'number', step: '0.1', numeric: true },
  { key: 'maxTokens', name: 'max_tokens', kind: 'number', step: '1', numeric: true },
  { key: 'maxContextResults', name: 'max_context_results', kind: 'number', step: '1', numeric: true },
];

/** The selected model's contract, from the allowlist the server sent. */
function specFor(modelId, allowedModels) {
  return (allowedModels || []).find((m) => m.id === modelId) || {};
}

const fieldName = (field) => field.name || field.key;

function buildControl(field, value, allowedModels, currentModel) {
  if (field.kind === 'effort') {
    // Populated from the SELECTED model's own list, because the levels differ
    // per model — Luna offers `none`, Nano's floor is `minimal`. A shared list
    // would offer a value the server would then refuse.
    const efforts = specFor(currentModel, allowedModels).reasoning_efforts || [];
    const select = document.createElement('select');
    select.className = 'form-select admin-input';

    const unset = document.createElement('option');
    unset.value = '';
    // Not a synonym for "medium": sending nothing lets the model apply its own
    // documented default, which is not ours to guess at.
    unset.textContent = I18n.t('admin.settings.reasoningDefault');
    unset.selected = !value;
    select.appendChild(unset);

    efforts.forEach((level) => {
      const option = document.createElement('option');
      option.value = level;
      option.textContent = level;
      option.selected = level === value;
      select.appendChild(option);
    });
    return select;
  }

  if (field.kind === 'select') {
    const select = document.createElement('select');
    select.className = 'form-select admin-input';
    allowedModels.forEach((model) => {
      const option = document.createElement('option');
      option.value = model.id;
      // The label is a machine fact and is not translated; see config.yaml.
      option.textContent = model.label || model.id;
      option.selected = model.id === value;
      select.appendChild(option);
    });
    return select;
  }

  const input = document.createElement('input');
  input.type = 'number';
  input.step = field.step;
  input.className = 'form-control admin-input';
  input.value = value;
  if (field.numeric) input.setAttribute('dir', 'ltr');
  return input;
}

/** Render the settings form. Returns nothing; read it back with readSettingsForm. */
export function renderSettings({ settings, overrides, allowed_models: allowedModels }) {
  const body = el('settings-body');
  if (!body) return;
  body.textContent = '';

  const form = document.createElement('form');
  form.id = 'settings-form';
  form.className = 'admin-form';
  form.noValidate = true;

  const hint = document.createElement('p');
  hint.className = 'admin-form-hint';
  hint.textContent = I18n.t('admin.settings.hint');
  form.appendChild(hint);

  const spec = specFor(settings.model, allowedModels);
  const isReasoning = (spec.reasoning_efforts || []).length > 0;

  FIELDS.forEach((field) => {
    const name = fieldName(field);

    // A reasoning model rejects `temperature` outright, and an ordinary one
    // rejects `reasoning_effort`. Showing a control the server would refuse is
    // an invitation to a 422 that nobody could have predicted from the form.
    if (field.kind === 'effort' && !isReasoning) return;
    if (name === 'temperature' && spec.supports_temperature === false) return;

    const row = document.createElement('div');
    row.className = 'admin-field';
    row.dataset.field = name;

    const label = document.createElement('label');
    label.className = 'admin-field-label';
    label.htmlFor = `setting-${name}`;
    label.textContent = I18n.t(`admin.settings.${field.key}`);

    const control = buildControl(field, settings[name], allowedModels || [], settings.model);
    control.id = `setting-${name}`;
    control.name = name;

    // Says whether this value was chosen or merely inherited. The two look
    // identical in the input and revert differently, so the distinction has to
    // be visible or an operator cannot tell what they are actually changing.
    const origin = document.createElement('span');
    const isOverride = Object.prototype.hasOwnProperty.call(overrides || {}, name);
    origin.className = `admin-field-origin${isOverride ? ' is-override' : ''}`;
    origin.textContent = I18n.t(
      isOverride ? 'admin.settings.overridden' : 'admin.settings.usingDefault',
    );

    const error = document.createElement('p');
    error.className = 'admin-field-error';
    error.id = `error-${name}`;
    error.hidden = true;
    // Bound now rather than when an error appears: a control that gains
    // aria-describedby mid-interaction is announced inconsistently.
    control.setAttribute('aria-describedby', error.id);

    row.append(label, control, origin, error);
    form.appendChild(row);
  });

  const actions = document.createElement('div');
  actions.className = 'admin-form-actions';

  const save = document.createElement('button');
  save.type = 'submit';
  save.className = 'btn btn-primary btn-sm';
  save.id = 'settings-save';
  save.textContent = I18n.t('admin.settings.save');
  actions.appendChild(save);

  form.appendChild(actions);
  body.appendChild(form);
}

/** The form's current values, keyed as the API expects them. */
export function readSettingsForm() {
  const form = el('settings-form');
  if (!form) return {};

  const patch = {};
  FIELDS.forEach((field) => {
    const name = fieldName(field);
    const control = form.elements[name];
    // Absent because the selected model does not accept it. Omitted entirely
    // rather than sent as null: null means "revert this override", and a model
    // switch should not silently clear a setting the operator never touched.
    if (!control) return;
    if (field.kind === 'effort') {
      // Empty is "model default", which is a removal — distinct from any level.
      patch[name] = control.value || null;
      return;
    }
    if (field.kind === 'number') {
      const raw = control.value.trim();
      // An empty box is not zero. Sending it as a number would silently write
      // a value nobody typed, so it is left out of the patch entirely.
      if (raw === '') return;
      patch[name] = Number(raw);
    } else {
      patch[name] = control.value;
    }
  });
  return patch;
}

export function clearSettingsErrors() {
  document.querySelectorAll('.admin-field-error').forEach((node) => {
    node.hidden = true;
    node.textContent = '';
  });
  document.querySelectorAll('.admin-field').forEach((node) => {
    node.classList.remove('has-error');
  });
}

/** Put each failure beside the field it belongs to, not in a pile at the top. */
export function showSettingsErrors(errors) {
  clearSettingsErrors();
  (errors || []).forEach(({ field, code, limit }) => {
    const row = document.querySelector(`.admin-field[data-field="${field}"]`);
    const node = el(`error-${field}`);
    const text = I18n.t(`admin.errors.${code}`, {
      limit: Array.isArray(limit) ? limit.join('–') : limit,
    });
    if (node) {
      node.textContent = text;
      node.hidden = false;
    }
    if (row) row.classList.add('has-error');
    // A field-less failure (storage unavailable) has nowhere to sit; the
    // caller surfaces it as a toast instead.
  });
}

export function setSettingsSaving(isSaving) {
  const save = el('settings-save');
  if (!save) return;
  save.disabled = isSaving;
  save.textContent = I18n.t(isSaving ? 'admin.settings.saving' : 'admin.settings.save');
}

/* ── Activity ────────────────────────────────────────────────────────────── */

/** A recorded action as one sentence, rather than a raw action code. */
function describeAction(action) {
  // Explicit rather than derived from the code string. An unknown action
  // showing its raw identifier is honest; guessing a translation from a dotted
  // name would produce confident nonsense in Arabic.
  if (action === 'settings.update') return I18n.t('admin.audit.actionSettingsUpdate');
  return action;
}

/** The changed keys, as `key: from → to`. */
function describeChange(before, after) {
  const keys = new Set([...Object.keys(before || {}), ...Object.keys(after || {})]);
  const parts = [];
  keys.forEach((key) => {
    const from = before?.[key];
    const to = after?.[key];
    if (JSON.stringify(from) === JSON.stringify(to)) return;
    parts.push(`${key}: ${from === undefined ? '—' : from} → ${to === undefined ? '—' : to}`);
  });
  return parts.join('\n');
}

export function renderAudit(entries, { append = false } = {}) {
  const body = el('audit-body');
  if (!body) return;

  if (!append) {
    body.textContent = '';

    const hint = document.createElement('p');
    hint.className = 'admin-form-hint';
    hint.textContent = I18n.t('admin.audit.hint');
    body.appendChild(hint);

    if (!entries.length) {
      const empty = document.createElement('p');
      empty.className = 'admin-empty';
      empty.textContent = I18n.t('admin.audit.empty');
      body.appendChild(empty);
      return;
    }

    const table = document.createElement('table');
    table.className = 'admin-table';
    table.id = 'audit-table';
    const head = document.createElement('thead');
    const headRow = document.createElement('tr');
    ['columnWhen', 'columnWho', 'columnWhat', 'columnChange'].forEach((key) => {
      const th = document.createElement('th');
      th.scope = 'col';
      th.textContent = I18n.t(`admin.audit.${key}`);
      headRow.appendChild(th);
    });
    head.appendChild(headRow);
    table.append(head, document.createElement('tbody'));
    body.appendChild(table);
  }

  const tbody = el('audit-table')?.querySelector('tbody');
  if (!tbody) return;

  entries.forEach((entry) => {
    const row = document.createElement('tr');

    const when = document.createElement('td');
    // A timestamp is a machine-reported fact: mono, and LTR even in Arabic,
    // where bidi would otherwise reorder the parts of the date.
    when.className = 'admin-cell-machine';
    when.setAttribute('dir', 'ltr');
    when.textContent = new Date(entry.occurred_at).toLocaleString(I18n.lang);

    const who = document.createElement('td');
    who.className = 'admin-cell-machine';
    who.setAttribute('dir', 'ltr');
    who.textContent = entry.actor_email || '—';

    const what = document.createElement('td');
    what.textContent = describeAction(entry.action);

    const change = document.createElement('td');
    change.className = 'admin-cell-machine';
    change.setAttribute('dir', 'ltr');
    change.textContent = describeChange(entry.before, entry.after) || '—';

    row.append(when, who, what, change);
    tbody.appendChild(row);
  });
}

export function showAuditMessage(message) {
  const body = el('audit-body');
  if (!body) return;
  body.textContent = '';
  const p = document.createElement('p');
  p.className = 'admin-empty';
  p.textContent = message;
  body.appendChild(p);
}

export function showSettingsMessage(message) {
  const body = el('settings-body');
  if (!body) return;
  body.textContent = '';
  const p = document.createElement('p');
  p.className = 'admin-empty';
  p.textContent = message;
  body.appendChild(p);
}
