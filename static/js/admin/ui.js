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
export function renderSettings({ settings, overrides, defaults, allowed_models: allowedModels }) {
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

    const seen = machineCell(
      user.last_sign_in_at
        ? new Date(user.last_sign_in_at).toLocaleDateString(I18n.lang)
        : I18n.t('admin.people.never'),
    );

    const actions = document.createElement('td');
    actions.className = 'admin-row-actions';
    // Disabled for yourself rather than hidden: an operator should be able to
    // see the control exists and why it is not available to them, instead of
    // wondering whether the console forgot to draw it.
    actions.append(
      actionButton(
        I18n.t(user.role === 'admin' ? 'admin.people.demote' : 'admin.people.promote'),
        { action: user.role === 'admin' ? 'demote' : 'promote', id: user.id,
          danger: user.role === 'admin', disabled: isSelf },
      ),
      actionButton(
        I18n.t(user.is_disabled ? 'admin.people.enable' : 'admin.people.disable'),
        { action: user.is_disabled ? 'enable' : 'disable', id: user.id,
          danger: !user.is_disabled, disabled: isSelf },
      ),
    );

    row.append(email, role, access, seen, actions);
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

function definition(list, label, value, { machine = false } = {}) {
  const dt = document.createElement('dt');
  dt.textContent = label;
  const dd = document.createElement('dd');
  if (machine && value) dd.appendChild(machineValue(value));
  else dd.textContent = value || I18n.t('admin.account.notSet');
  list.append(dt, dd);
}

function formatWhen(value) {
  return value ? new Date(value).toLocaleString(I18n.lang) : null;
}

export function showAccountList() {
  const list = el('people-list');
  const detail = el('people-detail');
  if (list) list.hidden = false;
  if (detail) { detail.hidden = true; detail.textContent = ''; }
  const search = el('people-search');
  if (search) search.hidden = false;
}

let currentSelfId = null;

export function renderAccountDetail(account, entries, selfId = null) {
  currentSelfId = selfId ?? currentSelfId;
  const list = el('people-list');
  const detail = el('people-detail');
  if (!detail) return;

  if (list) list.hidden = true;
  // Searching a list you cannot see is a control with nothing behind it.
  const search = el('people-search');
  if (search) search.hidden = true;
  detail.hidden = false;
  detail.textContent = '';

  const back = document.createElement('button');
  back.type = 'button';
  back.id = 'account-back';
  back.className = 'admin-tab';
  back.textContent = I18n.t('admin.account.back');
  detail.appendChild(back);

  const heading = document.createElement('h2');
  heading.className = 'admin-heading';
  heading.id = 'account-heading';
  heading.tabIndex = -1;
  heading.appendChild(machineValue(account.email));
  detail.appendChild(heading);

  /* Zone 1 — identity, read-only. Facts an operator needs before deciding
     anything, none of which the list shows. */
  const identity = document.createElement('h3');
  identity.className = 'admin-subheading';
  identity.textContent = I18n.t('admin.account.identityHeading');
  detail.appendChild(identity);

  const facts = document.createElement('dl');
  facts.className = 'admin-definitions';
  definition(facts, I18n.t('admin.account.created'), formatWhen(account.created_at), { machine: true });
  definition(facts, I18n.t('admin.account.lastSignIn'),
    formatWhen(account.last_sign_in_at) || I18n.t('admin.people.never'), { machine: true });
  definition(facts, I18n.t('admin.account.confirmed'),
    formatWhen(account.email_confirmed_at) || I18n.t('admin.account.notConfirmed'), { machine: true });
  // Fetched and previously not drawn. An operator deciding whether an account is
  // dormant wants this, and a field returned but never shown is privileged data
  // carried for no reason.
  definition(facts, I18n.t('admin.account.lastSeen'),
    formatWhen(account.last_seen_at) || I18n.t('admin.people.never'), { machine: true });

  if (account.has_profile) {
    definition(facts, I18n.t('admin.roleLabel'),
      I18n.t(account.role === 'admin' ? 'admin.people.roleAdmin' : 'admin.people.roleUser'));
    definition(facts, I18n.t('admin.account.standing'),
      I18n.t(account.is_disabled ? 'admin.people.accessDisabled' : 'admin.people.accessAllowed'));
    if (account.is_disabled) {
      definition(facts, I18n.t('admin.account.disabledAt'),
        formatWhen(account.disabled_at), { machine: true });
      definition(facts, I18n.t('admin.account.disabledBy'), account.disabled_by_email, { machine: true });
      definition(facts, I18n.t('admin.account.disabledReason'), account.disabled_reason);
    }
  }
  detail.appendChild(facts);

  /* The state the list cannot show at all: `admin_list_users` coalesces the
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

  /* Zone 2 — profile. Read-only in this step: showing it is most of the value,
     and editing another person's own description of themselves is a change with
     its own audit shape. */
  if (account.has_profile) {
    const profile = document.createElement('h3');
    profile.className = 'admin-subheading';
    profile.textContent = I18n.t('admin.account.profileHeading');
    detail.appendChild(profile);

    const fields = document.createElement('dl');
    fields.className = 'admin-definitions';
    definition(fields, I18n.t('admin.account.fullName'), account.full_name);
    definition(fields, I18n.t('admin.account.organization'), account.organization);
    definition(fields, I18n.t('admin.account.specialization'), account.specialization);
    detail.appendChild(fields);
  }

  /* Zone 3 — actions, in increasing severity. Last on the page on purpose:
     an operator reads who this is and what state they are in before they get
     the controls that change it. */
  const actionsHeading = document.createElement('h3');
  actionsHeading.className = 'admin-subheading';
  actionsHeading.textContent = I18n.t('admin.account.actionsHeading');
  detail.appendChild(actionsHeading);

  const actions = document.createElement('div');
  actions.className = 'admin-row-actions';
  actions.id = 'account-actions';

  const reset = document.createElement('button');
  reset.type = 'button';
  reset.className = 'admin-row-action';
  reset.id = 'account-send-reset';
  reset.dataset.action = 'send-reset';
  reset.dataset.userId = account.id;
  reset.textContent = I18n.t('admin.account.sendReset');
  actions.appendChild(reset);

  if (account.has_profile) {
    const isSelf = account.id === currentSelfId;
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
  detail.appendChild(actions);

  const hint = document.createElement('p');
  hint.className = 'admin-form-hint';
  hint.id = 'account-no-password-hint';
  hint.textContent = I18n.t('admin.account.noPasswordHint');
  detail.appendChild(hint);

  /* And what is deliberately missing. An operator mid-incident should not have
     to work out for themselves that the console cannot end a session. */
  const absent = document.createElement('div');
  absent.className = 'admin-notice';
  absent.id = 'account-absent';
  const absentTitle = document.createElement('strong');
  absentTitle.textContent = I18n.t('admin.account.absentHeading');
  const absentList = document.createElement('ul');
  [I18n.t('admin.account.absentRevoke'), I18n.t('admin.account.absentEmailChange')]
    .forEach((text) => {
      const li = document.createElement('li');
      li.textContent = text;
      absentList.appendChild(li);
    });
  absent.append(absentTitle, absentList);
  detail.appendChild(absent);

  /* Zone 4 — what has been done to this account. The same query as the global
     log with a filter, and this is the page it belongs on: "what happened to
     this person" had no surface anywhere before. */
  const activity = document.createElement('h3');
  activity.className = 'admin-subheading';
  activity.textContent = I18n.t('admin.account.activityHeading');
  detail.appendChild(activity);
  detail.appendChild(renderAccountActivity(entries));

  heading.focus();
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
  const tbody = document.createElement('tbody');

  entries.forEach((entry) => {
    const row = document.createElement('tr');
    row.append(
      machineCell(new Date(entry.occurred_at).toLocaleString(I18n.lang)),
      machineCell(entry.actor_email || ''),
    );
    const what = document.createElement('td');
    what.textContent = describeAction(entry.action);
    const why = document.createElement('td');
    why.textContent = entry.note || '';
    row.append(what, why);
    tbody.appendChild(row);
  });

  table.appendChild(tbody);
  return table;
}

export function showAccountMessage(message) {
  const detail = el('people-detail');
  if (!detail) return;

  /* The panel only swaps on a SUCCESSFUL render, so without these two lines the
     failure message is written into an element that is still hidden and the
     operator is told nothing at all. */
  const list = el('people-list');
  if (list) list.hidden = true;
  detail.hidden = false;
  detail.textContent = '';

  const back = document.createElement('button');
  back.type = 'button';
  back.id = 'account-back';
  back.className = 'admin-tab';
  back.textContent = I18n.t('admin.account.back');
  detail.appendChild(back);

  const p = document.createElement('p');
  p.className = 'admin-empty';
  p.id = 'account-error';
  p.textContent = message;
  detail.appendChild(p);
}
