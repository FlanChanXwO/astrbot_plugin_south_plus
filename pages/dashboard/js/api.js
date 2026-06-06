function getBridge() {
  return typeof window !== 'undefined' ? window.AstrBotPluginPage || null : null;
}

export async function ready() {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    const bridge = getBridge();
    if (bridge) return await bridge.ready();
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error('AstrBotPluginPage bridge not available');
}

function requireBridge() {
  const bridge = getBridge();
  if (!bridge) throw new Error('AstrBotPluginPage bridge not available');
  return bridge;
}

function cleanParams(params = {}) {
  const cleaned = {};
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    cleaned[key] = value;
  }
  return cleaned;
}

async function handle(result) {
  if (result && result.ok === false) {
    throw new Error(result.message || result.error || '操作失败');
  }
  return result || {};
}

export async function apiGet(path, params = {}) {
  const result = await requireBridge().apiGet(path, cleanParams(params));
  return await handle(result);
}

export async function apiPost(path, payload = {}) {
  const result = await requireBridge().apiPost(path, payload);
  return await handle(result);
}

export const api = {
  overview: () => apiGet('dashboard/overview'),
  accounts: (filters) => apiGet('accounts', filters),
  groups: (filters) => apiGet('groups', filters),
  userGroups: (filters) => apiGet('user-groups', filters),
  schedules: (filters) => apiGet('schedules', filters),
  scheduleParticipants: (filters) => apiGet('schedules/participants', filters),
  checkins: (filters) => apiGet('checkins', filters),
  suggestions: (filters) => apiGet('suggestions', filters),
  deleteAccount: (spUid) => apiPost('accounts/delete', { sp_uid: spUid }),
  switchAccount: (item) =>
    apiPost('accounts/switch', {
      account: item.account,
      platform: item.platform,
      sp_uid: item.sp_uid,
    }),
  setAccountAutoCheckin: (spUid, enabled) =>
    apiPost('accounts/auto-checkin', { sp_uid: spUid, enabled }),
  setScheduleEnabled: (id, enabled) =>
    apiPost('schedules/enabled', { id, enabled }),
  setScheduleParticipantExcluded: (scheduleId, spUid, excluded) =>
    apiPost('schedules/participants/excluded', {
      schedule_id: scheduleId,
      sp_uid: spUid,
      excluded,
    }),
  deleteSchedule: (id) => apiPost('schedules/delete', { id }),
};
