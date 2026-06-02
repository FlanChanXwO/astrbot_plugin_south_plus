const bridge = window.AstrBotPluginPage;
const rows = document.getElementById("rows");
const statusBox = document.getElementById("status");
const form = document.getElementById("credential-form");

await bridge.ready();
await loadCredentials();

document.getElementById("refresh").addEventListener("click", loadCredentials);

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = new FormData(form);
  await bridge.apiPost("credentials", {
    user_key: data.get("user_key"),
    unified_msg_origin: data.get("unified_msg_origin"),
    username: data.get("username"),
    cookie: data.get("cookie"),
    schedule_time: data.get("schedule_time"),
    enabled: data.get("enabled") === "on",
  });
  form.reset();
  form.elements.enabled.checked = true;
  await loadCredentials();
});

async function loadCredentials() {
  statusBox.textContent = "加载中...";
  const result = await bridge.apiGet("credentials");
  rows.innerHTML = "";
  for (const item of result.items) {
    rows.appendChild(renderRow(item));
  }
  statusBox.textContent = result.items.length ? "" : "暂无凭证。";
}

function renderRow(item) {
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td>${escapeHtml(item.user_key)}</td>
    <td>${escapeHtml(item.username || "")}</td>
    <td>${escapeHtml(item.cookie_masked || "")}</td>
    <td>${item.enabled ? "是" : "否"}</td>
    <td>${escapeHtml(item.schedule_time || "")}</td>
    <td>${escapeHtml(`${item.last_status || ""} ${item.last_message || ""}`)}</td>
    <td>
      <button data-action="toggle">${item.enabled ? "停用" : "启用"}</button>
      <button data-action="delete">删除</button>
    </td>
  `;
  tr.querySelector('[data-action="toggle"]').addEventListener("click", async () => {
    await bridge.apiPost("credentials/toggle", {
      user_key: item.user_key,
      enabled: !item.enabled,
    });
    await loadCredentials();
  });
  tr.querySelector('[data-action="delete"]').addEventListener("click", async () => {
    await bridge.apiPost("credentials/delete", { user_key: item.user_key });
    await loadCredentials();
  });
  return tr;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

