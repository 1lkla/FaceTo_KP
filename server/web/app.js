/* ============================================================
 * FaceTo KP 前端 SPA —— 五屏（对应前端画布功能模块）
 * S1 导入岗位 → S2 岗位画像 → S3 备考计划/面经 → S4 定向刷题 → S5 模拟面试
 * 屏间过渡：视图级 enter 动画 + 骨架屏 + 进度条缓动 + SSE 打字机
 * ============================================================ */
"use strict";

const API = "/api/v1";
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/* ---------------- 状态 ---------------- */
const state = {
  token: localStorage.getItem("fk_token") || "",
  user: JSON.parse(localStorage.getItem("fk_user") || "null"),
  jobId: +(localStorage.getItem("fk_job") || 0),
  planId: +(localStorage.getItem("fk_plan") || 0),
};

/* ---------------- API ---------------- */
async function api(path, { method = "GET", body, silent = false } = {}) {
  const res = await fetch(API + path, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = {};
  try { data = await res.json(); } catch { /* 204/流 */ }
  if (res.status === 401) { logout(); throw new Error("登录已过期"); }
  if (!res.ok) {
    const msg = (data && (data.detail?.message || data.detail || data.message)) || `请求失败(${res.status})`;
    if (!silent) toast(typeof msg === "string" ? msg : "请求失败", "bad");
    throw new Error(String(msg));
  }
  return data;
}

/* ---------------- Toast ---------------- */
function toast(msg, kind = "info", ms = 3200) {
  const el = document.createElement("div");
  el.className = `toast ${kind === "info" ? "" : kind}`;
  el.textContent = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 400); }, ms);
}

/* ---------------- SSE：POST 流式读取（面试提交） ---------------- */
async function streamSSE(path, body, handlers) {
  const res = await fetch(API + path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${state.token}` },
    body: JSON.stringify(body),
  });
  if (!res.ok) { toast("流式请求失败", "bad"); return; }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, idx); buf = buf.slice(idx + 2);
      let ev = "message", data = "";
      for (const line of chunk.split("\n")) {
        if (line.startsWith("event:")) ev = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (data && handlers[ev]) { try { handlers[ev](JSON.parse(data)); } catch { /* 忽略残包 */ } }
    }
  }
}

/* ---------------- 认证 ---------------- */
function logout() {
  state.token = ""; state.user = null;
  localStorage.removeItem("fk_token"); localStorage.removeItem("fk_user");
  location.hash = "#/login";
}

function saveAuth(d) {
  state.token = d.access_token;
  api("/auth/me").then(u => {
    state.user = u;
    localStorage.setItem("fk_user", JSON.stringify(u));
    enterApp();
    location.hash = "#/jobs";
  });
}

/* ---------------- 布局切换 ---------------- */
function enterApp() {
  $("#authRoot").innerHTML = "";
  $("#authRoot").classList.add("hidden");
  $("#sidebar").classList.remove("hidden");
  $("#main").classList.remove("hidden");
  $("#userChip").innerHTML = `<b>${esc(state.user?.name || "")}</b><span>${esc(state.user?.email || "")}</span>`;
}
function showAuth() {
  $("#sidebar").classList.add("hidden");
  $("#main").classList.add("hidden");
  const root = $("#authRoot");
  root.classList.remove("hidden");
  renderAuth(root);
}

/* ================= 登录 / 注册 ================= */
function renderAuth(root) {
  root.innerHTML = `
  <div class="auth-wrap"><div class="auth-card stagger">
    <div class="auth-hero">
      <div class="brand-logo">FK</div>
      <h1>FaceTo KP · 岗位定向刷题</h1>
      <p>粘贴 JD → 生成画像 → 定向刷题 → 模拟面试<br>把面经和真题对准你要的那个岗位</p>
    </div>
    <div class="card">
      <div class="tabs mb14">
        <div class="tab on" data-auth="login">登录</div>
        <div class="tab" data-auth="register">注册</div>
      </div>
      <form id="authForm">
        <div class="field" id="nameField" style="display:none">
          <label class="label">昵称</label>
          <input class="input" name="name" placeholder="怎么称呼你" maxlength="30">
        </div>
        <div class="field">
          <label class="label">邮箱</label>
          <input class="input" name="email" type="email" required placeholder="you@example.com">
        </div>
        <div class="field">
          <label class="label">密码</label>
          <input class="input" name="password" type="password" required minlength="6" placeholder="至少 6 位">
        </div>
        <button class="btn btn-primary btn-lg btn-block" id="authBtn">登录</button>
      </form>
      <div class="divider"></div>
      <div class="faint" style="font-size:12.5px;text-align:center;line-height:1.8">
        演示账号：<span class="mono">demo@faceto.cn</span> / <span class="mono">demo1234</span><br>
        已预置一个解析完成的安全工程师岗位画像
      </div>
    </div>
  </div></div>`;

  let mode = "login";
  $$(".tab", root).forEach(t => t.onclick = () => {
    mode = t.dataset.auth;
    $$(".tab", root).forEach(x => x.classList.toggle("on", x === t));
    $("#nameField").style.display = mode === "register" ? "" : "none";
    $("#authBtn").textContent = mode === "login" ? "登录" : "注册并登录";
  });
  $("#authForm").onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = Object.fromEntries(fd.entries());
    const btn = $("#authBtn"); btn.disabled = true; btn.innerHTML = `<span class="spinner"></span> 处理中`;
    try {
      const d = await api(`/auth/${mode}`, { method: "POST", body });
      saveAuth(d);
    } catch { btn.disabled = false; btn.textContent = mode === "login" ? "登录" : "注册并登录"; }
  };
}

/* ================= 路由 ================= */
const routes = [
  { re: /^#\/login$/, view: () => showAuth(), step: 0 },
  { re: /^#\/jobs$/, view: viewJobs, step: 2 },
  { re: /^#\/import$/, view: viewImport, step: 1 },
  { re: /^#\/job\/(\d+)$/, view: m => viewJob(+m[1]), step: 2 },
  { re: /^#\/plan\/(\d+)$/, view: m => viewPlan(+m[1]), step: 3 },
  { re: /^#\/practice\/(\d+)$/, view: m => viewPractice(+m[1]), step: 4 },
  { re: /^#\/interview\/(\d+)$/, view: m => viewInterview(+m[1]), step: 5 },
];

function route() {
  if (!state.token) { showAuth(); return; }
  enterApp();
  const hash = location.hash || "#/jobs";
  for (const r of routes) {
    const m = hash.match(r.re);
    if (m) {
      if (!$("#main").classList.contains("hidden")) markStep(r.step);
      r.view(m);
      return;
    }
  }
  location.hash = "#/jobs";
}

function markStep(step) {
  $$("#flowNav .flow-item").forEach(el => {
    const s = +el.dataset.step;
    el.classList.toggle("active", s === step);
    el.classList.toggle("visited", s < step);
  });
}

function setView(html, setup) {
  const v = $("#view");
  v.innerHTML = html;
  v.style.animation = "none"; void v.offsetWidth; v.style.animation = "";
  setup && setup();
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function when(ts) { return new Date(ts * 1000).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }); }

/* ================= 岗位列表 ================= */
async function viewJobs() {
  setView(`
    <div class="page-head">
      <div><div class="page-title">我的岗位</div>
        <div class="page-desc">每个岗位一份独立画像与备考计划 · 对应画布 S1/S2 入口</div></div>
      <a class="btn btn-primary" href="#/import">＋ 导入新岗位 JD</a>
    </div>
    <div id="jobList" class="stagger">
      ${[1,2,3].map(() => `<div class="card mb14"><div class="skel skel-line" style="width:38%"></div>
        <div class="skel skel-line" style="width:62%"></div><div class="skel skel-line" style="width:24%"></div></div>`).join("")}
    </div>`);
  const jobs = await api("/jobs");
  const box = $("#jobList");
  if (!jobs.length) {
    box.innerHTML = `<div class="card empty"><div class="big">📋</div>
      还没有岗位。粘贴一份 JD 开始定向备考 →<div class="mt14">
      <a class="btn btn-primary" href="#/import">导入岗位 JD</a></div></div>`;
    return;
  }
  box.innerHTML = jobs.map(j => `
    <div class="card hover mb14" style="cursor:pointer" data-job="${j.id}">
      <div style="display:flex;align-items:center;gap:14px">
        <div style="flex:1">
          <div style="display:flex;align-items:center;gap:10px">
            <b style="font-size:15.5px">${esc(j.title)}</b>
            <span class="chip ${j.parse_status === "done" ? "ok" : j.parse_status === "failed" ? "bad" : "warn"}">
              ${j.parse_status === "done" ? "画像就绪" : j.parse_status === "failed" ? "解析失败" : "解析中"}</span>
          </div>
          <div class="muted mt8" style="font-size:12.5px">${esc(j.company)} · ${j.point_count} 个考点 · ${when(j.created_at)}</div>
        </div>
        <span class="btn">查看画像 →</span>
      </div>
    </div>`).join("");
  $$(".card[data-job]", box).forEach(c => c.onclick = () => {
    state.jobId = +c.dataset.job; localStorage.setItem("fk_job", state.jobId);
    location.hash = `#/job/${state.jobId}`;
  });
}

/* ================= S1 · 导入岗位 ================= */
function viewImport() {
  const SAMPLE = `岗位：安全工程师（Web方向）
职责：
1. 负责公司 Web 应用的渗透测试与漏洞挖掘，输出测试报告并推动修复；
2. 参与安全开发生命周期（SDL）建设；
3. 处置线上安全事件，开展应急响应与溯源分析；
4. 对接等保测评与风险评估，完成合规整改。
要求：
1. 熟悉 SQL注入、XSS、CSRF 等 Web 漏洞原理与防御，有渗透测试经验；
2. 熟悉 HTTPS/TLS、加密算法与 JWT 认证鉴权；
3. 熟悉 TCP/IP 协议栈与计算机网络基础；熟悉 Linux 系统安全。`;

  setView(`
    <div class="page-head">
      <div><div class="page-title">S1 · 导入岗位 JD</div>
        <div class="page-desc">支持文本粘贴 / 链接 / 截图三种入口 · 解析为异步任务（202 语义），完成后自动进入画像</div></div>
    </div>
    <div class="grid2 stagger">
      <div class="card">
        <div class="tabs mb14" id="srcTabs">
          <div class="tab on" data-src="text">📄 文本粘贴</div>
          <div class="tab" data-src="url">🔗 链接</div>
          <div class="tab" data-src="image">🖼 截图</div>
        </div>
        <div class="field">
          <label class="label" id="srcLabel">岗位描述（JD 原文）</label>
          <textarea class="input" id="jdInput" placeholder="粘贴完整的岗位描述，越完整解析越准…"></textarea>
        </div>
        <div style="display:flex;gap:10px;align-items:center">
          <button class="btn btn-primary btn-lg" id="parseBtn">开始解析画像</button>
          <a href="javascript:;" class="muted" id="fillSample" style="font-size:12.5px">填入示例 JD</a>
        </div>
      </div>
      <div class="card" id="parsePanel">
        <div class="muted" style="font-size:13px;line-height:2">
          <b style="color:var(--text)">解析将产出：</b><br>
          1. 考点清单（技能 / 知识维度）<br>
          2. 每个考点的权重（AI 判定 + 可手动微调）<br>
          3. JD 原句证据（后续刷题「双溯源」的来源之一）<br><br>
          <span class="faint">解析为异步任务：接口立即返回 202 + job_id，
          前端轮询任务状态，就绪后平滑过渡到 S2 画像屏。</span>
        </div>
        <div id="parseStatus" class="mt14"></div>
      </div>
    </div>`);

  let src = "text";
  $$("#srcTabs .tab").forEach(t => t.onclick = () => {
    src = t.dataset.src;
    $$("#srcTabs .tab").forEach(x => x.classList.toggle("on", x === t));
    const input = $("#jdInput");
    if (src === "text") {
      $("#srcLabel").textContent = "岗位描述（JD 原文）";
      input.placeholder = "粘贴完整的岗位描述，越完整解析越准…";
    } else if (src === "url") {
      $("#srcLabel").textContent = "招聘页链接";
      input.placeholder = "https://…（M1 演示版直接按原文处理）";
    } else {
      $("#srcLabel").textContent = "截图内容（OCR 输入）";
      input.placeholder = "粘贴截图中的文字内容（模拟 OCR 结果）…";
    }
  });
  $("#fillSample").onclick = () => { $("#jdInput").value = SAMPLE; };

  $("#parseBtn").onclick = async () => {
    const payload = $("#jdInput").value.trim();
    if (payload.length < 10) { toast("内容太短，请粘贴完整 JD", "bad"); return; }
    const btn = $("#parseBtn");
    btn.disabled = true;
    $("#parseStatus").innerHTML = `<div style="display:flex;align-items:center;gap:10px">
      <span class="spinner"></span><span class="dots">解析任务已提交，AI 正在提取考点</span></div>
      <div class="progress mt14"><i style="width:8%"></i></div>`;
    try {
      const d = await api("/jobs", { method: "POST", body: { source: src, payload } });
      state.jobId = d.job_id; localStorage.setItem("fk_job", d.job_id);
      pollJobParsed(d.job_id);
    } catch { btn.disabled = false; }
  };
}

async function pollJobParsed(jobId) {
  const bar = $("#parseStatus .progress > i");
  let pct = 8;
  const timer = setInterval(() => { pct = Math.min(pct + 6, 92); if (bar) bar.style.width = pct + "%"; }, 260);
  for (let i = 0; i < 60; i++) {
    await new Promise(r => setTimeout(r, 800));
    const job = await api(`/jobs/${jobId}`, { silent: true }).catch(() => null);
    if (job && job.parse_status === "done") {
      clearInterval(timer);
      if (bar) bar.style.width = "100%";
      toast("画像解析完成，正在进入 S2", "ok");
      setTimeout(() => { location.hash = `#/job/${jobId}`; }, 700);
      return;
    }
    if (job && job.parse_status === "failed") { clearInterval(timer); toast("解析失败，请重试", "bad"); return; }
  }
  clearInterval(timer); toast("解析超时，请稍后在列表中查看", "bad");
}

/* ================= S2 · 岗位画像 ================= */
async function viewJob(jobId) {
  state.jobId = jobId; localStorage.setItem("fk_job", jobId);
  setView(`<div class="card"><div class="skel skel-line" style="width:40%"></div>
    <div class="skel skel-line" style="width:70%"></div><div class="skel skel-line" style="width:55%"></div></div>`);

  const [job, points, mastery] = await Promise.all([
    api(`/jobs/${jobId}`), api(`/jobs/${jobId}/points`), api(`/profile/mastery?job_id=${jobId}`),
  ]);

  const m = mastery.points.reduce((a, x) => (a[x.point_name] = x, a), {});
  setView(`
    <div class="page-head">
      <div>
        <div class="page-title">S2 · 岗位画像</div>
        <div class="page-desc">${esc(job.title)} · ${esc(job.company)} · ${points.length} 个考点
          ${job.match_score != null ? ` · 匹配度 <b class="mono" style="color:var(--accent-2)">${job.match_score}%</b>` : ""}</div>
      </div>
      <div style="display:flex;gap:10px">
        <button class="btn" id="reparseBtn">重新解析</button>
        <button class="btn btn-primary" id="planBtn">生成备考计划 →</button>
      </div>
    </div>

    <div class="grid2 stagger" style="align-items:start">
      <div class="card">
        <b style="font-size:14px">考点雷达（权重 × 掌握度）</b>
        <div class="radar-wrap mt14" id="radarBox"></div>
        <div class="faint mt8" style="font-size:12px;text-align:center">掌握度随刷题与模拟面试实时回流更新</div>
      </div>
      <div class="card">
        <b style="font-size:14px">考点权重与掌握度</b>
        <div class="mt14" id="pointsBox"></div>
        <div style="display:flex;justify-content:space-between;margin-top:16px">
          <span class="faint" style="font-size:12px">拖动滑杆微调权重（source=user），保存后计划将重排</span>
        </div>
        <button class="btn btn-block mt8" id="saveWeights">保存权重调整</button>
      </div>
    </div>

    <div class="card mt22" id="weakBox">
      <b style="font-size:14px">弱项提醒</b>
      <div class="mt14" id="weakList" style="display:flex;gap:10px;flex-wrap:wrap"></div>
    </div>`);

  drawRadar(points.map(p => ({
    name: p.point_name,
    weight: p.weight / 100,
    mastery: (p.mastery ?? 50) / 100,
  })));

  $("#pointsBox").innerHTML = points.map((p, i) => `
    <div style="padding:11px 0;border-bottom:1px solid rgba(35,48,72,.5)">
      <div style="display:flex;align-items:center;gap:10px">
        <span class="chip ${p.dimension === "技能" ? "on" : ""}">${p.dimension}</span>
        <b style="flex:1;font-size:13.5px">${esc(p.point_name)}</b>
        <span class="muted" style="font-size:12px">权重 <b class="mono" id="wv-${i}">${p.weight}</b></span>
      </div>
      <div class="mt8" style="display:flex;align-items:center;gap:12px">
        <input type="range" min="1" max="100" value="${p.weight}" data-p="${esc(p.point_name)}" data-i="${i}"
          style="flex:1;accent-color:var(--accent)">
        <div class="mbar" style="width:120px;flex:none" title="掌握度">
          <i style="width:${p.mastery ?? 0}%"></i></div>
        <span class="muted mono" style="font-size:11.5px;width:34px">${p.mastery != null ? p.mastery + "%" : "—"}</span>
      </div>
    </div>`).join("") || `<div class="empty">暂无考点</div>`;

  $$("#pointsBox input[type=range]").forEach(r => r.oninput = () => {
    $(`#wv-${r.dataset.i}`).textContent = r.value;
  });
  $("#saveWeights").onclick = async () => {
    const pts = $$("#pointsBox input[type=range]").map(r => ({ point_name: r.dataset.p, weight: +r.value }));
    const d = await api(`/jobs/${jobId}/points`, { method: "PUT", body: { points: pts } });
    toast(`已更新 ${d.updated} 个考点权重`, "ok");
  };
  $("#reparseBtn").onclick = async () => {
    await api(`/jobs/${jobId}/reparse`, { method: "POST" });
    toast("已提交重新解析，稍后刷新查看", "ok");
    setTimeout(() => viewJob(jobId), 3200);
  };
  $("#planBtn").onclick = async () => {
    const btn = $("#planBtn"); btn.disabled = true; btn.innerHTML = `<span class="spinner"></span> 生成中`;
    const d = await api(`/jobs/${jobId}/plans`, { method: "POST", body: { days: 7 } });
    state.planId = d.plan_id; localStorage.setItem("fk_plan", d.plan_id);
    toast(`计划已生成：${d.days} 天 · ${d.modules} 个模块`, "ok");
    location.hash = `#/plan/${d.plan_id}`;
  };

  const weak = (mastery.weak_points || []);
  $("#weakList").innerHTML = weak.length
    ? weak.map(w => `<span class="chip warn">⚠ ${esc(w.point_name)} · ${w.mastery}%</span>`).join("")
    : `<span class="faint" style="font-size:13px">刷题后这里会显示最薄弱的考点</span>`;
}

/* 雷达图（SVG，含过渡动画） */
function drawRadar(items) {
  const n = Math.max(3, Math.min(items.length, 8));
  const show = items.slice(0, n);
  const W = 330, H = 300, cx = W / 2, cy = H / 2 + 6, R = 100;
  const angle = i => (Math.PI * 2 * i) / show.length - Math.PI / 2;
  const pt = (i, r) => [cx + Math.cos(angle(i)) * r, cy + Math.sin(angle(i)) * r];

  let web = "", rings = "";
  for (let lv = 1; lv <= 4; lv++) {
    const r = (R * lv) / 4;
    web += `<polygon class="web" points="${show.map((_, i) => pt(i, r).join(",")).join(" ")}"/>`;
  }
  show.forEach((_, i) => {
    const [x, y] = pt(i, R);
    web += `<line class="web" x1="${cx}" y1="${cy}" x2="${x}" y2="${y}"/>`;
  });
  const dataPts = show.map((it, i) => pt(i, R * (0.25 + 0.75 * it.weight * 0.5 + 0.75 * it.mastery * 0.5)).join(",")).join(" ");
  const labels = show.map((it, i) => {
    const [x, y] = pt(i, R + 26);
    return `<text x="${x}" y="${y}" text-anchor="middle">${esc(it.name.length > 8 ? it.name.slice(0, 7) + "…" : it.name)}</text>`;
  }).join("");
  const dots = show.map((it, i) => {
    const [x, y] = pt(i, R * (0.25 + 0.75 * it.weight * 0.5 + 0.75 * it.mastery * 0.5));
    return `<circle class="dot" r="3.2" cx="${x}" cy="${y}"/>`;
  }).join("");

  $("#radarBox").innerHTML = `
    <svg class="radar" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
      ${web}<polygon class="data" points="${dataPts}" style="opacity:0"/>${dots}${labels}
    </svg>`;
  requestAnimationFrame(() => {
    const poly = $("#radarBox polygon.data");
    if (poly) { poly.style.opacity = "1"; poly.style.transformOrigin = `${cx}px ${cy}px`; }
  });
}

/* ================= S3 · 计划 + 面经 ================= */
async function viewPlan(planId) {
  state.planId = planId; localStorage.setItem("fk_plan", planId);
  setView(`<div class="card"><div class="skel skel-line" style="width:40%"></div>
    <div class="skel skel-line" style="width:70%"></div></div>`);
  const [plan, progress] = await Promise.all([api(`/plans/${planId}`), api(`/plans/${planId}/progress`)]);

  setView(`
    <div class="page-head">
      <div><div class="page-title">S3 · 备考计划</div>
        <div class="page-desc">${plan.days} 天 · ${plan.days.length} 个日程块 · 进度准实时（Redis 计数先行）</div></div>
      <div style="display:flex;gap:10px">
        <a class="btn" href="#/job/${plan.job_id}">← 返回画像</a>
        <a class="btn" href="#/interview/${plan.job_id}">模拟面试 S5</a>
        <a class="btn btn-primary" href="#/practice/${planId}">开始今日刷题 →</a>
      </div>
    </div>

    <div class="card mb22">
      <div style="display:flex;align-items:center;gap:16px">
        <div style="flex:1">
          <div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:8px">
            <b>总进度</b><span class="muted mono">${progress.done}/${progress.total} 题 · ${progress.percent}%</span>
          </div>
          <div class="progress"><i style="width:${progress.percent}%"></i></div>
        </div>
      </div>
    </div>

    <div class="grid2" style="grid-template-columns:1.6fr 1fr;align-items:start">
      <div id="daysBox" class="stagger"></div>
      <div class="card">
        <b style="font-size:14px">📚 面经情报（同考点）</b>
        <div class="field mt14">
          <input class="input" id="expKw" placeholder="搜索考点关键词，如 注入 / 面试官…">
        </div>
        <div id="expList" style="max-height:520px;overflow-y:auto"></div>
      </div>
    </div>`);

  const days = plan.days || [];
  $("#daysBox").innerHTML = days.map(d => {
    const pct = d.total ? Math.round(d.done / d.total * 100) : 0;
    const stateChip = d.done >= d.total ? `<span class="chip ok">已完成</span>` : d.done > 0 ? `<span class="chip warn">进行中</span>` : "";
    return `
    <div class="day-block mb14">
      <div class="day-head" data-open="1">
        <span class="n">Day ${d.day_no}</span>
        <span class="muted" style="font-size:12.5px">${d.done}/${d.total} 题</span>
        <div class="progress" style="flex:1;max-width:180px"><i style="width:${pct}%"></i></div>
        ${stateChip}
      </div>
      <div class="day-body">
        ${d.modules.map(mm => `
          <div class="module">
            <span class="chip">${esc(mm.point_name)}</span>
            <span class="mc muted">${mm.done_count}/${mm.question_count} 题</span>
            <div class="mbar" style="width:90px"><i style="width:${Math.round(mm.done_count / mm.question_count * 100)}%"></i></div>
          </div>`).join("")}
      </div>
    </div>`;
  }).join("") || `<div class="card empty">计划为空</div>`;
  $$(".day-head").forEach(h => h.onclick = () => {
    const body = h.nextElementSibling;
    body.style.display = body.style.display === "none" ? "" : "none";
  });

  // 面经检索（游标分页）
  let cursor = 0, kw = "";
  async function loadExp(reset) {
    if (reset) { cursor = 0; $("#expList").innerHTML = ""; }
    const d = await api(`/exp?keyword=${encodeURIComponent(kw)}&cursor=${cursor}`);
    if (d.degraded) { $("#expList").innerHTML = `<div class="faint" style="font-size:12.5px">面经服务降级中（§8.3），稍后再试</div>`; return; }
    if (!d.items.length && !cursor) {
      $("#expList").innerHTML = `<div class="faint" style="font-size:12.5px;padding:12px 0">没有匹配的面经</div>`;
    }
    d.items.forEach(x => {
      const el = document.createElement("div");
      el.className = "trace-card";
      el.style.marginBottom = "10px";
      el.innerHTML = `<b style="color:var(--text)">${esc(x.title)}</b>
        <span class="faint" style="float:right;font-size:11px">${esc(x.source)}</span>
        <div style="margin-top:6px">${esc(x.content)}</div>
        <div style="margin-top:8px">${x.points.map(p => `<span class="chip">${esc(p)}</span>`).join(" ")}</div>`;
      $("#expList").appendChild(el);
    });
    cursor = d.next_cursor ?? 0;
    if (cursor && !$("#moreExp")) {
      const more = document.createElement("button");
      more.className = "btn btn-block btn-sm mt8"; more.id = "moreExp"; more.textContent = "加载更多面经";
      more.onclick = () => { more.remove(); loadExp(false); };
      $("#expList").after(more);
      $("#expList").parentNode.appendChild(more);
    } else if (!cursor && $("#moreExp")) { $("#moreExp").remove(); }
  }
  $("#expKw").oninput = debounce(() => { kw = $("#expKw").value.trim(); loadExp(true); }, 350);
  loadExp(true);
}

function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

/* ================= S4 · 定向刷题 ================= */
async function viewPractice(planId) {
  state.planId = planId; localStorage.setItem("fk_plan", planId);
  setView(`<div class="card"><div class="skel skel-line" style="width:30%"></div>
    <div class="skel skel-line" style="width:80%"></div><div class="skel skel-line" style="width:64%"></div></div>`);

  let progress = await api(`/plans/${planId}/progress`);
  const plan = await api(`/plans/${planId}`);
  renderShell();

  async function next() {
    $("#qzone").innerHTML = `<div class="skel skel-line" style="width:20%"></div>
      <div class="skel skel-line" style="width:82%"></div><div class="skel skel-line" style="width:70%"></div>
      <div class="skel skel-line" style="width:55%"></div>`;
    const d = await api(`/plans/${planId}/next`);
    progress = await api(`/plans/${planId}/progress`);
    refreshProgress();
    if (d.done || !d.question) { renderDone(d.reason); return; }
    renderQuestion(d);
  }

  function refreshProgress() {
    $("#pct").textContent = `${progress.done}/${progress.total} · ${progress.percent}%`;
    $("#pbar").style.width = progress.percent + "%";
  }

  function renderShell() {
    setView(`
    <div class="page-head">
      <div><div class="page-title">S4 · 定向刷题</div>
        <div class="page-desc">题目按岗位考点权重定向投放 · 客观题同步判分 / 主观题 AI 异步点评</div></div>
      <a class="btn" href="#/plan/${planId}">← 返回计划</a>
    </div>
    <div class="card mb22">
      <div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:8px">
        <b>本轮计划进度</b><span class="muted mono" id="pct"></span>
      </div>
      <div class="progress"><i id="pbar" style="width:0%"></i></div>
    </div>
    <div id="qzone"></div>`);
    refreshProgress();
    next();
  }

  function renderDone(reason) {
    $("#qzone").innerHTML = `
    <div class="card stagger" style="text-align:center;padding:60px 30px">
      <div style="font-size:46px">🎉</div>
      <div class="page-title mt14">本计划题目已刷完</div>
      <div class="muted mt8" style="font-size:13.5px">${esc(reason || "去 S5 模拟面试检验成果，或回到画像查看掌握度变化")}</div>
      <div class="mt22" style="display:flex;gap:10px;justify-content:center">
        <a class="btn" href="#/job/${state.jobId || plan.job_id}">查看画像雷达</a>
        <a class="btn btn-primary" href="#/interview/${plan.job_id}">进入模拟面试 →</a>
      </div>
    </div>`;
  }

  function renderQuestion(d) {
    const q = d.question;
    const typeLabel = { single: "单选", multi: "多选", subjective: "问答" }[q.type];
    $("#qzone").innerHTML = `
    <div class="stagger">
      <div class="card mb14" style="display:flex;align-items:center;gap:10px">
        <span class="chip on">${esc(d.module || "")}</span>
        <span class="chip">${typeLabel}</span>
        <span class="chip">${"★".repeat(q.difficulty)}</span>
        ${q.points.map(p => `<span class="chip">${esc(p)}</span>`).join("")}
        <span class="muted" style="margin-left:auto;font-size:12px">本模块还剩 ${d.remaining_in_module} 题</span>
      </div>

      <div class="card mb14">
        <div class="q-stem">${esc(q.stem)}</div>
        <div id="optsBox" class="mt14"></div>
        <div id="ansZone"></div>
      </div>

      <div id="traceZone">
        ${traceHTML(q)}
      </div>
    </div>`;

    let picked = [];
    const box = $("#optsBox");
    if (q.type === "subjective") {
      box.innerHTML = `<textarea class="input" id="subjAns" style="min-height:170px"
        placeholder="按「结论 → 原理 → 实例」的结构作答，AI 点评将按要点覆盖度打分…"></textarea>`;
    } else {
      box.innerHTML = (q.options || []).map((o, i) => `
        <div class="opt" data-i="${i}">
          <span class="key">${"ABCD"[i]}</span><span>${esc(o)}</span>
        </div>`).join("");
      $$(".opt", box).forEach(el => el.onclick = () => {
        if ($("#submitBtn")?.disabled) return;
        const i = +el.dataset.i;
        if (q.type === "single") picked = [i];
        else picked = picked.includes(i) ? picked.filter(x => x !== i) : [...picked, i];
        $$(".opt", box).forEach(e => e.classList.toggle("sel", picked.includes(+e.dataset.i)));
      });
    }

    $("#ansZone").innerHTML = `
      <div class="mt22" style="display:flex;gap:10px;align-items:center">
        <button class="btn btn-primary btn-lg" id="submitBtn">提交作答</button>
        <span class="faint" style="font-size:12px">提交携带 Idempotency-Key（防双击双写）</span>
      </div>
      <div id="resultZone" class="mt14"></div>`;

    $("#submitBtn").onclick = () => submit(q, picked);
  }

  async function submit(q, picked) {
    const idem = `ans-${q.id}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const body = {
      question_id: q.id, plan_id: planId, idempotency_key: idem,
      user_answer: q.type === "subjective" ? $("#subjAns").value : picked,
    };
    if (q.type === "subjective" && !body.user_answer.trim()) { toast("先写下你的作答", "bad"); return; }
    if (q.type !== "subjective" && !picked.length) { toast("先选择答案", "bad"); return; }

    const btn = $("#submitBtn");
    btn.disabled = true; btn.innerHTML = `<span class="spinner"></span> 判分中`;
    const d = await api("/answers", { method: "POST", body });
    progress.done += 1; progress.percent = Math.round(progress.done / progress.total * 100);
    refreshProgress();

    if (q.type !== "subjective") {
      // 客观题：同步判分
      $$(".opt").forEach(el => {
        const i = +el.dataset.i;
        if ((d.correct_answer || []).includes(i)) el.classList.add("correct");
        else if (picked.includes(i)) el.classList.add("wrong");
      });
      $("#resultZone").innerHTML = resultHTML(d.is_correct, d.analysis, null);
      showNextBtn();
    } else {
      // 主观题：异步 AI 点评（轮询兜底 + 排队可见化）
      $("#resultZone").innerHTML = `
        <div class="trace-card" style="border-left-color:var(--accent-2)">
          <span class="spinner"></span> <b>AI 点评生成中</b>
          <span class="muted" style="font-size:12px">（异步任务 #${d.task_id} · 预计 ${d.eta_seconds}s，完成后自动展示）</span>
        </div>`;
      pollReview(d.answer_id);
    }
  }

  async function pollReview(answerId, attempt = 0) {
    const d = await api(`/answers/${answerId}/review`, { silent: true }).catch(() => null);
    if (!d) { showNextBtn(); return; }
    if (d.status === "done" && d.review) {
      $("#resultZone").innerHTML = resultHTML(null, null, d.review);
      showNextBtn();
    } else if (attempt > 40) {
      $("#resultZone").innerHTML = resultHTML(null, null, { score: "—", review: "点评超时，可稍后在任务中心查看。" });
      showNextBtn();
    } else {
      await new Promise(r => setTimeout(r, (d.retry_after || 2) * 1000));
      pollReview(answerId, attempt + 1);
    }
  }

  function resultHTML(isCorrect, analysis, review) {
    let head = "";
    if (isCorrect === true) head = `<div class="chip ok" style="font-size:13px">✓ 回答正确</div>`;
    else if (isCorrect === false) head = `<div class="chip bad" style="font-size:13px">✗ 回答错误</div>`;
    const body = review
      ? `<div class="card mt14" style="border-color:rgba(34,211,238,.35)">
           <b style="color:var(--accent-2);font-size:13.5px">AI 点评 · 模拟面试官视角</b>
           <div class="mt8" style="white-space:pre-wrap;line-height:1.85;font-size:14px">${esc(review.review)}</div>
         </div>`
      : (analysis ? `<div class="card mt14"><b style="font-size:13.5px">参考解析</b>
           <div class="mt8" style="line-height:1.85;font-size:14px">${esc(analysis)}</div></div>` : "");
    return `<div style="animation:fadeUp .5s var(--ease) both">${head}${body}</div>`;
  }

  function showNextBtn() {
    if ($("#nextBtn")) return;
    const zone = $("#resultZone");
    const btn = document.createElement("button");
    btn.className = "btn btn-primary btn-lg mt14"; btn.id = "nextBtn"; btn.textContent = "下一题 →";
    btn.onclick = () => next();
    zone.appendChild(btn);
    btn.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function traceHTML(q) {
    const t = q.trace || {};
    const parts = [];
    if (t.jd_evidence?.length) {
      parts.push(`<div class="trace-card"><b style="color:var(--accent)">溯源① JD 原句</b>
        ${t.jd_evidence.map(e => `<div class="mt8" style="border-left:2px solid var(--border);padding-left:10px">“${esc(e)}”</div>`).join("")}</div>`);
    }
    if (t.exp_ref) {
      parts.push(`<div class="trace-card" style="border-left-color:var(--warn)"><b style="color:var(--warn)">溯源② 面经出处</b>
        <div class="mt8">本题出现于「${esc(t.exp_ref)}」高频考点</div>
        ${t.related_exp?.length ? `<div class="mt8">${t.related_exp.map(x => `<span class="chip">${esc(x.title)}</span>`).join(" ")}</div>` : ""}</div>`);
    }
    return parts.length ? `<div class="card" style="padding:16px 20px"><b style="font-size:13px">🔍 双溯源（这道题为什么出现在你的计划里）</b><div class="mt14">${parts.join("")}</div></div>`
      : "";
  }
}

/* ================= S5 · 模拟面试 ================= */
async function viewInterview(jobId) {
  state.jobId = jobId; localStorage.setItem("fk_job", jobId);
  setView(`<div class="card"><div class="skel skel-line" style="width:36%"></div>
    <div class="skel skel-line" style="width:72%"></div></div>`);
  const sess = await api("/interviews", { method: "POST", body: { job_id: +jobId } });

  setView(`
    <div class="page-head">
      <div><div class="page-title">S5 · 模拟面试</div>
        <div class="page-desc">考点范围：${sess.point_checklist.map(esc).join(" / ")} · 共 ${sess.max_turns} 轮 · SSE 流式</div></div>
      <a class="btn" href="#/job/${jobId}">← 返回画像</a>
    </div>
    <div class="card">
      <div class="chat" id="chat"></div>
      <div class="divider"></div>
      <div style="display:flex;gap:10px">
        <textarea class="input" id="chatInput" style="min-height:64px;flex:1"
          placeholder="面试官提问结束后在此作答（回车发送 / Shift+回车换行）" disabled></textarea>
        <button class="btn btn-primary btn-lg" id="sendBtn" disabled>回答</button>
      </div>
      <div class="mt8" style="display:flex;gap:8px;flex-wrap:wrap" id="evalBox"></div>
      <div class="mt14" id="reportZone"></div>
    </div>`);

  const chat = $("#chat"), input = $("#chatInput"), sendBtn = $("#sendBtn");
  let streaming = false, turn = 0, finished = false;

  function addMsg(role, text = "") {
    const el = document.createElement("div");
    el.className = `msg ${role}`;
    el.innerHTML = `<div class="avatar">${role === "ai" ? "面" : "我"}</div>
      <div class="bubble">${esc(text)}${role === "ai" ? '<span class="caret"></span>' : ""}</div>`;
    chat.appendChild(el);
    chat.scrollTop = chat.scrollHeight;
    return $(".bubble", el);
  }
  function appendToken(bubble, t) {
    const caret = $(".caret", bubble);
    if (caret) caret.before(document.createTextNode(t));
    chat.scrollTop = chat.scrollHeight;
  }
  function endStream(bubble) { $(".caret", bubble)?.remove(); }

  // ---- 开场：EventSource 连接 SSE 流（token 走 query 兜底）
  addMsg("ai");
  const es = new EventSource(`${API}/interviews/${sess.interview_id}/stream?token=${encodeURIComponent(state.token)}`);
  let openingBubble = $(".msg:last-child .bubble", chat);
  es.addEventListener("token", e => appendToken(openingBubble, JSON.parse(e.data).t));
  es.addEventListener("done", () => { endStream(openingBubble); enableInput(); });
  es.addEventListener("error", () => { if (es.readyState === 2) { endStream(openingBubble); } });

  function enableInput() {
    streaming = false;
    input.disabled = false; sendBtn.disabled = false;
    input.focus();
  }
  function disableInput() {
    streaming = true;
    input.disabled = true; sendBtn.disabled = true;
  }

  async function answer() {
    if (streaming || finished) return;
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    addMsg("me", text);
    disableInput();

    const bubble = addMsg("ai");
    await streamSSE(`/interviews/${sess.interview_id}/turns`, { answer: text }, {
      token: d => appendToken(bubble, d.t),
      point_eval: d => {
        const chip = document.createElement("span");
        chip.className = `chip ${d.score >= 75 ? "ok" : d.score >= 55 ? "warn" : "bad"} eval-chip`;
        chip.textContent = `${d.point} · ${d.score} 分（${d.level}）`;
        $("#evalBox").appendChild(chip);
      },
      done: d => {
        endStream(bubble);
        turn = d.turn;
        if (d.finished) {
          finished = true;
          showReportBtn();
        } else enableInput();
      },
      error: d => { endStream(bubble); toast(`流错误：${d.message}`, "bad"); },
    });
  }

  function showReportBtn() {
    input.disabled = true; sendBtn.disabled = true;
    input.placeholder = "面试已结束，点击下方查看报告";
    const btn = document.createElement("button");
    btn.className = "btn btn-primary btn-lg btn-block";
    btn.innerHTML = `<span class="spinner"></span> 生成面试报告中`;
    $("#reportZone").appendChild(btn);
    setTimeout(async () => {
      const r = await api(`/interviews/${sess.interview_id}/report`);
      btn.remove();
      renderReport(r);
    }, 2600);
  }

  function renderReport(r) {
    const zone = $("#reportZone");
    zone.innerHTML = `
    <div class="card" style="border-color:rgba(91,140,255,.4);animation:fadeUp .5s var(--ease) both">
      <div style="display:flex;align-items:center;gap:16px">
        <div style="font-size:34px;font-weight:800" class="mono">${r.overall}<span style="font-size:15px;color:var(--muted)"> /100</span></div>
        <div><b>面试综合评估</b>
          <div class="muted" style="font-size:12.5px;margin-top:4px">掌握度已回流画像（S2 雷达将更新）</div></div>
        <a class="btn" style="margin-left:auto" href="#/job/${jobId}">查看画像变化 →</a>
      </div>
      <div class="divider"></div>
      ${r.points.map(p => `
        <div style="display:flex;align-items:center;gap:12px;padding:8px 0">
          <span style="width:170px;font-size:13.5px">${esc(p.point_name)}</span>
          <div class="mbar" style="flex:1"><i style="width:${p.avg_score}%"></i></div>
          <span class="mono muted" style="width:56px;text-align:right">${p.avg_score}%</span>
        </div>`).join("")}
      ${r.weak_points?.length ? `<div class="mt14" style="display:flex;gap:8px;flex-wrap:wrap">
        <span class="faint" style="font-size:12.5px">建议重点补强：</span>
        ${r.weak_points.map(w => `<span class="chip warn">${esc(w)}</span>`).join("")}</div>` : ""}
    </div>`;
    zone.scrollIntoView({ behavior: "smooth" });
  }

  sendBtn.onclick = answer;
  input.onkeydown = e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); answer(); } };
}

/* ================= 启动 ================= */
$("#logoutBtn").onclick = () => { logout(); toast("已退出登录"); };
window.addEventListener("hashchange", route);
route();
