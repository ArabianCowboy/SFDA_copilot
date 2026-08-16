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
import { iconMarkup } from '../modules/icons.js';

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
    /* A panel that ships structural children is not empty, it is waiting — and
       the Users panel ships two, `#people-list` and `#people-detail`. Testing
       only for text left a permanent "Nothing here yet." card sitting under the
       accounts table, because the loader fills a child and never touches the
       placeholder that was appended beside it. */
    if (body && !body.children.length && !body.textContent.trim()) {
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

function buildControl(field, value, allowedModels, currentModel, ceiling) {
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
  // The output ceiling belongs to the MODEL, not to the field, and it changes
  // under the operator when they pick a different one. Declaring it here is
  // not a clamp — `noValidate` is set on the form and the server still refuses
  // — it is the difference between a box that quietly holds an unsaveable
  // number and one that says what the number may be.
  if (fieldName(field) === 'max_tokens' && ceiling) input.max = ceiling;
  if (field.numeric) input.setAttribute('dir', 'ltr');
  return input;
}

/** Render the settings form. Returns nothing; read it back with readSettingsForm. */
export function renderSettings({
  settings, overrides, defaults, allowed_models: allowedModels, active,
}) {
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

  // Said here, where the model is chosen, when the model being chosen is not
  // the model answering. This form otherwise describes the stored settings and
  // nothing else, which is how a console could show Luna for two days while
  // every answer came from gpt-4o-mini — the disagreement existed only in the
  // server's terminal, and only for whoever thought to look.
  const activeModel = active?.model;
  if (activeModel && settings.model && activeModel !== settings.model) {
    const stale = document.createElement('p');
    stale.className = 'admin-form-hint is-warning';
    stale.id = 'settings-not-live';
    stale.setAttribute('role', 'status');
    stale.textContent = I18n.t('admin.settings.notLive', { model: activeModel });
    form.appendChild(stale);
  }

  const spec = specFor(settings.model, allowedModels);
  const isReasoning = (spec.reasoning_efforts || []).length > 0;

  // The settings this model has no parameter for, recorded on the form so that
  // reading it back can say so.
  //
  // Not rendering a control is only half a decision. The other half is what the
  // patch says about it, and "nothing" was the wrong answer: an override stored
  // for the PREVIOUS model survived the merge, the server validated the
  // resulting document and refused it — `reasoning_effort` set on a model with
  // no reasoning — and the refusal named a field this form had chosen not to
  // draw, so it could not be shown either. Switching away from a reasoning
  // model was therefore impossible from this console and silent about it.
  const inapplicable = [];

  FIELDS.forEach((field) => {
    const name = fieldName(field);

    // A reasoning model rejects `temperature` outright, and an ordinary one
    // rejects `reasoning_effort`. Showing a control the server would refuse is
    // an invitation to a 422 that nobody could have predicted from the form.
    if (field.kind === 'effort' && !isReasoning) { inapplicable.push(name); return; }
    if (name === 'temperature' && spec.supports_temperature === false) {
      inapplicable.push(name);
      return;
    }

    const row = document.createElement('div');
    row.className = 'admin-field';
    row.dataset.field = name;

    const label = document.createElement('label');
    label.className = 'admin-field-label';
    label.htmlFor = `setting-${name}`;
    label.textContent = I18n.t(`admin.settings.${field.key}`);

    const control = buildControl(
      field, settings[name], allowedModels || [], settings.model, spec.max_output_tokens,
    );
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

    // Only an overridden field has anything to revert. Offering it on a field
    // already inheriting the default would be a control that does nothing.
    if (isOverride && defaults && name in defaults) {
      const revert = document.createElement('button');
      revert.type = 'button';
      revert.className = 'btn btn-sm btn-ghost admin-field-revert';
      revert.dataset.revert = name;
      revert.textContent = I18n.t('admin.settings.revert');
      row.appendChild(revert);
    }

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
  // Read back by readSettingsForm as explicit removals. Empty string when the
  // model accepts everything, which `split` turns into `[]` rather than `['']`.
  form.dataset.inapplicable = inapplicable.join(',');
  body.appendChild(form);
}

/** The form's current values, keyed as the API expects them. */
export function readSettingsForm() {
  const form = el('settings-form');
  if (!form) return {};

  const patch = {};

  // Settings the SELECTED model has no parameter for, cleared explicitly.
  //
  // This used to be an omission, on the reasoning that null means "revert this
  // override" and a model switch should not clear a setting nobody touched.
  // The reasoning was right about what null means and wrong about what the
  // operator did: choosing a model without a temperature IS a decision about
  // temperature. Omitting it left the old value in the stored document, the
  // server validated the resulting pair — `reasoning_effort` against a model
  // with no reasoning, which is exactly the invalid-pair-from-two-valid-values
  // case it exists to catch — and refused every save. There was no gesture in
  // this form that could clear it, because the control it belongs to is the one
  // the new model caused to disappear.
  const inapplicable = (form.dataset.inapplicable || '').split(',').filter(Boolean);
  inapplicable.forEach((name) => { patch[name] = null; });

  FIELDS.forEach((field) => {
    const name = fieldName(field);
    const control = form.elements[name];
    if (!control) return;
    // Marked for reversion by the control below. Sent as null, which removes
    // the override — distinct from writing the default's current value, which
    // would pin it against a future deploy.
    const row = control.closest('.admin-field');
    if (row?.dataset.reverting === 'true') {
      patch[name] = null;
      return;
    }
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

/**
 * What the controls are SHOWING, with none of the patch semantics attached.
 *
 * Separate from readSettingsForm because the two questions are different, and
 * answering the second with the first is what blanked a field. A patch says
 * "remove this override" with null; a re-render needs a value to put in a box,
 * and null is not one. A field the current model has no parameter for is simply
 * absent here, so the caller keeps whatever it already knew — which is the only
 * place that value still exists once the control is gone.
 */
export function readSettingsDisplay() {
  const form = el('settings-form');
  if (!form) return {};

  const shown = {};
  FIELDS.forEach((field) => {
    const name = fieldName(field);
    const control = form.elements[name];
    if (!control) return;
    // A staged revert has already put the default in the box, so reading the
    // control shows what it will become — which is what should carry over.
    if (field.kind === 'effort') {
      shown[name] = control.value || null;
      return;
    }
    const raw = String(control.value).trim();
    if (raw === '') return;
    shown[name] = field.kind === 'number' ? Number(raw) : raw;
  });
  return shown;
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

/**
 * Put each failure beside the field it belongs to, not in a pile at the top.
 *
 * Returns the failures that found no field to sit beside, so the caller can say
 * them out loud. That return value is the fix for a save that refused in
 * silence: an error against a control this model does not render — storage
 * unavailable, or a setting left over from the previous model — was written
 * into a DOM node that does not exist and then dropped. The operator got a
 * re-enabled Save button and no other change on screen.
 */
export function showSettingsErrors(errors) {
  clearSettingsErrors();
  const homeless = [];
  (errors || []).forEach((entry) => {
    const { field, code, limit } = entry;
    const row = document.querySelector(`.admin-field[data-field="${field}"]`);
    const node = el(`error-${field}`);
    const text = I18n.t(`admin.errors.${code}`, {
      limit: Array.isArray(limit) ? limit.join('–') : limit,
    });
    if (node) {
      node.textContent = text;
      node.hidden = false;
    } else {
      homeless.push(entry);
    }
    if (row) row.classList.add('has-error');
  });
  return homeless;
}

export function setSettingsSaving(isSaving) {
  const save = el('settings-save');
  if (!save) return;
  save.disabled = isSaving;
  save.textContent = I18n.t(isSaving ? 'admin.settings.saving' : 'admin.settings.save');
}

/* ── People ──────────────────────────────────────────────────────────────── */

function machineCell(text, { mono = true } = {}) {
  const td = document.createElement('td');
  if (mono) {
    // Emails, dates and ids are machine-reported facts. Each cell carries its
    // own dir="ltr" because an outer dir="rtl" reorders an address.
    td.className = 'admin-cell-machine';
    td.setAttribute('dir', 'ltr');
  }
  td.textContent = text;
  return td;
}

function actionButton(label, { danger = false, action, id, disabled = false }) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'btn btn-sm btn-ghost admin-row-action';
  button.dataset.action = action;
  button.dataset.userId = id;
  button.textContent = label;
  button.disabled = disabled;
  // The design system has no danger button variant — logout, the one genuinely
  // irreversible control in the reader app, is a quiet ghost. So a destructive
  // action here is a quiet ghost too, and the weight is carried by the
  // confirmation and the record rather than by colour.
  if (danger) button.classList.add('is-destructive');
  return button;
}

export function renderUsers({ users, total, self_id: selfId }) {
  const body = el('people-list');
  if (!body) return;
  body.textContent = '';

  const hint = document.createElement('p');
  hint.className = 'admin-form-hint';
  hint.textContent = I18n.t('admin.people.hint');
  body.appendChild(hint);

  if (!users.length) {
    const empty = document.createElement('p');
    empty.className = 'admin-empty';
    empty.textContent = I18n.t('admin.people.empty');
    body.appendChild(empty);
    return;
  }

  const table = document.createElement('table');
  table.className = 'admin-table';
  table.id = 'people-table';

  const head = document.createElement('thead');
  const headRow = document.createElement('tr');
  ['columnEmail', 'columnRole', 'columnAccess', 'columnLastSeen', 'columnActions']
    .forEach((key) => {
      const th = document.createElement('th');
      th.scope = 'col';
      th.textContent = I18n.t(`admin.people.${key}`);
      headRow.appendChild(th);
    });
  head.appendChild(headRow);

  const tbody = document.createElement('tbody');
  users.forEach((user) => {
    const isSelf = user.id === selfId;
    const row = document.createElement('tr');
    row.dataset.userId = user.id;

    /* The email is the way in. A row that opens a detail view needs an
       affordance a keyboard can reach, and the address is the thing an operator
       is already looking for. `textContent` of the cell is unchanged, which the
       confirmation copy in handlers.js reads. */
    const email = machineCell('');
    const open = document.createElement('button');
    open.type = 'button';
    open.className = 'admin-row-action admin-account-open';
    open.dataset.action = 'open';
    open.dataset.userId = user.id;
    open.textContent = user.email;
    email.appendChild(open);
    if (isSelf) {
      const you = document.createElement('span');
      you.className = 'admin-you';
      you.textContent = ` (${I18n.t('admin.people.you')})`;
      email.appendChild(you);
    }

    const role = document.createElement('td');
    role.textContent = I18n.t(
      user.role === 'admin' ? 'admin.people.roleAdmin' : 'admin.people.roleUser',
    );

    const access = document.createElement('td');
    access.textContent = I18n.t(
      user.is_disabled ? 'admin.people.accessDisabled' : 'admin.people.accessAllowed',
    );
    if (user.is_disabled) {
      access.classList.add('admin-flag-off');
      // The stated reason, beside the state it explains. Asking for one and
      // then never showing it is how a required field becomes theatre.
      if (user.disabled_reason) {
        const why = document.createElement('span');
        why.className = 'admin-cell-note';
        why.textContent = user.disabled_reason;
        access.append(document.createElement('br'), why);
      }
    }

    /* Two different kinds of value share this column, so they cannot share a
       cell treatment. A stamp is machine-reported and takes the mono LTR box;
       "never" is a translated sentence, and forcing it into that same box set
       Arabic in a Latin mono face and laid it out left-to-right. The account
       detail view already draws this distinction — see the `text:` branch of
       the sign-in fact — and the table had not. */
    const seen = user.last_sign_in_at
      ? machineCell(dayStamp(user.last_sign_in_at))
      : machineCell(I18n.t('admin.people.never'), { mono: false });

    /* Role and access used to be buttons on every row AND on the detail view.
       TODO.md asks for one home for everything done to an account, and a
       control in two places is two places to keep true — so they live on the
       account page now and this column carries only the way through to it. */
    const go = document.createElement('td');
    go.className = 'admin-row-go';
    go.setAttribute('aria-hidden', 'true');
    go.innerHTML = iconMarkup('chevron-right', 14);

    row.append(email, role, access, seen, go);
    tbody.appendChild(row);
  });

  table.append(head, tbody);
  body.appendChild(table);

  if (total > users.length) {
    const count = document.createElement('p');
    count.className = 'admin-form-hint';
    count.textContent = `${users.length} / ${total}`;
    body.appendChild(count);
  }
}

export function showPeopleMessage(message) {
  const body = el('people-list');
  if (!body) return;
  body.textContent = '';
  const p = document.createElement('p');
  p.className = 'admin-empty';
  p.textContent = message;
  body.appendChild(p);
}

/* ── Activity ────────────────────────────────────────────────────────────── */

/** A recorded action as one sentence, rather than a raw action code. */
const ACTION_KEYS = {
  'settings.update': 'admin.audit.actionSettingsUpdate',
  'user.disable': 'admin.audit.actionUserDisable',
  'user.enable': 'admin.audit.actionUserEnable',
  'user.role_change': 'admin.audit.actionUserRoleChange',
  'user.profile_change': 'admin.audit.actionUserProfileChange',
  'user.password_reset_requested': 'admin.audit.actionResetRequested',
  'user.password_reset_accepted': 'admin.audit.actionResetAccepted',
  'user.password_reset_failed': 'admin.audit.actionResetFailed',
};

function describeAction(action) {
  // A lookup rather than a derivation. An unknown action showing its raw
  // identifier is honest; guessing a translation from a dotted name would
  // produce confident nonsense in Arabic.
  const key = ACTION_KEYS[action];
  return key ? I18n.t(key) : action;
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
    ['columnWhen', 'columnWho', 'columnWhat', 'columnChange', 'columnReason'].forEach((key) => {
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
    /* A timestamp is a machine-reported fact: mono, and LTR even in Arabic.
       `dir="ltr"` is necessary and was never sufficient — the Arabic locale
       format carries a strongly-RTL comma and meridiem marker, and bidi
       reorders those inside the isolate, moving the day digit to the end of
       the line. `exactWhen` emits no localised characters at all, so there is
       nothing left to reorder. */
    when.className = 'admin-cell-machine';
    when.setAttribute('dir', 'ltr');
    when.textContent = exactWhen(entry.occurred_at);

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

    const note = document.createElement('td');
    note.textContent = entry.note || '—';

    row.append(when, who, what, change, note);
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

/**
 * Stage a field for reversion.
 *
 * Staged rather than written immediately, because the form is submitted whole:
 * an operator midway through editing three fields should not lose two of them
 * to reverting the third. The input shows what it will become, the marker says
 * so, and Save sends null for it.
 */
export function stageRevert(name, defaults) {
  const row = document.querySelector(`.admin-field[data-field="${name}"]`);
  if (!row) return;

  row.dataset.reverting = 'true';
  const control = row.querySelector('.admin-input');
  if (control) control.value = defaults?.[name] ?? '';

  const origin = row.querySelector('.admin-field-origin');
  if (origin) {
    origin.classList.remove('is-override');
    origin.textContent = I18n.t('admin.settings.usingDefault');
  }
  row.querySelector('.admin-field-revert')?.remove();
}

// ── Account detail ────────────────────────────────────────────────────────────
//
// An in-panel swap, not a fifth tab. An account has no meaning without one being
// selected, and a permanently-present tab that is empty until you pick somebody
// is a lie the roving-tabindex model has to live with. `#tab-people` stays
// selected throughout, so `aria-selected` stays honest.

/** Machine-reported facts stay left-to-right even under `dir="rtl"`. */
function machineValue(text) {
  const span = document.createElement('span');
  span.className = 'admin-cell-machine';
  span.setAttribute('dir', 'ltr');
  span.textContent = text;
  return span;
}

const RELATIVE_STEPS = [
  ['year', 31536000], ['month', 2592000], ['week', 604800],
  ['day', 86400], ['hour', 3600], ['minute', 60],
];

/**
 * "3 days ago", in whichever language the console is in.
 *
 * Intl does the localisation, so this needs no catalogue entry and no plural
 * rules of our own — Arabic has six plural forms, and hand-writing them is how
 * a date ends up ungrammatical in one of them and nobody notices for a year.
 */
function relativeWhen(value) {
  const then = Date.parse(value);
  if (Number.isNaN(then)) return null;
  const seconds = (then - Date.now()) / 1000;
  const size = Math.abs(seconds);
  const format = new Intl.RelativeTimeFormat(I18n.lang, { numeric: 'auto' });
  if (size < 60) return format.format(0, 'second');
  const [unit, step] = RELATIVE_STEPS.find(([, span]) => size >= span);
  return format.format(Math.round(seconds / step), unit);
}

/**
 * The exact stamp: ISO order, local clock, no localised characters at all.
 *
 * `toLocaleString(lang)` was wrong here in a way that only showed up in Arabic.
 * The Arabic form mixes strongly-RTL characters — the comma and the meridiem
 * marker — into a run of digits, and the bidi algorithm reorders them even
 * inside a `dir="ltr"` isolate: "1/2/2026، 3:00:00 م" rendered with the day
 * digit moved to the far end of the line, which is a date that says the wrong
 * thing rather than one that merely looks odd.
 *
 * Building it from the parts sidesteps that completely, and is the better read
 * anyway: DESIGN.md reserves the mono face for values a machine produced, and a
 * sortable fixed-width stamp is what that means. The human reading of the same
 * moment sits above it in the body face and localises fully.
 */
function exactWhen(value) {
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return '';
  const pad = (part) => String(part).padStart(2, '0');
  return `${dayStamp(value)} `
    + `${pad(at.getHours())}:${pad(at.getMinutes())}:${pad(at.getSeconds())}`;
}

/**
 * The date alone, on exactly the doctrine above, for the columns that carry no
 * clock time.
 *
 * The people table asked Intl for this one and got back `15<RLM>/8<RLM>/2026`:
 * the `ar` locale separates the numeric fields with U+200F RIGHT-TO-LEFT MARK.
 * Those are strongly-RTL characters sitting in a run of digits, so the bidi
 * algorithm reorders the fields even inside the cell's own `dir="ltr"` isolate,
 * and the column rendered the literal string `152026/8/` — a date that says the
 * wrong thing rather than one that merely looks odd. `dir` cannot fix it; only
 * not emitting the marks can.
 *
 * The audit table already learned this — see the comment on `exactWhen` and the
 * one above the audit `when` cell. This cell had been left behind.
 */
function dayStamp(value) {
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return '';
  const pad = (part) => String(part).padStart(2, '0');
  return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}`;
}

/**
 * One cell of the readout.
 *
 * A timestamp gets two readings and never one: the relative one in ink, because
 * that is what an operator decides on, and the exact stamp beneath it in mono,
 * because that is what they defend the decision with afterwards. It is the same
 * split this product already makes between an answer and its citation.
 */
function fact(list, label, { when = null, text = null, machine = false } = {}) {
  const cell = document.createElement('div');
  cell.className = 'admin-fact';

  const dt = document.createElement('dt');
  dt.textContent = label;

  const dd = document.createElement('dd');
  if (when) {
    dd.textContent = relativeWhen(when) || '';
    const exact = document.createElement('span');
    exact.className = 'admin-fact-exact';
    exact.setAttribute('dir', 'ltr');
    exact.textContent = exactWhen(when);
    dd.appendChild(exact);
  } else if (machine && text) {
    dd.appendChild(machineValue(text));
  } else {
    dd.textContent = text || I18n.t('admin.account.notSet');
  }

  cell.append(dt, dd);
  list.appendChild(cell);
}

/** A standing, as a pill. Not a row in a list of facts: it is the thing an
    operator has to see before reading anything else on the page. */
function mark(label, variant = '') {
  const span = document.createElement('span');
  span.className = variant ? `admin-mark ${variant}` : 'admin-mark';
  span.textContent = label;
  return span;
}

/** A zone heading and the hairline that runs out from it to the edge. */
function section(title) {
  const wrapper = document.createElement('section');
  wrapper.className = 'admin-section';

  const head = document.createElement('div');
  head.className = 'admin-section-head';

  const heading = document.createElement('h3');
  heading.className = 'admin-subheading';
  heading.textContent = title;

  head.appendChild(heading);
  wrapper.appendChild(head);
  return wrapper;
}

function backLink() {
  const back = document.createElement('button');
  back.type = 'button';
  back.id = 'account-back';
  back.className = 'admin-backlink';
  back.innerHTML = iconMarkup('chevron-right', 14);
  const label = document.createElement('span');
  label.textContent = I18n.t('admin.account.back');
  back.appendChild(label);
  return back;
}

export function showAccountList() {
  const list = el('people-list');
  const detail = el('people-detail');
  if (list) list.hidden = false;
  if (detail) { detail.hidden = true; detail.textContent = ''; }
  const search = el('people-search-field');
  if (search) search.hidden = false;
}

/**
 * Swap the panel over to the detail side and hand back an empty container.
 *
 * The FIELD is hidden, not the input: hiding `#people-search` alone left its
 * label stranded above the account page with nothing underneath it, which is
 * what "Search by email" was doing over the top of every account.
 */
function openDetailPanel() {
  const list = el('people-list');
  const detail = el('people-detail');
  if (!detail) return null;

  if (list) list.hidden = true;
  const search = el('people-search-field');
  if (search) search.hidden = true;

  detail.hidden = false;
  detail.className = 'admin-detail';
  detail.textContent = '';
  return detail;
}

/** The three fields an operator may rewrite. Mirrors `_PROFILE_FIELDS` in
    web/api/admin.py, which rejects anything outside the set rather than
    quietly dropping it. */
const PROFILE_FIELDS = [
  { name: 'full_name', id: 'account-full-name', key: 'admin.account.fullName' },
  { name: 'organization', id: 'account-organization', key: 'admin.account.organization' },
  { name: 'specialization', id: 'account-specialization', key: 'admin.account.specialization' },
];

let currentSelfId = null;

export function renderAccountDetail(account, entries, selfId = null) {
  currentSelfId = selfId ?? currentSelfId;
  const detail = openDetailPanel();
  if (!detail) return;

  const isSelf = account.id === currentSelfId;
  detail.appendChild(backLink());

  /* ── The account as one object ─────────────────────────────────────────────
     Address, person, standing. It was six more rows in a flat definition list
     before, which meant an operator had to read the page to learn whether this
     person could use the product at all. */
  const head = document.createElement('div');
  head.className = 'admin-account-head';
  if (account.is_disabled) head.classList.add('is-off');

  const identity = document.createElement('div');
  identity.className = 'admin-account-id';

  const heading = document.createElement('h2');
  heading.className = 'admin-account-address';
  heading.id = 'account-heading';
  heading.tabIndex = -1;
  /* The address and nothing else. `handlers.js` reads this element's
     textContent to name the account in a confirmation, so a display name folded
     in here would be quoted back at an operator as though it were an email. */
  heading.appendChild(machineValue(account.email));
  identity.appendChild(heading);

  const person = [account.full_name, account.organization].filter(Boolean).join(' · ');
  if (person) {
    const line = document.createElement('p');
    line.className = 'admin-account-person';
    line.textContent = person;
    identity.appendChild(line);
  }

  const marks = document.createElement('div');
  marks.className = 'admin-marks';
  if (account.has_profile) {
    marks.append(
      mark(I18n.t(account.role === 'admin' ? 'admin.people.roleAdmin' : 'admin.people.roleUser'),
        account.role === 'admin' ? 'is-signal' : ''),
      mark(I18n.t(account.is_disabled ? 'admin.people.accessDisabled' : 'admin.people.accessAllowed'),
        account.is_disabled ? 'is-off' : ''),
    );
  } else {
    marks.appendChild(mark(I18n.t('admin.account.noProfileMark'), 'is-off'));
  }
  if (isSelf) marks.appendChild(mark(I18n.t('admin.people.you')));

  head.append(identity, marks);

  /* The stated reason, where the standing is. Asking for one and then filing it
     as the sixth row of a definition list is how a required field becomes
     theatre. */
  if (account.is_disabled && account.disabled_reason) {
    const note = document.createElement('div');
    note.className = 'admin-account-note';
    const text = document.createElement('p');
    text.textContent = `${I18n.t('admin.account.disabledReason')}: `;
    const reason = document.createElement('span');
    reason.className = 'admin-account-reason';
    reason.textContent = account.disabled_reason;
    text.appendChild(reason);
    note.appendChild(text);
    head.appendChild(note);
  }
  detail.appendChild(head);

  /* The state the list cannot express at all: `admin_list_users` coalesces the
     missing columns to healthy defaults, so a broken account reads there as an
     ordinary reader. Said plainly here instead. */
  if (!account.has_profile) {
    const broken = document.createElement('div');
    broken.className = 'admin-notice';
    broken.id = 'account-broken';
    const title = document.createElement('strong');
    title.textContent = I18n.t('admin.account.brokenHeading');
    const body = document.createElement('p');
    body.textContent = I18n.t('admin.account.brokenBody');
    broken.append(title, body);
    detail.appendChild(broken);
  }

  /* ── Zone 1: identity, read-only ─────────────────────────────────────────── */
  const identitySection = section(I18n.t('admin.account.identityHeading'));
  const facts = document.createElement('dl');
  facts.className = 'admin-facts admin-card';
  fact(facts, I18n.t('admin.account.created'), { when: account.created_at });
  fact(facts, I18n.t('admin.account.lastSignIn'), account.last_sign_in_at
    ? { when: account.last_sign_in_at } : { text: I18n.t('admin.people.never') });
  fact(facts, I18n.t('admin.account.confirmed'), account.email_confirmed_at
    ? { when: account.email_confirmed_at } : { text: I18n.t('admin.account.notConfirmed') });
  fact(facts, I18n.t('admin.account.lastSeen'), account.last_seen_at
    ? { when: account.last_seen_at } : { text: I18n.t('admin.people.never') });
  if (account.is_disabled) {
    fact(facts, I18n.t('admin.account.disabledAt'), { when: account.disabled_at });
    fact(facts, I18n.t('admin.account.disabledBy'),
      { text: account.disabled_by_email, machine: true });
  }
  identitySection.appendChild(facts);
  detail.appendChild(identitySection);

  /* ── Zone 2: profile, editable ───────────────────────────────────────────── */
  if (account.has_profile) {
    const profileSection = section(I18n.t('admin.account.profileHeading'));
    profileSection.appendChild(profileForm(account));
    detail.appendChild(profileSection);
  }

  /* ── Zone 3: actions, in increasing severity ─────────────────────────────
     Below the facts on purpose: an operator reads who this is and what state
     they are in before reaching the controls that change it. */
  const actionsSection = section(I18n.t('admin.account.actionsHeading'));
  const card = document.createElement('div');
  card.className = 'admin-card';

  const actions = document.createElement('div');
  actions.className = 'admin-row-actions';
  actions.id = 'account-actions';

  const reset = actionButton(I18n.t('admin.account.sendReset'),
    { action: 'send-reset', id: account.id });
  reset.id = 'account-send-reset';
  actions.appendChild(reset);

  if (account.has_profile) {
    // Disabled for yourself rather than hidden: an operator should see that the
    // control exists and why it is not theirs to use, instead of wondering
    // whether the console forgot to draw it.
    actions.append(
      actionButton(
        I18n.t(account.role === 'admin' ? 'admin.people.demote' : 'admin.people.promote'),
        { action: account.role === 'admin' ? 'demote' : 'promote', id: account.id,
          danger: account.role === 'admin', disabled: isSelf },
      ),
      actionButton(
        I18n.t(account.is_disabled ? 'admin.people.enable' : 'admin.people.disable'),
        { action: account.is_disabled ? 'enable' : 'disable', id: account.id,
          danger: !account.is_disabled, disabled: isSelf },
      ),
    );
  }
  card.appendChild(actions);

  const hint = document.createElement('p');
  hint.className = 'admin-account-hint';
  hint.id = 'account-no-password-hint';
  hint.textContent = I18n.t('admin.account.noPasswordHint');
  card.appendChild(hint);

  /* And what is deliberately missing. An operator mid-incident should not have
     to work out for themselves that the console cannot end a session. */
  const absent = document.createElement('div');
  absent.className = 'admin-absent';
  absent.id = 'account-absent';
  const absentTitle = document.createElement('strong');
  absentTitle.className = 'admin-absent-title';
  absentTitle.textContent = I18n.t('admin.account.absentHeading');
  const absentList = document.createElement('ul');
  absentList.className = 'admin-absent-list';
  [I18n.t('admin.account.absentRevoke'), I18n.t('admin.account.absentEmailChange')]
    .forEach((text) => {
      const li = document.createElement('li');
      li.textContent = text;
      absentList.appendChild(li);
    });
  absent.append(absentTitle, absentList);
  card.appendChild(absent);
  actionsSection.appendChild(card);
  detail.appendChild(actionsSection);

  /* ── Zone 4: what has been done to this account ──────────────────────────
     The same query as the global log with a filter, and this is the page it
     belongs on: "what happened to this person" had no surface anywhere. */
  const activitySection = section(I18n.t('admin.account.activityHeading'));
  activitySection.appendChild(renderAccountActivity(entries));
  detail.appendChild(activitySection);

  heading.focus();
}

/**
 * The profile, as a form rather than a transcript.
 *
 * `PATCH /admin/api/users/<id>/profile` and `admin_update_profile` were built
 * and tested with no caller at all, so this zone showed three values an
 * operator could read and not correct. Explicit save, never autosave: the RPC
 * writes one audit row carrying the whole diff, and a keystroke is not a
 * decision worth recording.
 */
function profileForm(account) {
  const form = document.createElement('form');
  form.className = 'admin-card';
  form.id = 'account-profile-form';
  form.noValidate = true;
  form.dataset.userId = account.id;
  /* The version this form was loaded at, handed back on save. The RPC refuses a
     write whose expectation no longer matches (AD005) rather than silently
     overwriting what somebody else stored meanwhile — the row lock protects
     execution time, and this protects think time. */
  if (account.updated_at) form.dataset.updatedAt = account.updated_at;

  const fields = document.createElement('div');
  fields.className = 'admin-profile-fields';
  PROFILE_FIELDS.forEach(({ name, id, key }) => {
    const field = document.createElement('div');
    field.className = 'admin-profile-field';

    const label = document.createElement('label');
    label.className = 'admin-label';
    label.htmlFor = id;
    label.textContent = I18n.t(key);

    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'admin-input';
    input.id = id;
    input.name = name;
    // Matches _PROFILE_MAX_LENGTH in web/api/admin.py, which bounds it because
    // every value is copied into `before` AND `after` of a row nothing can ever
    // delete. Bounded here too, so an operator is stopped before the round trip
    // rather than after it.
    input.maxLength = 200;
    input.autocomplete = 'off';
    input.value = account[name] || '';

    field.append(label, input);
    fields.appendChild(field);
  });
  form.appendChild(fields);

  const actions = document.createElement('div');
  actions.className = 'admin-profile-actions';

  const save = document.createElement('button');
  save.type = 'submit';
  save.className = 'btn btn-primary btn-sm';
  save.id = 'account-profile-save';
  save.textContent = I18n.t('admin.account.saveProfile');
  actions.appendChild(save);

  const note = document.createElement('p');
  note.className = 'admin-form-hint';
  note.textContent = I18n.t('admin.account.profileHint');
  actions.appendChild(note);

  form.appendChild(actions);
  return form;
}

/** What the operator typed, shaped for the route. */
export function readProfileForm() {
  const form = el('account-profile-form');
  if (!form) return null;

  const patch = {};
  PROFILE_FIELDS.forEach(({ name, id }) => {
    const value = el(id)?.value.trim() ?? '';
    // Empty means null, not "". The column is nullable, and "never filled in"
    // and "set to the empty string" are different facts about a person — one of
    // which the reader's own profile form can produce and the other cannot.
    patch[name] = value === '' ? null : value;
  });
  if (form.dataset.updatedAt) patch.expected_updated_at = form.dataset.updatedAt;

  return { userId: form.dataset.userId, patch };
}

export function setProfileSaving(isSaving) {
  const save = el('account-profile-save');
  if (!save) return;
  save.disabled = isSaving;
  save.textContent = I18n.t(isSaving ? 'admin.settings.saving' : 'admin.account.saveProfile');
}

function renderAccountActivity(entries) {
  /* null is "we could not tell", [] is "nothing happened". Collapsing the two
     tells an operator that an account has a clean history when the truth is
     that the log was unreachable — the same false-absence the server side
     answers with a 503 rather than an empty list. */
  if (entries === null) {
    const failed = document.createElement('p');
    failed.className = 'admin-empty';
    failed.id = 'account-activity-failed';
    failed.textContent = I18n.t('admin.account.activityFailed');
    return failed;
  }

  if (!entries.length) {
    const empty = document.createElement('p');
    empty.className = 'admin-empty';
    empty.id = 'account-activity-empty';
    empty.textContent = I18n.t('admin.account.noActivity');
    return empty;
  }

  const table = document.createElement('table');
  table.className = 'admin-table';
  table.id = 'account-activity';

  /* A header, which this table never had — four unlabelled columns of dates and
     sentences is a record nobody can read across. The same column vocabulary as
     the Activity tab, minus the target: every row here is about one account and
     naming it four times says nothing. */
  const head = document.createElement('thead');
  const headRow = document.createElement('tr');
  ['columnWhen', 'columnWho', 'columnWhat', 'columnReason'].forEach((key) => {
    const th = document.createElement('th');
    th.scope = 'col';
    th.textContent = I18n.t(`admin.audit.${key}`);
    headRow.appendChild(th);
  });
  head.appendChild(headRow);

  const tbody = document.createElement('tbody');
  entries.forEach((entry) => {
    const row = document.createElement('tr');
    row.append(
      machineCell(exactWhen(entry.occurred_at)),
      machineCell(entry.actor_email || ''),
    );
    const what = document.createElement('td');
    what.textContent = describeAction(entry.action);
    const why = document.createElement('td');
    why.textContent = entry.note || '';
    row.append(what, why);
    tbody.appendChild(row);
  });

  table.append(head, tbody);

  // Wide content scrolls inside its own container; the page must never scroll
  // sideways, because a horizontal scrollbar on the document takes the whole
  // layout with it on a narrow screen.
  const scroll = document.createElement('div');
  scroll.className = 'admin-scroll';
  scroll.appendChild(table);
  return scroll;
}

export function showAccountMessage(message) {
  /* The panel only swaps on a SUCCESSFUL render, so without this the failure
     message is written into an element that is still hidden and the operator is
     told nothing at all. */
  const detail = openDetailPanel();
  if (!detail) return;

  detail.appendChild(backLink());

  const p = document.createElement('p');
  p.className = 'admin-empty';
  p.id = 'account-error';
  p.textContent = message;
  detail.appendChild(p);
}
