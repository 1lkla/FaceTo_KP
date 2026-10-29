/* 刷题中心（QZ）—— FaceTo KP SPA 原生视图：#/quiz 与 #/quiz/pack/{pid}
 * 依赖 app.js 的全局 $ / $$ / api / esc / toast / setView / routes（本文件先于 app.js 加载，
 * 仅在视图被调用时才使用其全局函数）。进度键与旧版独立页一致：quiz_prog_{pid}。
 */
window.QZ = (() => {
  /* ---------- 状态 ---------- */
  let packs = null, bank = null, packMeta = null;
  let module = "choice", setF = "all", wrongOnly = false, idx = 0, advTimer = null;
  let prog = null;
  const progKey = pid => "quiz_prog_" + pid;
  const getProg = pid => JSON.parse(localStorage.getItem(progKey(pid)) || '{"choice":{},"subj":{}}');
  const save = () => packMeta && localStorage.setItem(progKey(packMeta.id), JSON.stringify(prog));

  // 旧版独立页（xi_quiz_prog_v1）进度一次性迁移到习思想包
  (function migrate() {
    const old = localStorage.getItem("xi_quiz_prog_v1");
    if (old && !localStorage.getItem(progKey("xi15040"))) localStorage.setItem(progKey("xi15040"), old);
  })();

  /* ---------- 样式（一次性注入，全部复用 SPA 设计令牌） ---------- */
  let styled = false;
  function ensureStyles() {
    if (styled) return; styled = true;
    const s = document.createElement("style");
    s.textContent = `
.qz-head{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-bottom:16px}
.qz-head h2{font-size:21px}
.qz-hint{font-size:12.5px;color:var(--muted)}
.qz-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
.qz-pack{background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);
  padding:18px;display:flex;flex-direction:column;gap:8px;cursor:pointer;
  transition:transform .15s var(--ease),border-color .15s,box-shadow .15s;animation:viewEnter .5s var(--ease) both}
.qz-pack:hover{transform:translateY(-2px);border-color:rgba(91,140,255,.5);box-shadow:var(--shadow)}
.qz-pack .emoji{font-size:26px}
.qz-pack h3{font-size:16px}
.qz-pack .desc{font-size:12.5px;color:var(--muted);min-height:36px}
.qz-meta{font-size:12px;color:var(--muted);display:flex;gap:12px}
.qz-meta b{color:var(--text)}
.qz-pbar{height:6px;border-radius:99px;background:var(--panel-3);overflow:hidden}
.qz-pbar i{display:block;height:100%;background:var(--grad);transition:width .4s var(--ease)}
.qz-pstat{font-size:11.5px;color:var(--muted);display:flex;justify-content:space-between}
.qz-pstat .acc{font-weight:700}
.qz-acc-ok{color:var(--ok)} .qz-acc-bad{color:var(--bad)}
.qz-del{font-size:11.5px;color:var(--bad);background:none;border:none;cursor:pointer;padding:0;text-align:left;opacity:.75}
.qz-del:hover{opacity:1}
.qz-import{border:1.5px dashed var(--border);background:rgba(91,140,255,.05);border-radius:var(--radius);
  padding:18px;display:flex;flex-direction:column;gap:6px;cursor:pointer;align-items:flex-start;
  transition:border-color .15s;animation:viewEnter .5s var(--ease) both}
.qz-import:hover{border-color:var(--accent)}
.qz-import .emoji{font-size:26px}
.qz-import h3{font-size:16px;color:var(--accent)}
.qz-import p{font-size:12.5px;color:var(--muted)}
.qz-panel{margin-top:16px}
.qz-filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px;align-items:center}
.qz-fchip{border:1px solid var(--border);background:var(--panel);border-radius:99px;padding:4px 13px;
  font-size:12.5px;cursor:pointer;color:var(--muted);transition:.12s}
.qz-fchip:hover{color:var(--text)}
.qz-fchip.on{border-color:var(--accent);color:var(--accent);background:rgba(91,140,255,.13);font-weight:600}
.qz-stat{margin-left:auto;font-size:13px;color:var(--muted)}
.qz-stat b{color:var(--text)}
.qz-layout{display:flex;gap:16px;align-items:flex-start}
.qz-main{flex:1;min-width:0}
.qz-side{flex:0 0 232px;width:232px;position:sticky;top:16px}
.qz-side .card{padding:13px 14px}
.qz-side h4{font-size:13px;display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;color:var(--muted);font-weight:600}
.qz-lg{font-size:11px;font-weight:600;display:flex;gap:8px}
.qz-lg i{display:inline-block;width:9px;height:9px;border-radius:3px;margin-right:3px}
.qz-lg .g{background:var(--ok)} .qz-lg .r{background:var(--bad)}
.qz-ansgrid{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;max-height:calc(100vh - 220px);
  overflow-y:auto;padding:2px 2px 4px}
.qz-cell{position:relative;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--panel);
  min-height:46px;cursor:pointer;display:flex;flex-direction:column;align-items:center;justify-content:center;
  gap:1px;padding:3px 2px;transition:transform .12s,color .12s;color:var(--muted);font-family:inherit;font-size:12px}
.qz-cell:hover{transform:translateY(-1px);border-color:rgba(91,140,255,.5)}
.qz-cell .num{font-size:10.5px;font-weight:700;line-height:1}
.qz-cell .ans{font-size:15px;font-weight:800;line-height:1.15;min-height:18px}
.qz-cell:not(.ok):not(.bad) .ans{visibility:hidden}
.qz-cell.ok,.qz-cell.bad{animation:qzreveal .35s var(--ease)}
.qz-cell.ok{background:rgba(52,211,153,.12);border-color:rgba(52,211,153,.35)}
.qz-cell.ok .ans{color:var(--ok)}
.qz-cell.bad{background:rgba(248,113,113,.12);border-color:rgba(248,113,113,.35)}
.qz-cell.bad .ans{color:var(--bad)}
.qz-cell.cur{outline:2px solid var(--accent);outline-offset:1px;color:var(--text)}
@keyframes qzreveal{0%{transform:scale(.82);opacity:.2}100%{transform:scale(1);opacity:1}}
.qz-qmeta{display:flex;gap:8px;align-items:center;font-size:12px;color:var(--muted);margin-bottom:10px;flex-wrap:wrap}
.qz-tag{background:rgba(91,140,255,.14);color:var(--accent);font-weight:600;padding:1px 9px;border-radius:99px}
.qz-stem{font-size:16px;font-weight:600;white-space:pre-wrap;margin-bottom:14px}
.qz-mat{border-left:3px solid var(--border);background:var(--bg-soft);padding:10px 14px;
  border-radius:0 10px 10px 0;font-size:14px;font-weight:400;color:var(--muted);
  margin-bottom:12px;white-space:pre-wrap}
.qz-opts{display:flex;flex-direction:column;gap:9px}
.qz-opt{display:flex;gap:10px;align-items:flex-start;border:1.5px solid var(--border);border-radius:11px;
  padding:11px 14px;cursor:pointer;font-size:14.5px;background:var(--panel);color:var(--text);
  text-align:left;width:100%;transition:transform .1s,border-color .1s,background .1s;font-family:inherit}
.qz-opt:not(.locked):hover{border-color:var(--accent);transform:translateX(2px)}
.qz-opt .ltr{font-weight:700;color:var(--accent);flex:0 0 auto}
.qz-opt.right{border-color:var(--ok);background:rgba(52,211,153,.10)}
.qz-opt.right .ltr{color:var(--ok)}
.qz-opt.wrong{border-color:var(--bad);background:rgba(248,113,113,.10)}
.qz-opt.wrong .ltr{color:var(--bad)}
.qz-opts.locked .qz-opt{cursor:default}
@keyframes qzflash{0%{transform:scale(.985)}50%{transform:scale(1.01)}100%{transform:scale(1)}}
.qz-opt.right,.qz-opt.wrong{animation:qzflash .25s ease}
.qz-verdict{margin-top:12px;border-radius:11px;padding:11px 14px;font-size:13.5px}
.qz-verdict.ok{background:rgba(52,211,153,.12);color:var(--ok)}
.qz-verdict.bad{background:rgba(248,113,113,.12);color:var(--bad)}
.qz-ta{width:100%;min-height:170px;border:1.5px solid var(--border);border-radius:11px;
  padding:12px 14px;font-size:14.5px;font-family:inherit;resize:vertical;background:var(--panel);color:var(--text)}
.qz-ta:focus{outline:none;border-color:var(--accent)}
.qz-ref{margin-top:12px;background:var(--bg-soft);border:1px solid var(--border);border-radius:11px;
  padding:12px 15px;font-size:14px;white-space:pre-wrap}
.qz-ref .rt{font-weight:700;color:var(--accent);font-size:12.5px;display:block;margin-bottom:6px}
.qz-btnrow{display:flex;gap:10px;margin-top:14px;flex-wrap:wrap;align-items:center}
.qz-spin{display:inline-block;width:14px;height:14px;border:2px solid var(--border);border-top-color:var(--accent);
  border-radius:50%;animation:qzrot .8s linear infinite;vertical-align:-2px;margin-right:6px}
@keyframes qzrot{to{transform:rotate(360deg)}}
@media(max-width:900px){
  .qz-layout{flex-direction:column}
  .qz-side{position:static;width:100%;flex:none;order:2}
  .qz-ansgrid{max-height:230px}
  .qz-stem{font-size:15px}
}`;
    document.head.appendChild(s);
  }

  function markNav() {
    $$("#flowNav .flow-item").forEach(el => el.classList.remove("active"));
    const qz = $("#quizNavItem");
    if (qz) qz.classList.add("active");
  }

  /* ---------- Hub：题库包列表 ---------- */
  function packProgress(pk) {
    const p = getProg(pk.id);
    const c = Object.values(p.choice), s = Object.values(p.subj).filter(x => x.self);
    const ok = c.filter(x => x.ok).length + s.filter(x => x.self === "good").length;
    const done = c.length + s.length, total = pk.n_choice + pk.n_subjective;
    return { done, ok, total, pct: total ? Math.round(done / total * 100) : 0,
             acc: done ? Math.round(ok / done * 100) : null };
  }

  async function hub() {
    ensureStyles(); markNav();
    if (!packs) {
      try { packs = await api("/quiz/packs"); }
      catch (e) { setView(`<div class="card">加载题库包失败：${esc(e.message)}</div>`); return; }
    }
    const cards = packs.map(pk => {
      const pr = packProgress(pk);
      const acc = pr.acc != null
        ? `<span class="acc ${pr.acc >= 80 ? "qz-acc-ok" : "qz-acc-bad"}">正确率 ${pr.acc}%</span>` : "未开始";
      return `<div class="qz-pack" onclick="QZ.openPack('${pk.id}')">
        <div class="emoji">${pk.origin === "seed" ? "📕" : pk.origin === "import-llm" ? "🤖" : "📗"}</div>
        <h3>${esc(pk.name)}</h3>
        <div class="desc">${esc(pk.desc)}</div>
        <div class="qz-meta"><span>✅ <b>${pk.n_choice}</b> 选择</span><span>✍️ <b>${pk.n_subjective}</b> 非选择</span></div>
        <div class="qz-pbar"><i style="width:${pr.pct}%"></i></div>
        <div class="qz-pstat"><span>已刷 ${pr.done}/${pr.total}</span>${acc}</div>
        ${pk.origin !== "seed" ? `<button class="qz-del" onclick="event.stopPropagation();QZ.delPack('${pk.id}','${esc(pk.name)}')">删除此题库包</button>` : ""}
      </div>`;
    }).join("");
    setView(`
    <div class="qz-head">
      <h2>📚 刷题中心</h2>
      <span class="qz-hint">每个题库包独立记录进度与正确率 · 模版通用：单选即点即判，非选择自评</span>
    </div>
    <div class="qz-grid">
      ${cards}
      <div class="qz-import" onclick="QZ.toggleImport()">
        <div class="emoji">➕</div><h3>导入新题库</h3>
        <p>贴入学习资料（教材 / 讲义 / 考纲），AI 按同一套刷题模版自动出题</p>
      </div>
    </div>
    <div class="card qz-panel" id="qzImportPanel" style="display:none">
      <h3 style="margin-bottom:4px">🤖 AI 导入题库</h3>
      <p class="qz-hint">资料越结构化出题越准（建议 2000 字以上）。生成约需 30~90 秒。</p>
      <div class="field" style="margin-top:10px"><label class="label">题库包名称</label>
        <input class="input" id="qzImpName" placeholder="如：软考中级 · 信息安全"></div>
      <div class="field"><label class="label">学习资料原文</label>
        <textarea class="qz-ta" id="qzImpText" style="min-height:200px" placeholder="粘贴资料原文…（至少 100 字）"></textarea></div>
      <div class="qz-btnrow">
        <button class="btn btn-primary" id="qzImpBtn" onclick="QZ.doImport()">开始生成</button>
      </div>
      <div class="qz-hint" id="qzImpStatus" style="margin-top:10px"></div>
    </div>`);
  }

  function toggleImport() {
    const p = $("#qzImportPanel");
    p.style.display = p.style.display === "none" ? "block" : "none";
    if (p.style.display === "block") p.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function doImport() {
    const name = $("#qzImpName").value.trim(), text = $("#qzImpText").value.trim();
    if (text.length < 100) return toast("资料太短，至少 100 字", "bad");
    const btn = $("#qzImpBtn"); btn.disabled = true;
    const st = $("#qzImpStatus");
    st.innerHTML = `<span class="qz-spin"></span>AI 正在通读资料并命题，请稍候…（30~90 秒）`;
    try {
      const d = await api("/quiz/packs/import", { method: "POST", body: { name, text } });
      st.textContent = `✅ 生成完成：${d.n_choice} 选择 + ${d.n_subjective} 非选择，正在进入…`;
      packs = null; openPack(d.id);
    } catch (e) {
      btn.disabled = false;
      st.innerHTML = e.message.includes("未配置 LLM")
        ? `⚠️ ${esc(e.message)}<br>配置：在启动命令里设置 <b>FT_LLM_API_KEY</b>（智谱 GLM 等 OpenAI 兼容服务均可）后重启；或者直接把资料发给 ZCode 助手生成题库包。`
        : `❌ ${esc(e.message)}`;
    }
  }

  async function delPack(pid, name) {
    if (!confirm(`确定删除题库包「${name}」？该包的刷题进度也会一并失效。`)) return;
    try { await api("/quiz/packs/" + pid, { method: "DELETE" }); toast("已删除"); packs = null; hub(); }
    catch (e) { toast("删除失败：" + e.message, "bad"); }
  }

  /* ---------- 包内刷题 ---------- */
  function list() {
    const arr = module === "choice" ? bank.choice : bank.subjective;
    return arr.filter(q =>
      (setF === "all" || q.set === setF) &&
      (!wrongOnly || (module === "choice" ? prog.choice[q.id]?.ok === false : prog.subj[q.id]?.self === "bad")));
  }
  function cur() { const l = list(); return l[Math.min(idx, l.length - 1)]; }
  function modStat(m) {
    if (m === "choice") {
      const e = Object.values(prog.choice), ok = e.filter(x => x.ok).length;
      return { done: e.length, ok, total: bank.choice.length };
    }
    const e = Object.values(prog.subj).filter(x => x.self), ok = e.filter(x => x.self === "good").length;
    return { done: e.length, ok, total: bank.subjective.length };
  }
  function accHtml(s) {
    if (!s.done) return `<span>正确率 --</span>`;
    const a = Math.round(s.ok / s.done * 100);
    return `<span>正确率 <b class="${a >= 80 ? "qz-acc-ok" : "qz-acc-bad"}">${a}%</b></span>`;
  }
  function setList() { return [...new Set([...bank.choice.map(q => q.set), ...bank.subjective.map(q => q.set)])]; }

  async function openPack(pid) {
    ensureStyles(); markNav();
    try {
      bank = await api("/quiz/packs/" + pid);
      packMeta = { id: pid, name: bank.name };
      prog = getProg(pid);
      module = "choice"; setF = "all"; wrongOnly = false;
      const first = bank.choice.findIndex(q => !prog.choice[q.id]);
      idx = first >= 0 ? first : 0;
      if (location.hash !== "#/quiz/pack/" + pid) location.hash = "#/quiz/pack/" + pid;
      render();
    } catch (e) { toast("加载题库失败：" + e.message, "bad"); }
  }
  async function packRoute(pid) {
    if (bank && packMeta && packMeta.id === pid) { render(); return; }
    openPack(pid);
  }
  function backHub() { location.hash = "#/quiz"; }

  function render() {
    clearTimeout(advTimer);
    markNav();   // route() 的 markStep(0) 会清掉高亮，渲染后重新点亮
    const cs = modStat("choice"), ss = modStat("subj");
    const l = list();
    if (!l.length) return renderEmpty();
    idx = Math.max(0, Math.min(idx, l.length - 1));
    const q = cur();
    const rec = module === "choice" ? prog.choice[q.id] : prog.subj[q.id];
    const body = module === "choice" ? renderChoice(q, rec) : renderSubj(q, rec);
    const sets = setList();

    setView(`
    <div class="qz-head">
      <h2>${esc(packMeta.name)}</h2>
      <a href="javascript:QZ.backHub()">← 返回刷题中心</a>
    </div>
    <div class="tabs mb14">
      <div class="tab ${module === "choice" ? "on" : ""}" onclick="QZ.switchMod('choice')">✅ 选择题<span class="qz-tag" style="margin-left:6px">${cs.done}/${cs.total} · ${cs.done ? Math.round(cs.ok / cs.done * 100) + "%" : "--"}</span></div>
      <div class="tab ${module === "subj" ? "on" : ""}" onclick="QZ.switchMod('subj')">✍️ 非选择题<span class="qz-tag" style="margin-left:6px">${ss.done}/${ss.total}${ss.done ? " · " + Math.round(ss.ok / ss.done * 100) + "%" : ""}</span></div>
    </div>
    <div class="qz-filters">
      <button class="qz-fchip ${setF === "all" ? "on" : ""}" onclick="QZ.setSet('all')">全部</button>
      ${sets.map(s => `<button class="qz-fchip ${setF === s ? "on" : ""}" onclick="QZ.setSet('${s}')">${s === "练" ? "练习卷" : "模拟卷" + s}</button>`).join("")}
      <button class="qz-fchip ${wrongOnly ? "on" : ""}" onclick="QZ.toggleWrong()">🔥 只刷错题</button>
      <button class="qz-fchip" onclick="QZ.resetMod()">清空本包进度</button>
      <span class="qz-stat">${accHtml(module === "choice" ? cs : ss)} · 本轮 ${idx + 1}/${l.length}</span>
    </div>
    <div class="qz-layout">
      <div class="qz-main"><div class="card">${body}</div></div>
      ${renderSide(l)}
    </div>`);
    const cc = document.querySelector(".qz-cell.cur");
    if (cc) cc.scrollIntoView({ block: "nearest" });
  }

  function renderEmpty() {
    const cs = modStat("choice"), ss = modStat("subj");
    setView(`
    <div class="qz-head"><h2>${esc(packMeta.name)}</h2><a href="javascript:QZ.backHub()">← 返回刷题中心</a></div>
    <div class="card" style="text-align:center;padding:44px 18px">
      <div style="font-size:40px">🎉</div>
      <p style="font-weight:700;font-size:17px;margin-top:8px">当前筛选下没有题目</p>
      <p class="qz-hint">可能这组题目都已做对，或进度已清空。</p>
      <div class="qz-btnrow" style="justify-content:center">
        <button class="btn btn-primary" onclick="QZ.wrongOnly=false;QZ.setSet('all')">看全部题目</button>
      </div>
    </div>`);
  }

  function cellState(q) {
    if (module === "choice") {
      const r = prog.choice[q.id]; if (!r) return { cls: "", ans: "" };
      return { cls: r.ok ? "ok" : "bad", ans: "ABCD"[q.answer[0]] };
    }
    const r = prog.subj[q.id];
    if (!r) return { cls: "", ans: "" };
    if (r.self === "good") return { cls: "ok", ans: "✓" };
    if (r.self === "bad") return { cls: "bad", ans: "✗" };
    return { cls: "", ans: "" };
  }
  function renderSide(l) {
    const cells = l.map((q, i) => {
      const st = cellState(q);
      return `<button class="qz-cell ${st.cls} ${i === idx ? "cur" : ""}" onclick="QZ.jump(${i})" title="${q.set}·第${q.no}题">
        <span class="num">${q.no}</span><span class="ans">${st.ans}</span></button>`;
    }).join("");
    const done = l.filter(q => cellState(q).cls).length;
    return `<div class="qz-side"><div class="card">
      <h4>答题卡 <span class="qz-lg"><span><i class="g"></i>对</span><span><i class="r"></i>错</span></span></h4>
      <div class="qz-ansgrid">${cells}</div>
      <div class="qz-hint" style="margin-top:7px">${module === "choice"
        ? `刮刮乐：做一题揭一题，格子亮出正确答案（${done}/${l.length}）`
        : `自评一题揭一题：✓ / ✗（${done}/${l.length}）`}</div>
    </div></div>`;
  }

  function splitMat(stem) {
    const i = stem.indexOf("【材料】");
    if (i < 0) return { mat: null, body: stem };
    return { mat: stem.slice(i + 4, stem.indexOf("【题目】")), body: stem.slice(stem.indexOf("【题目】") + 4) };
  }
  function renderChoice(q, rec) {
    const { mat, body } = splitMat(q.stem);
    const locked = !!rec;
    const opts = q.options.map((o, i) => {
      let cls = "qz-opt" + (locked ? " locked" : "");
      if (locked) {
        if (rec.pick.includes(i)) cls += rec.ok ? " right" : " wrong";
        if (q.answer.includes(i)) cls += " right";
      }
      return `<button class="${cls}" onclick="QZ.pickOpt(${i})">
        <span class="ltr">${"ABCD"[i]}.</span><span>${esc(o)}</span></button>`;
    }).join("");
    const verdict = locked ? (rec.ok
      ? `<div class="qz-verdict ok"><b>✓ 答对了</b></div>`
      : `<div class="qz-verdict bad"><b>✗ 答错了</b>　正确答案：${q.answer.map(a => "ABCD"[a]).join("")}　你选了：${rec.pick.map(a => "ABCD"[a]).join("")}</div>`)
      : `<p class="qz-hint" style="margin-top:10px">点击选项立即判定并自动跳下一题 · 只有一次机会，想清楚再点 🔍</p>`;
    const ana = (locked && q.analysis) ? `<div class="qz-ref"><span class="rt">📖 解析</span>${esc(q.analysis)}</div>` : "";
    return `
    <div class="qz-qmeta"><span class="qz-tag">${q.set === "练" ? "练习卷" : "模拟卷" + q.set}</span><span>第 ${q.no} 题</span><span>· 单选</span><span>· ${q.score} 分</span></div>
    ${mat ? `<div class="qz-mat">${esc(mat)}</div>` : ""}
    <div class="qz-stem">${esc(body)}</div>
    <div class="qz-opts ${locked ? "locked" : ""}">${opts}</div>
    ${verdict}${ana}
    <div class="qz-btnrow">
      <button class="btn btn-ghost" onclick="QZ.prev()" ${idx === 0 ? "disabled" : ""}>← 上一题</button>
      ${locked ? `<button class="btn btn-ghost" onclick="QZ.redo('${q.id}')">重做本题</button>` : ""}
      <button class="btn btn-primary" onclick="QZ.next()" ${idx >= list().length - 1 ? "disabled" : ""}>下一题 →</button>
    </div>`;
  }
  function pickOpt(i) {
    const q = cur();
    if (prog.choice[q.id]) return;
    const ok = q.answer.length === 1 && q.answer[0] === i;
    prog.choice[q.id] = { pick: [i], ok }; save();
    render();
    advTimer = setTimeout(() => next(), ok ? 280 : 600);
  }
  function redo(id) { delete prog.choice[id]; save(); render(); }

  function renderSubj(q, rec) {
    const { mat, body } = splitMat(q.stem);
    const text = rec?.text || "";
    const revealed = rec?.revealed;
    const self = rec?.self;
    return `
    <div class="qz-qmeta"><span class="qz-tag">${q.set === "练" ? "练习卷" : "模拟卷" + q.set}</span><span>第 ${q.no} 题</span><span>· ${q.kind || "问答"}</span><span>· ${q.score} 分</span></div>
    ${mat ? `<div class="qz-mat">${esc(mat)}</div>` : ""}
    <div class="qz-stem">${esc(body)}</div>
    <textarea class="qz-ta" id="subjTa" placeholder="在此写下你的作答（自动保存，刷新不丢）…"
      oninput="QZ.saveText()">${esc(text)}</textarea>
    ${revealed ? `<div class="qz-ref"><span class="rt">📖 参考答案 / 评分要点</span>${esc(q.analysis || "（暂无）")}</div>` : ""}
    <div class="qz-btnrow">
      <button class="btn btn-ghost" onclick="QZ.prev()" ${idx === 0 ? "disabled" : ""}>← 上一题</button>
      ${!revealed ? `<button class="btn" onclick="QZ.reveal()">查看参考答案</button>` : ""}
      ${revealed && !self ? `<span class="qz-hint">对照参考答案自评：</span>` : ""}
      ${revealed ? `
        <button class="btn ${self === "good" ? "btn-primary" : ""}" style="${self === "good" ? "background:var(--ok);border-color:var(--ok)" : ""}" onclick="QZ.selfJudge('good')">✓ 我答上了</button>
        <button class="btn ${self === "bad" ? "btn-primary" : ""}" style="${self === "bad" ? "background:var(--bad);border-color:var(--bad)" : ""}" onclick="QZ.selfJudge('bad')">✗ 没答好</button>` : ""}
      <button class="btn btn-primary" onclick="QZ.next()" ${idx >= list().length - 1 ? "disabled" : ""}>下一题 →</button>
    </div>`;
  }
  function saveText() {
    const q = cur();
    prog.subj[q.id] = prog.subj[q.id] || {};
    prog.subj[q.id].text = $("#subjTa").value; save();
  }
  function reveal() {
    const q = cur();
    prog.subj[q.id] = prog.subj[q.id] || {}; prog.subj[q.id].revealed = true; save(); render();
  }
  function selfJudge(v) {
    const q = cur();
    prog.subj[q.id] = prog.subj[q.id] || {}; prog.subj[q.id].self = v; prog.subj[q.id].revealed = true; save();
    render();
  }

  function jump(i) {
    idx = i; render();
    document.querySelector(".qz-main").scrollIntoView({ behavior: "smooth", block: "start" });
  }
  function next() { const l = list(); if (idx < l.length - 1) jump(idx + 1); else { toast("已是最后一题"); render(); } }
  function prev() { if (idx > 0) jump(idx - 1); }
  function switchMod(m) { module = m; setF = "all"; wrongOnly = false; idx = 0; render(); }
  function setSet(s) { setF = s; idx = 0; render(); }
  function toggleWrong() {
    wrongOnly = !wrongOnly; idx = 0; render();
    if (wrongOnly) toast(list().length ? `已筛选 ${list().length} 道错题` : "当前没有错题");
  }
  function resetMod() {
    const name = module === "choice" ? "选择题" : "非选择题";
    if (!confirm(`确定清空本包「${name}」的作答进度？`)) return;
    if (module === "choice") prog.choice = {}; else prog.subj = {};
    save(); idx = 0; render(); toast("已清空");
  }

  return { hub, openPack, packRoute, backHub, toggleImport, doImport, delPack,
           pickOpt, redo, saveText, reveal, selfJudge,
           jump, next, prev, switchMod, setSet, toggleWrong, resetMod,
           get wrongOnly() { return wrongOnly; }, set wrongOnly(v) { wrongOnly = v; } };
})();
