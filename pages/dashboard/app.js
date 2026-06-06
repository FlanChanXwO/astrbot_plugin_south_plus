import { api, ready } from './js/api.js';

const AUTOCOMPLETE_DEBOUNCE_MS = 220;
const FILTER_REFRESH_DEBOUNCE_MS = 400;
const PARTICIPANT_REFRESH_DEBOUNCE_MS = 400;

const state = {
  activePage: 'overview',
  loading: false,
  filters: {},
  draftFilters: {},
  items: [],
  overview: null,
  listRequestId: 0,
  filterDebounceTimer: null,
  toolbarRenderedFor: '',
  autocomplete: {
    openKey: '',
    items: [],
    loading: false,
    activeIndex: -1,
    timer: null,
    requestId: 0,
  },
  participantAutocomplete: {
    items: [],
    loading: false,
    activeIndex: -1,
    timer: null,
    requestId: 0,
    query: '',
  },
  participantPanel: {
    open: false,
    schedule: null,
    keyword: '',
    excluded: '',
    items: [],
    loading: false,
    requestId: 0,
    debounceTimer: null,
  },
};

const pages = [
  { id: 'overview', title: '概览', subtitle: '数据库状态与近期签到概况' },
  { id: 'accounts', title: '账号', subtitle: '绑定 UID、活跃账号与自动签到状态' },
  { id: 'groups', title: '群组', subtitle: 'Bot 观测到的群目录' },
  { id: 'schedules', title: '调度任务', subtitle: '签到结果推送订阅与运行开关' },
  { id: 'checkins', title: '签到历史', subtitle: '最近签到记录与失败排障信息' },
  { id: 'relations', title: '关系', subtitle: '用户与群组的观测关系' },
];

const pageConfigs = {
  accounts: {
    loader: api.accounts,
    filters: [
      { key: 'keyword', label: '关键词', type: 'text', placeholder: 'UID / 用户 / 平台', suggest: ['accounts', 'keyword'] },
      { key: 'platform', label: '平台', type: 'text', placeholder: 'aiocqhttp', suggest: ['accounts', 'platform'] },
      { key: 'active', label: '活跃', type: 'select', options: [['', '全部'], ['true', '是'], ['false', '否']] },
      { key: 'auto_checkin', label: '自动签到', type: 'select', options: [['', '全部'], ['true', '开启'], ['false', '关闭']] },
    ],
    columns: [
      ['sp_uid', 'UID'],
      ['account', '用户'],
      ['platform', '平台'],
      ['cookie_masked', 'Cookie'],
      ['is_active', '活跃', renderBool],
      ['auto_checkin', '自动签到', renderBool],
      ['updated_at', '更新'],
      ['actions', '操作', renderAccountActions],
    ],
  },
  groups: {
    loader: api.groups,
    filters: [
      { key: 'keyword', label: '关键词', type: 'text', placeholder: '群号 / 群名 / Bot', suggest: ['groups', 'keyword'] },
      { key: 'platform', label: '平台', type: 'text', placeholder: 'aiocqhttp', suggest: ['groups', 'platform'] },
      { key: 'bot_id', label: 'Bot ID', type: 'text', placeholder: 'self id', suggest: ['groups', 'bot_id'] },
    ],
    columns: [
      ['id', 'ID'],
      ['bot_id', 'Bot'],
      ['platform', '平台'],
      ['group_id', '群号'],
      ['group_name', '群名'],
      ['last_seen_at', '最后观测'],
    ],
  },
  schedules: {
    loader: api.schedules,
    filters: [
      { key: 'keyword', label: '关键词', type: 'text', placeholder: '会话 / task / cron', suggest: ['schedules', 'keyword'] },
      { key: 'task_key', label: '任务', type: 'text', placeholder: 'sp.checkin.all', suggest: ['schedules', 'task_key'] },
      { key: 'enabled', label: '启用', type: 'select', options: [['', '全部'], ['true', '是'], ['false', '否']] },
    ],
    columns: [
      ['id', 'ID'],
      ['umo', '会话'],
      ['task_key', '任务'],
      ['cron', 'Cron'],
      ['params_json', '参数', renderScheduleParams],
      ['enabled', '启用', renderBool],
      ['updated_at', '更新'],
      ['actions', '操作', renderScheduleActions],
    ],
  },
  checkins: {
    loader: api.checkins,
    filters: [
      { key: 'sp_uid', label: 'UID', type: 'text', placeholder: '2030219', suggest: ['checkins', 'sp_uid'] },
      { key: 'task_key', label: '任务', type: 'text', placeholder: 'sp.checkin.daily', suggest: ['checkins', 'task_key'] },
      { key: 'status', label: '状态', type: 'select', options: [['', '全部'], ['success', 'success'], ['failed', 'failed'], ['already_done', 'already_done']] },
      { key: 'period_key', label: '周期', type: 'text', placeholder: '2026-06-06 / 2026-W23', suggest: ['checkins', 'period_key'] },
    ],
    columns: [
      ['id', 'ID'],
      ['sp_uid', 'UID'],
      ['task_key', '任务'],
      ['period_key', '周期'],
      ['status', '状态', renderStatus],
      ['message', '消息', renderLong],
      ['error', '错误', renderLong],
      ['created_at', '时间'],
    ],
  },
  relations: {
    loader: api.userGroups,
    filters: [
      { key: 'sp_uid', label: 'UID', type: 'text', placeholder: '2030219', suggest: ['relations', 'sp_uid'] },
      { key: 'group_id', label: '关系群 ID', type: 'text', placeholder: '内部 group id', suggest: ['relations', 'group_id'] },
    ],
    columns: [
      ['id', 'ID'],
      ['sp_uid', 'UID'],
      ['account', '用户'],
      ['group_id', '群 ID'],
      ['group_external_id', '群号'],
      ['group_name', '群名'],
      ['platform', '平台'],
      ['last_seen_at', '最后观测'],
    ],
  },
};

const els = {
  nav: document.getElementById('nav-list'),
  title: document.getElementById('page-title'),
  subtitle: document.getElementById('page-subtitle'),
  refresh: document.getElementById('refresh-button'),
  overview: document.getElementById('overview'),
  toolbar: document.getElementById('toolbar'),
  panel: document.getElementById('table-panel'),
  head: document.getElementById('table-head'),
  body: document.getElementById('table-body'),
  empty: document.getElementById('empty-state'),
  toast: document.getElementById('toast'),
};

init();

async function init() {
  renderNav();
  bindRefresh();
  try {
    await ready();
    await loadPage('overview');
  } catch (error) {
    showToast(`初始化失败：${error.message}`, 'error');
  }
}

function renderNav() {
  els.nav.innerHTML = '';
  for (const page of pages) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'nav-item';
    button.textContent = page.title;
    button.dataset.page = page.id;
    button.addEventListener('click', () => loadPage(page.id));
    els.nav.appendChild(button);
  }
}

function bindRefresh() {
  els.refresh.addEventListener('click', () => loadPage(state.activePage, false));
}

async function loadPage(pageId, resetFilters = true) {
  const page = pages.find((item) => item.id === pageId) || pages[0];
  state.activePage = page.id;
  if (resetFilters) {
    state.filters = {};
    state.draftFilters = {};
    state.toolbarRenderedFor = '';
    closeAutocomplete();
  }
  updateShell(page);
  try {
    state.loading = true;
    if (page.id === 'overview') {
      await loadOverview();
    } else {
      await loadListPage();
    }
  } catch (error) {
    showToast(error.message || '加载失败', 'error');
  } finally {
    state.loading = false;
  }
}

function updateShell(page) {
  els.title.textContent = page.title;
  els.subtitle.textContent = page.subtitle;
  for (const button of els.nav.querySelectorAll('.nav-item')) {
    button.classList.toggle('active', button.dataset.page === page.id);
  }
}

async function loadOverview() {
  const result = await api.overview();
  state.overview = result.overview || {};
  els.overview.hidden = false;
  els.toolbar.hidden = true;
  els.panel.hidden = true;
  renderOverview();
}

function renderOverview() {
  const data = state.overview || {};
  const cards = [
    ['账号总数', data.accounts_total ?? 0],
    ['活跃账号', data.accounts_active ?? 0],
    ['自动签到账号', data.accounts_auto_checkin ?? 0],
    ['群组数', data.groups_total ?? 0],
    ['调度任务', `${data.schedules_enabled ?? 0}/${data.schedules_total ?? 0}`],
    ['近期记录', data.checkins_recent ?? 0],
  ];
  const status = data.checkins_by_status || {};
  els.overview.innerHTML = cards
    .map(([label, value]) => `<article class="metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></article>`)
    .join('') + `<article class="metric wide"><span>近期签到状态</span><strong>${escapeHtml(formatStatusCounts(status))}</strong></article>`;
}

async function loadListPage() {
  const config = pageConfigs[state.activePage];
  const requestId = state.listRequestId + 1;
  state.listRequestId = requestId;
  if (state.toolbarRenderedFor !== state.activePage) {
    renderToolbar(config);
    state.toolbarRenderedFor = state.activePage;
  }
  const result = await config.loader(state.filters);
  if (requestId !== state.listRequestId) return;
  state.items = result.items || [];
  closeParticipants();
  els.overview.hidden = true;
  els.toolbar.hidden = false;
  els.panel.hidden = false;
  renderTable(config);
}

function renderToolbar(config) {
  els.toolbar.innerHTML = '';
  for (const filter of config.filters) {
    const label = document.createElement('label');
    label.className = 'filter-field';
    label.textContent = filter.label;
    const input = filter.type === 'select' ? document.createElement('select') : document.createElement('input');
    input.name = filter.key;
    if (filter.type === 'select') {
      for (const [value, caption] of filter.options) {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = caption;
        input.appendChild(option);
      }
    } else {
      input.type = 'search';
      input.placeholder = filter.placeholder || '';
      input.autocomplete = 'off';
    }
    input.value = state.draftFilters[filter.key] ?? state.filters[filter.key] ?? '';
    if (filter.suggest) {
      const [resource, field] = filter.suggest;
      input.dataset.suggestResource = resource;
      input.dataset.suggestField = field;
      input.addEventListener('input', () => scheduleAutocomplete(input, filter.key, resource, field));
      input.addEventListener('focus', () => scheduleAutocomplete(input, filter.key, resource, field));
    }
    input.addEventListener('input', () => {
      state.draftFilters[filter.key] = input.value;
      queueFilterRefresh(config);
    });
    input.addEventListener('change', () => {
      state.draftFilters[filter.key] = input.value;
      queueFilterRefresh(config);
    });
    input.addEventListener('keydown', (event) => {
      if (event.isComposing) return;
      if (event.key === 'Enter') {
        event.preventDefault();
        if (acceptActiveAutocomplete(config)) return;
        applyFilters(config);
      } else if (event.key === 'ArrowDown') {
        if (moveAutocomplete(1)) event.preventDefault();
      } else if (event.key === 'ArrowUp') {
        if (moveAutocomplete(-1)) event.preventDefault();
      } else if (event.key === 'Escape') {
        closeAutocomplete();
      }
    });
    input.addEventListener('blur', () => window.setTimeout(closeAutocomplete, 120));
    if (filter.suggest) label.classList.add('autocomplete-field');
    label.appendChild(input);
    label.appendChild(renderAutocompleteMenu(filter.key));
    els.toolbar.appendChild(label);
  }
  const search = document.createElement('button');
  search.className = 'primary-button';
  search.type = 'button';
  search.textContent = '搜索';
  search.addEventListener('click', () => applyFilters(config));
  els.toolbar.appendChild(search);
  const clear = document.createElement('button');
  clear.className = 'ghost-button';
  clear.type = 'button';
  clear.textContent = '清空';
  clear.addEventListener('click', () => {
    state.filters = {};
    state.draftFilters = {};
    state.toolbarRenderedFor = '';
    closeAutocomplete();
    loadListPage();
  });
  els.toolbar.appendChild(clear);
}

function applyFilters(config) {
  window.clearTimeout(state.filterDebounceTimer);
  const filters = {};
  for (const filter of config.filters) {
    const value = els.toolbar.querySelector(`[name="${filter.key}"]`)?.value?.trim();
    if (value) filters[filter.key] = value;
  }
  state.filters = filters;
  state.draftFilters = { ...filters };
  loadListPage();
}

function queueFilterRefresh(config) {
  window.clearTimeout(state.filterDebounceTimer);
  state.filterDebounceTimer = window.setTimeout(
    () => applyFilters(config),
    FILTER_REFRESH_DEBOUNCE_MS,
  );
}

function renderAutocompleteMenu(filterKey) {
  const menu = document.createElement('div');
  menu.className = 'autocomplete-menu';
  menu.dataset.autocompleteFor = filterKey;
  menu.hidden = true;
  return menu;
}

function scheduleAutocomplete(input, filterKey, resource, field) {
  const query = input.value.trim();
  const key = `${state.activePage}:${filterKey}`;
  if (state.autocomplete.timer) window.clearTimeout(state.autocomplete.timer);
  state.autocomplete.openKey = key;
  state.autocomplete.activeIndex = -1;
  if (!query) {
    state.autocomplete.items = [];
    state.autocomplete.loading = false;
    state.autocomplete.requestId += 1;
    renderAutocomplete(input, filterKey);
    return;
  }
  state.autocomplete.loading = true;
  renderAutocomplete(input, filterKey);
  const requestId = state.autocomplete.requestId + 1;
  state.autocomplete.requestId = requestId;
  state.autocomplete.timer = window.setTimeout(async () => {
    try {
      const result = await api.suggestions({
        resource,
        field,
        q: query,
        limit: 10,
      });
      if (requestId !== state.autocomplete.requestId) return;
      state.autocomplete.items = result.items || [];
      state.autocomplete.activeIndex = state.autocomplete.items.length ? 0 : -1;
    } catch {
      if (requestId === state.autocomplete.requestId) state.autocomplete.items = [];
    } finally {
      if (requestId === state.autocomplete.requestId) {
        state.autocomplete.loading = false;
        renderAutocomplete(input, filterKey);
      }
    }
  }, AUTOCOMPLETE_DEBOUNCE_MS);
}

function renderAutocomplete(input, filterKey) {
  const key = `${state.activePage}:${filterKey}`;
  const menu = els.toolbar.querySelector(`[data-autocomplete-for="${filterKey}"]`);
  if (!menu) return;
  if (!input.value.trim()) {
    menu.hidden = true;
    menu.innerHTML = '';
    return;
  }
  if (state.autocomplete.openKey !== key) {
    menu.hidden = true;
    return;
  }
  if (state.autocomplete.loading) {
    menu.hidden = false;
    menu.innerHTML = '<div class="autocomplete-empty">搜索中...</div>';
    return;
  }
  if (!state.autocomplete.items.length) {
    menu.hidden = false;
    menu.innerHTML = '<div class="autocomplete-empty">没有建议</div>';
    return;
  }
  menu.hidden = false;
  menu.innerHTML = state.autocomplete.items
    .map((item, index) => {
      const active = index === state.autocomplete.activeIndex ? ' active' : '';
      return `<button class="autocomplete-option${active}" type="button" data-autocomplete-index="${index}"><span class="autocomplete-option-main">${escapeHtml(item.label || item.value)}</span><span class="autocomplete-option-kind">${escapeHtml(item.kind || '')}</span><span class="autocomplete-option-meta">${escapeHtml(formatAutocompleteMeta(item))}</span></button>`;
    })
    .join('');
  for (const button of menu.querySelectorAll('[data-autocomplete-index]')) {
    button.addEventListener('mousedown', (event) => {
      event.preventDefault();
      const accepted = acceptAutocompleteIndex(
        Number(button.dataset.autocompleteIndex),
        input,
        filterKey,
      );
      if (accepted) applyFilters(pageConfigs[state.activePage]);
    });
  }
}

function moveAutocomplete(delta) {
  const total = state.autocomplete.items.length;
  if (!total) return false;
  const active = document.activeElement;
  if (!active?.name || state.autocomplete.openKey !== `${state.activePage}:${active.name}`) {
    return false;
  }
  state.autocomplete.activeIndex = (state.autocomplete.activeIndex + delta + total) % total;
  renderAutocomplete(active, active.name);
  return true;
}

function acceptActiveAutocomplete(config) {
  const active = document.activeElement;
  if (!active?.name || state.autocomplete.activeIndex < 0) return false;
  if (state.autocomplete.openKey !== `${state.activePage}:${active.name}`) return false;
  const accepted = acceptAutocompleteIndex(state.autocomplete.activeIndex, active, active.name);
  if (accepted) applyFilters(config);
  return accepted;
}

function acceptAutocompleteIndex(index, input, filterKey) {
  const item = state.autocomplete.items[index];
  const value = String(item?.value || '').trim();
  if (!value) return false;
  input.value = value;
  state.draftFilters[filterKey] = value;
  closeAutocomplete();
  return true;
}

function closeAutocomplete() {
  if (state.autocomplete.timer) window.clearTimeout(state.autocomplete.timer);
  state.autocomplete.openKey = '';
  state.autocomplete.items = [];
  state.autocomplete.loading = false;
  state.autocomplete.activeIndex = -1;
  state.autocomplete.requestId += 1;
  for (const menu of els.toolbar?.querySelectorAll?.('.autocomplete-menu') || []) {
    menu.hidden = true;
    menu.innerHTML = '';
  }
}

function renderTable(config) {
  els.head.innerHTML = `<tr>${config.columns.map(([, label]) => `<th>${escapeHtml(label)}</th>`).join('')}</tr>`;
  els.body.innerHTML = '';
  for (const item of state.items) {
    const row = document.createElement('tr');
    for (const [key, , renderer] of config.columns) {
      const cell = document.createElement('td');
      cell.innerHTML = renderer ? renderer(item[key], item) : escapeHtml(item[key] ?? '');
      row.appendChild(cell);
    }
    bindRowActions(row, item);
    els.body.appendChild(row);
  }
  renderParticipantsPanel();
  els.empty.hidden = state.items.length > 0;
}

function bindRowActions(row, item) {
  for (const button of row.querySelectorAll('[data-action]')) {
    button.addEventListener('click', async () => {
      const action = button.dataset.action;
      try {
        if (action === 'switch-account') {
          await api.switchAccount(item);
          showToast('已切换活跃账号');
        } else if (action === 'toggle-account') {
          await api.setAccountAutoCheckin(item.sp_uid, !item.auto_checkin);
          showToast('已更新自动签到');
        } else if (action === 'delete-account') {
          if (!window.confirm(`删除账号 ${item.sp_uid}？`)) return;
          await api.deleteAccount(item.sp_uid);
          showToast('已删除账号');
        } else if (action === 'toggle-schedule') {
          await api.setScheduleEnabled(item.id, !item.enabled);
          showToast('已更新调度');
        } else if (action === 'show-participants') {
          await openParticipants(item);
          return;
        } else if (action === 'delete-schedule') {
          if (!window.confirm(`删除调度 #${item.id}？`)) return;
          await api.deleteSchedule(item.id);
          showToast('已删除调度');
        }
        await loadListPage();
      } catch (error) {
        showToast(error.message || '操作失败', 'error');
      }
    });
  }
}

function renderBool(value) {
  return `<span class="chip ${value ? 'ok' : 'muted'}">${value ? '是' : '否'}</span>`;
}

function renderStatus(value) {
  const status = String(value || '');
  const cls = status === 'failed' ? 'bad' : status === 'success' || status === 'already_done' ? 'ok' : 'muted';
  return `<span class="chip ${cls}">${escapeHtml(status)}</span>`;
}

function renderCode(value) {
  return `<code>${escapeHtml(value || '')}</code>`;
}

function renderScheduleParams(value) {
  return `<details><summary>查看参数</summary>${renderCode(value)}</details>`;
}

function renderLong(value) {
  const text = String(value || '');
  if (!text) return '';
  return `<details><summary>${escapeHtml(text.slice(0, 28))}${text.length > 28 ? '...' : ''}</summary><pre>${escapeHtml(text)}</pre></details>`;
}

function renderAccountActions(_value, item) {
  return [
    `<button class="row-button" data-action="switch-account" ${item.is_active ? 'disabled' : ''}>切换</button>`,
    `<button class="row-button" data-action="toggle-account">${item.auto_checkin ? '全局停签' : '全局恢复'}</button>`,
    `<button class="row-button danger" data-action="delete-account">删除</button>`,
  ].join('');
}

function renderScheduleActions(_value, item) {
  return [
    `<button class="row-button" data-action="show-participants">参与账号</button>`,
    `<button class="row-button" data-action="toggle-schedule">${item.enabled ? '停用' : '启用'}</button>`,
    `<button class="row-button danger" data-action="delete-schedule">删除</button>`,
  ].join('');
}

async function openParticipants(schedule) {
  state.participantPanel.open = true;
  state.participantPanel.schedule = schedule;
  state.participantPanel.keyword = '';
  state.participantPanel.excluded = '';
  state.participantPanel.items = [];
  renderParticipantsPanel();
  await loadParticipants();
}

function closeParticipants() {
  if (state.participantPanel.debounceTimer) {
    window.clearTimeout(state.participantPanel.debounceTimer);
  }
  state.participantPanel.open = false;
  state.participantPanel.schedule = null;
  state.participantPanel.items = [];
  state.participantPanel.loading = false;
  closeParticipantAutocomplete();
}

async function loadParticipants() {
  const panel = state.participantPanel;
  if (!panel.open || !panel.schedule) return;
  const requestId = panel.requestId + 1;
  panel.requestId = requestId;
  panel.loading = true;
  renderParticipantList();
  try {
    const result = await api.scheduleParticipants({
      schedule_id: panel.schedule.id,
      keyword: panel.keyword,
      excluded: panel.excluded,
    });
    if (requestId !== panel.requestId) return;
    panel.items = result.items || [];
  } catch (error) {
    showToast(error.message || '参与账号加载失败', 'error');
  } finally {
    if (requestId === panel.requestId) {
      panel.loading = false;
      renderParticipantList();
    }
  }
}

function renderParticipantsPanel() {
  const existing = els.panel.querySelector('.participants-panel');
  const panel = state.participantPanel;
  if (!panel.open || !panel.schedule) {
    if (existing) existing.remove();
    return;
  }
  if (existing?.dataset.scheduleId === String(panel.schedule.id)) {
    renderParticipantList();
    return;
  }
  if (existing) existing.remove();

  const section = document.createElement('section');
  section.className = 'participants-panel';
  section.dataset.scheduleId = String(panel.schedule.id);
  section.innerHTML = `
    <div class="participants-header">
      <div>
        <h2>参与账号</h2>
        <p>#${escapeHtml(panel.schedule.id)} · ${escapeHtml(panel.schedule.umo)}</p>
      </div>
      <button class="icon-button" type="button" data-participant-close title="关闭" aria-label="关闭">×</button>
    </div>
    <div class="participant-toolbar">
      <label class="filter-field autocomplete-field">搜索账号
        <input name="participant-keyword" type="search" autocomplete="off" placeholder="UID / 用户 / 平台" value="${escapeHtml(panel.keyword)}" />
        <div class="autocomplete-menu" data-participant-autocomplete hidden></div>
      </label>
      <label class="filter-field">排除状态
        <select name="participant-excluded">
          <option value="" ${panel.excluded === '' ? 'selected' : ''}>全部</option>
          <option value="true" ${panel.excluded === 'true' ? 'selected' : ''}>已排除</option>
          <option value="false" ${panel.excluded === 'false' ? 'selected' : ''}>参与中</option>
        </select>
      </label>
      <button class="primary-button" type="button" data-participant-search>搜索</button>
    </div>
    <div class="participant-list"></div>
  `;
  els.panel.appendChild(section);
  bindParticipantPanel(section);
  renderParticipantList();
}

function bindParticipantPanel(section) {
  section.querySelector('[data-participant-close]')?.addEventListener('click', () => {
    closeParticipants();
    renderParticipantsPanel();
  });

  const keywordInput = section.querySelector('[name="participant-keyword"]');
  const excludedSelect = section.querySelector('[name="participant-excluded"]');
  const refresh = () => {
    state.participantPanel.keyword = keywordInput.value.trim();
    state.participantPanel.excluded = excludedSelect.value;
    loadParticipants();
  };
  const debounceRefresh = () => {
    window.clearTimeout(state.participantPanel.debounceTimer);
    state.participantPanel.debounceTimer = window.setTimeout(
      refresh,
      PARTICIPANT_REFRESH_DEBOUNCE_MS,
    );
  };
  keywordInput.addEventListener('input', () => {
    scheduleParticipantAutocomplete(keywordInput);
    debounceRefresh();
  });
  keywordInput.addEventListener('focus', () => scheduleParticipantAutocomplete(keywordInput));
  keywordInput.addEventListener('keydown', (event) => {
    if (event.isComposing) return;
    if (event.key === 'Enter') {
      event.preventDefault();
      if (acceptActiveParticipantAutocomplete(keywordInput)) {
        refresh();
        return;
      }
      refresh();
    } else if (event.key === 'ArrowDown') {
      if (moveParticipantAutocomplete(1, keywordInput)) event.preventDefault();
    } else if (event.key === 'ArrowUp') {
      if (moveParticipantAutocomplete(-1, keywordInput)) event.preventDefault();
    } else if (event.key === 'Escape') {
      closeParticipantAutocomplete();
    }
  });
  keywordInput.addEventListener('blur', () => window.setTimeout(closeParticipantAutocomplete, 120));
  excludedSelect.addEventListener('change', refresh);
  section.querySelector('[data-participant-search]')?.addEventListener('click', refresh);

  bindParticipantActions(section);
}

function renderParticipantList() {
  const list = els.panel.querySelector('.participant-list');
  if (!list) return;
  const panel = state.participantPanel;
  list.innerHTML = panel.loading
    ? '<div class="empty-state">加载中</div>'
    : renderParticipantRows(panel.items);
  bindParticipantActions(list);
}

function bindParticipantActions(container) {
  for (const button of container.querySelectorAll('[data-participant-action]')) {
    button.addEventListener('click', async () => {
      const spUid = button.dataset.spUid;
      const excluded = button.dataset.participantAction === 'exclude';
      try {
        await api.setScheduleParticipantExcluded(
          state.participantPanel.schedule.id,
          spUid,
          excluded,
        );
        showToast(excluded ? '已排除此会话自动签到' : '已恢复此会话自动签到');
        await loadParticipants();
      } catch (error) {
        showToast(error.message || '操作失败', 'error');
      }
    });
  }
}

function scheduleParticipantAutocomplete(input) {
  const query = input.value.trim();
  if (state.participantAutocomplete.timer) {
    window.clearTimeout(state.participantAutocomplete.timer);
  }
  state.participantAutocomplete.query = query;
  state.participantAutocomplete.activeIndex = -1;
  if (!query) {
    state.participantAutocomplete.items = [];
    state.participantAutocomplete.loading = false;
    state.participantAutocomplete.requestId += 1;
    renderParticipantAutocomplete(input);
    return;
  }
  state.participantAutocomplete.loading = true;
  renderParticipantAutocomplete(input);
  const requestId = state.participantAutocomplete.requestId + 1;
  state.participantAutocomplete.requestId = requestId;
  state.participantAutocomplete.timer = window.setTimeout(async () => {
    try {
      const result = await api.suggestions({
        resource: 'participants',
        field: 'keyword',
        q: query,
        limit: 10,
      });
      if (requestId !== state.participantAutocomplete.requestId) return;
      state.participantAutocomplete.items = result.items || [];
      state.participantAutocomplete.activeIndex = state.participantAutocomplete.items.length ? 0 : -1;
    } catch {
      if (requestId === state.participantAutocomplete.requestId) {
        state.participantAutocomplete.items = [];
      }
    } finally {
      if (requestId === state.participantAutocomplete.requestId) {
        state.participantAutocomplete.loading = false;
        renderParticipantAutocomplete(input);
      }
    }
  }, AUTOCOMPLETE_DEBOUNCE_MS);
}

function renderParticipantAutocomplete(input) {
  const menu = input
    .closest('.participants-panel')
    ?.querySelector('[data-participant-autocomplete]');
  if (!menu) return;
  if (state.participantAutocomplete.loading) {
    menu.hidden = false;
    menu.innerHTML = '<div class="autocomplete-empty">搜索中...</div>';
    return;
  }
  if (!state.participantAutocomplete.query) {
    menu.hidden = true;
    menu.innerHTML = '';
    return;
  }
  if (!state.participantAutocomplete.items.length) {
    menu.hidden = false;
    menu.innerHTML = '<div class="autocomplete-empty">没有建议</div>';
    return;
  }
  menu.hidden = false;
  menu.innerHTML = state.participantAutocomplete.items
    .map((item, index) => {
      const active = index === state.participantAutocomplete.activeIndex ? ' active' : '';
      return `<button class="autocomplete-option${active}" type="button" data-participant-autocomplete-index="${index}"><span class="autocomplete-option-main">${escapeHtml(item.label || item.value)}</span><span class="autocomplete-option-kind">${escapeHtml(item.kind || '')}</span><span class="autocomplete-option-meta">${escapeHtml(formatAutocompleteMeta(item))}</span></button>`;
    })
    .join('');
  for (const button of menu.querySelectorAll('[data-participant-autocomplete-index]')) {
    button.addEventListener('mousedown', (event) => {
      event.preventDefault();
      const accepted = acceptParticipantAutocompleteIndex(
        Number(button.dataset.participantAutocompleteIndex),
        input,
      );
      if (accepted) loadParticipants();
    });
  }
}

function moveParticipantAutocomplete(delta, input) {
  const total = state.participantAutocomplete.items.length;
  if (!total) return false;
  state.participantAutocomplete.activeIndex = (
    state.participantAutocomplete.activeIndex + delta + total
  ) % total;
  renderParticipantAutocomplete(input);
  return true;
}

function acceptActiveParticipantAutocomplete(input) {
  if (state.participantAutocomplete.activeIndex < 0) return false;
  return acceptParticipantAutocompleteIndex(state.participantAutocomplete.activeIndex, input);
}

function acceptParticipantAutocompleteIndex(index, input) {
  const item = state.participantAutocomplete.items[index];
  const value = String(item?.value || '').trim();
  if (!value) return false;
  input.value = value;
  state.participantPanel.keyword = value;
  closeParticipantAutocomplete();
  return true;
}

function closeParticipantAutocomplete() {
  if (state.participantAutocomplete.timer) {
    window.clearTimeout(state.participantAutocomplete.timer);
  }
  state.participantAutocomplete.items = [];
  state.participantAutocomplete.loading = false;
  state.participantAutocomplete.activeIndex = -1;
  state.participantAutocomplete.query = '';
  state.participantAutocomplete.requestId += 1;
  for (const menu of els.panel?.querySelectorAll?.('[data-participant-autocomplete]') || []) {
    menu.hidden = true;
    menu.innerHTML = '';
  }
}

function renderParticipantRows(items) {
  if (!items.length) return '<div class="empty-state">暂无参与账号</div>';
  return items
    .map((item) => {
      const action = item.excluded
        ? `<button class="row-button" data-participant-action="restore" data-sp-uid="${escapeHtml(item.sp_uid)}">恢复</button>`
        : `<button class="row-button danger" data-participant-action="exclude" data-sp-uid="${escapeHtml(item.sp_uid)}">排除</button>`;
      return `
        <article class="participant-row">
          <div>
            <strong>${escapeHtml(item.sp_uid)}</strong>
            <span>${escapeHtml(item.account)} · ${escapeHtml(item.platform)}</span>
          </div>
          <div class="participant-status">
            ${renderBool(item.auto_checkin)}
            <span class="chip ${item.excluded ? 'bad' : 'ok'}">${item.excluded ? '已排除' : '参与中'}</span>
            <span class="chip ${item.will_run ? 'ok' : 'muted'}">${item.will_run ? '会执行' : '不会执行'}</span>
            ${action}
          </div>
        </article>
      `;
    })
    .join('');
}

function showToast(message, type = 'success') {
  els.toast.textContent = message;
  els.toast.className = `toast ${type}`;
  els.toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    els.toast.hidden = true;
  }, 2600);
}

function formatStatusCounts(status) {
  const parts = Object.entries(status).map(([key, value]) => `${key}: ${value}`);
  return parts.length ? parts.join(' / ') : '暂无记录';
}

function formatAutocompleteMeta(item) {
  return Object.values(item?.meta || {})
    .map((value) => String(value || '').trim())
    .filter(Boolean)
    .join(' · ');
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}
