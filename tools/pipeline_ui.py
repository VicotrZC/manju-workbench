#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""漫剧管线 · 可视化界面（**只用标准库**，不起第二个服务）。

    python tools/pipeline.py ui <项目> [--scene SCN-01] [--port 8788]

打开 http://127.0.0.1:8788

## 它显示什么

- 左边：11 个阶段的流水线卡片 —— 状态灯 / 执行者 / ERROR 数 / 是否要封条
- 右边：选中阶段的详情 —— **为什么有这一阶段**、**该读哪些方法文件**、
  现场跑出来的门禁逐条、产出文件与哈希、@当前卡点@ 的下一步
- 顶上：全阶段通过数 / 当前卡在哪 / 重跑按钮 / 场次切换

## 一条硬设计

**页面上的每个状态都是点开时现算的**（调 `pipeline.scan()`），不读缓存、不存快照。
因为整个管线的目的就是「程序兜底」—— 如果界面显示的是上次算的结论，
那它就和大模型凭记忆汇报一样不可信。
"""
from __future__ import annotations

import io
import json
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import pipeline as P  # noqa: E402

def get_state(proj: Path, scene: str | None, refresh: bool = False) -> dict:
    """**不缓存。** 每次请求现场重跑全部门禁。

    2026-09-21 实测：一次完整 `scan()` 只要 **0.42 秒**，缓存省不下什么。
    而它会造成一个直接自相矛盾的后果 ——
    **界面上显示的可能是你改之前的状态**（实测：`scaffold` 写完资产清单之后，
    页面还显示 S4 不过）。那正是本管线要消灭的东西：
    「程序兜底」如果兜的是上次算的结论，就退化成「程序凭记忆汇报」。

    `refresh` 参数保留只为兼容旧链接，现在无论真假都重算。
    """
    return P.scan(proj, scene)


# ══════════════════════════════════════════════════════════════════════
#  「点一下真的往下做」—— 每个阶段一个动作
# ══════════════════════════════════════════════════════════════════════
#: `kind`：prog = 程序自己跑；gen = 调模型生成；chain = 多步串起来；user = 只能人做
ACTIONS: dict[str, dict] = {
    "S0":  {"kind": "user", "label": "换场次（用上面的下拉框）"},
    "S1":  {"kind": "gen", "argv": ["gen", "S1"], "label": "让模型写剧本",
            "note": "S1 生成规格还没做（目前支持 S2 / S4 / S7）"},
    "S2":  {"kind": "gen", "argv": ["gen", "S2", "--rounds", "3"],
            "label": "让模型写分镜（不过就自动打回重做，最多 3 轮）"},
    "S3":  {"kind": "prog", "argv": ["gate", "S3"], "label": "跑「验分镜」门禁"},
    "S4":  {"kind": "gen", "argv": ["gen", "S4", "--rounds", "3"],
            "label": "让模型抽角色／道具／场景"},
    "S5":  {"kind": "prog", "argv": ["gate", "S5"], "label": "跑「验资产」门禁"},
    "S6":  {"kind": "gen", "argv": ["gen", "S6"], "label": "让模型写提示词",
            "note": "S6 生成规格还没做（每镜一条工作流，要逐镜跑）"},
    "S7":  {"kind": "chain", "label": "审查提示词：出审计包 → 模型判定 → 程序封存",
            "steps": [["audit-all"], ["gen", "S7"], ["seal-all"]]},
    "S8":  {"kind": "prog", "argv": ["run"], "label": "连服务器生成（先过 S7 才放行）",
            "cost": "会真的占云机 GPU，按小时计费"},
    "S9":  {"kind": "prog", "argv": ["qc", "--write"], "label": "机械合规检查并落盘"},
    "S10": {"kind": "chain", "label": "流程审计（出包 → 模型审 → 封存）",
            "steps": [["postflight"], ["gen", "S10"], ["seal-all"]]},
}


class Job:
    """一个后台动作。页面轮询它的 log。"""

    _n = 0

    def __init__(self, proj_name: str, stage: str, argv_sets: list[list[str]],
                 scene: str | None):
        Job._n += 1
        self.id = f"j{Job._n}"
        self.proj_name = proj_name
        self.stage = stage
        self.argv_sets = argv_sets
        self.scene = scene
        self.log: list[str] = []
        self.status = "running"
        self.rc: int | None = None
        self.t = threading.Thread(target=self._run, daemon=True)
        self.t.start()

    def _run(self):
        import subprocess
        try:
            for argv in self.argv_sets:
                head, rest = argv[0], list(argv[1:])
                cmd = [sys.executable, str(ROOT / "tools" / "pipeline.py"),
                       head, self.proj_name, *rest]
                if self.scene:
                    cmd += ["--scene", self.scene]
                self.log.append(f"$ python tools/pipeline.py {' '.join(cmd[2:])}\n\n")
                r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True,
                                   text=True, encoding="utf-8", errors="replace")
                self.log.append((r.stdout or "") + (r.stderr or ""))
                if r.returncode != 0:
                    self.log.append(f"\n⛔ 这一步返回 {r.returncode} —— 停下，不往下跑。\n")
                    self.status, self.rc = "failed", r.returncode
                    return
            self.status, self.rc = "done", 0
            self.log.append("\n✅ 这一步做完了。点「↻ 重跑全部门禁」看结果。\n")
        except Exception as exc:                       # noqa: BLE001
            self.status, self.rc = "error", -1
            self.log.append(f"\n💥 {exc!r}\n")

    def text(self) -> str:
        return "".join(self.log)[-40000:]


JOBS: dict[str, Job] = {}


PAGE = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>漫剧管线 · __PROJ__</title>
<style>
:root{
  --bg:#0f1216; --panel:#171b21; --panel2:#1e242c; --line:#2b333d;
  --fg:#e6ebf2; --dim:#8b98a8; --pass:#3fb950; --fail:#f85149; --warn:#d29922;
  --agent:#a371f7; --prog:#2f81f7; --user:#e3b341;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
  font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
header{padding:14px 20px;border-bottom:1px solid var(--line);
  display:flex;align-items:center;gap:16px;flex-wrap:wrap;background:var(--panel)}
h1{font-size:16px;margin:0;font-weight:600}
.sub{color:var(--dim);font-size:12px}
button{background:var(--panel2);color:var(--fg);border:1px solid var(--line);
  border-radius:6px;padding:6px 12px;cursor:pointer;font-size:13px}
button:hover{border-color:#3d4b5c;background:#232a33}
select{background:var(--panel2);color:var(--fg);border:1px solid var(--line);
  border-radius:6px;padding:6px 8px;font-size:13px}
.wrap{display:flex;height:calc(100vh - 58px);overflow:hidden}
.left{width:430px;min-width:430px;overflow-y:auto;border-right:1px solid var(--line);
  padding:12px}
.right{flex:1;overflow-y:auto;padding:18px 22px}
.card{background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--line);
  border-radius:8px;padding:10px 12px;margin-bottom:8px;cursor:pointer;transition:.12s}
.card:hover{background:var(--panel2)}
.card.sel{border-color:#3d4b5c;background:var(--panel2);box-shadow:0 0 0 1px #3d4b5c}
.card.pass{border-left-color:var(--pass)}
.card.fail{border-left-color:var(--fail)}
.row{display:flex;align-items:center;gap:8px}
.id{font-family:ui-monospace,Consolas,monospace;color:var(--dim);font-size:12px;width:30px}
.nm{font-weight:600;flex:1}
.badge{font-size:11px;padding:1px 7px;border-radius:10px;border:1px solid}
.b-agent{color:var(--agent);border-color:var(--agent)}
.b-prog{color:var(--prog);border-color:var(--prog)}
.b-user{color:var(--user);border-color:var(--user)}
.cnt{font-size:12px;font-family:ui-monospace,monospace}
.e{color:var(--fail)} .w{color:var(--warn)} .p{color:var(--pass)}
.wait{color:var(--dim);font-size:12px;margin-top:2px}
.why{color:var(--dim);font-size:12px;margin-top:5px;display:none}
.card.sel .why{display:block}
.item{border-left:3px solid var(--line);padding:7px 11px;margin:6px 0;
  background:var(--panel);border-radius:0 6px 6px 0}
.item.ERROR{border-left-color:var(--fail)} .item.WARN{border-left-color:var(--warn)}
.item.INFO{border-left-color:var(--prog)}
.code{font-family:ui-monospace,monospace;font-size:11px;color:var(--dim);margin-right:8px}
.fix{color:var(--dim);font-size:12px;margin-top:4px}
.kv{color:var(--dim);font-size:12px;margin-top:3px}
h2{font-size:15px;margin:0 0 4px}
h3{font-size:13px;color:var(--dim);margin:20px 0 8px;
  text-transform:uppercase;letter-spacing:.06em;font-weight:600}
code{background:var(--panel2);padding:1px 6px;border-radius:4px;
  font-family:ui-monospace,Consolas,monospace;font-size:12px}
pre{background:var(--panel);border:1px solid var(--line);border-radius:8px;
  padding:12px;overflow-x:auto;font-size:12px;margin:8px 0}
table{width:100%;border-collapse:collapse;font-size:12.5px}
td,th{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line)}
th{color:var(--dim);font-weight:500}
.empty{color:var(--dim);padding:40px;text-align:center}
.lock{font-size:12px}
.bar{height:6px;background:var(--panel2);border-radius:3px;overflow:hidden;
  width:220px;display:inline-block;vertical-align:middle}
.bar>i{display:block;height:100%;background:var(--pass)}
.banner{padding:9px 20px;background:#1d232b;border-bottom:1px solid var(--line);
  font-size:13px}
.banner b{color:var(--fail)}
.tabs{display:flex;gap:6px;margin-left:auto}
.tab{padding:6px 14px;border:1px solid var(--line);border-radius:6px;
  cursor:pointer;background:var(--panel2);font-size:13px}
.tab.on{background:#2b3644;border-color:#4a5b70;font-weight:600}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
.card2{background:var(--panel);border:1px solid var(--line);border-radius:8px;
  padding:10px;display:flex;flex-direction:column;gap:8px}
.card2 img{width:100%;border-radius:6px;background:#000;display:block;
  max-height:400px;object-fit:contain}
.card2 video{width:100%;border-radius:6px;background:#000;display:block}
.card2 .cap{font-size:12.5px;font-weight:600;line-height:1.4}
.meta{font-size:11.5px;color:var(--dim);font-family:ui-monospace,monospace}
.pill{display:inline-block;font-size:11px;padding:1px 7px;border-radius:9px;
  border:1px solid var(--line);margin-right:5px}
.pill.ok{color:var(--pass);border-color:var(--pass)}
.pill.bad{color:var(--fail);border-color:var(--fail)}
.grp{margin:22px 0 10px;font-size:14px;font-weight:600;
  border-bottom:1px solid var(--line);padding-bottom:6px}
.grp span{color:var(--dim);font-weight:400;font-size:12px;margin-left:8px}
</style></head><body>
<header>
  <h1>漫剧管线</h1>
  <span class="sub" id="proj">__PROJ__</span>
  <select id="scene"></select>
  <button onclick="load(true)">↻ 重跑全部门禁</button>
  <span class="bar"><i id="bar" style="width:0%"></i></span>
  <span class="sub" id="score">—</span>
  <span class="sub" id="ts"></span>
  <div class="tabs">
    <div class="tab on" id="t1" onclick="tab('pipe')">管线</div>
    <div class="tab" id="t2" onclick="tab('media')">资源与成片</div>
  </div>
</header>
<div class="banner" id="banner">载入中…</div>
<div class="wrap" id="vpipe">
  <div class="left" id="list"></div>
  <div class="right" id="detail"><div class="empty">点左边任一阶段看详情</div></div>
</div>
<div class="wrap" id="vmedia" style="display:none">
  <div class="right" id="media" style="padding:18px 22px">
    <div class="empty">载入中…</div>
  </div>
</div>
<script>
let STATE=null, SEL=null;
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

async function load(refresh){
  const sc=$('#scene').value||'';
  const r=await fetch('/api/state?refresh='+(refresh?1:0)+'&scene='+encodeURIComponent(sc));
  STATE=await r.json();
  if(!SEL) SEL=STATE.next_action||STATE.stages[0].id;
  render();
}
function render(){
  const st=STATE.stages, ok=st.filter(s=>s.status==='pass').length;
  $('#bar').style.width=(ok/st.length*100)+'%';
  $('#score').textContent=`${ok}/${st.length} 阶段通过`;
  $('#ts').textContent='现场核验 '+STATE.checked_at.replace('T',' ');
  $('#proj').textContent=STATE.project+' · '+STATE.scene.id+' '+(STATE.scene.name||'');
  const sel=$('#scene');
  if(sel.options.length===0){
    (STATE.all_scenes||[STATE.scene]).forEach(s=>{
      const o=document.createElement('option'); o.value=s.id;
      o.textContent=s.id+' '+(s.name||''); sel.appendChild(o);});
    sel.value=STATE.scene.id;
  }
  const nx=STATE.next_action;
  $('#banner').innerHTML = nx
    ? `👉 当前卡在 <b>${nx}</b> ${esc(st.find(s=>s.id===nx).name)} —— 门禁没过的阶段，后面的都轮不到`
    : `🎬 11 个阶段全部通过`;
  $('#list').innerHTML=st.map(s=>`
    <div class="card ${s.status} ${s.id===SEL?'sel':''}" onclick="pick('${s.id}')">
      <div class="row">
        <span class="id">${s.id}</span>
        <span class="nm">${esc(s.name)}</span>
        <span class="badge b-${s.executor}">${{prog:'程序',agent:'agent',user:'用户'}[s.executor]}</span>
        ${s.seal_required?'<span class="lock">🔒</span>':''}
        <span class="cnt ${s.status==='pass'?'p':'e'}">
          ${s.status==='pass'?'✓':'✗ '+s.report.errors}</span>
      </div>
      ${s.waiting_on&&s.status!=='pass'?`<div class="wait">轮不到：上面卡在 ${s.waiting_on}</div>`:''}
      <div class="why">${esc(s.why)}</div>
    </div>`).join('');
  if(SEL) detail(SEL);
}
function pick(id){SEL=id; render();}
function detail(id){
  const s=STATE.stages.find(x=>x.id===id); if(!s) return;
  const items=s.report.items||[];
  const ord={ERROR:0,WARN:1,INFO:2};
  items.sort((a,b)=>ord[a.level]-ord[b.level]);
  const arts=Object.entries(s.artifacts||{});
  $('#detail').innerHTML=`
    <h2>${s.id} · ${esc(s.name)}</h2>
    <div class="sub">执行者：${{prog:'程序（机械可判）',agent:'agent（创作／语义判断）',user:'用户（审美／花钱）'}[s.executor]}
      ${s.seal_required?'　·　🔒 必须留判定封条':''}</div>
    <h3>为什么有这一阶段</h3><div>${esc(s.why)}</div>
    <h3>该先读这些方法（不要凭记忆写）</h3>
    ${(s.methods||[]).length?`<table><tr><th>文件</th></tr>${
      s.methods.map(m=>`<tr><td><code>${esc(m)}</code></td></tr>`).join('')}</table>`
      :'<div class="sub">（这一阶段不需要读方法文件）</div>'}
    <h3>门禁（每次点开现算）</h3>
    ${items.length?items.map(i=>`
      <div class="item ${i.level}">
        <span class="code">${esc(i.code)}</span>${esc(i.msg)}
        ${Object.entries(i).filter(([k])=>!['level','code','msg'].includes(k))
          .map(([k,v])=>`<div class="kv">${k}: ${esc(Array.isArray(v)?v.join(' / '):v)}</div>`).join('')}
        ${i.fix?`<div class="fix">→ ${esc(i.fix)}</div>`:''}
      </div>`).join(''):'<div class="sub">无记录</div>'}
    <h3>产出（含哈希前缀）</h3>
    ${arts.length?`<table><tr><th>文件</th><th>sha256／大小</th></tr>${
      arts.map(([k,v])=>`<tr><td>${esc(k)}</td><td><code>${esc(v)}</code></td></tr>`).join('')}</table>`
      :'<div class="sub">（这一阶段没有文件产出）</div>'}
    <h3>下一步怎么走</h3>
    <div id="act"></div>
    <pre id="logbox" style="display:none"></pre>
  `;
  renderAct(s);
}

function renderAct(s){
  const a=(STATE.actions||{})[s.id];
  const box=$('#act');
  if(!a){ box.innerHTML='<div class="sub">（这一阶段没有动作）</div>'; return; }
  const cls=a.kind==='prog'?'b-prog':(a.kind==='user'?'b-user':'b-agent');
  let h=`<div class="row" style="margin:8px 0">
      <button class="go" onclick="go('${s.id}')">▶ ${esc(a.label)}</button>
      <span class="badge ${cls}">${{prog:'程序跑',gen:'调模型',chain:'多步',user:'人做'}[a.kind]}</span>
    </div>`;
  if(a.cost) h+=`<div class="fix">⚠️ ${esc(a.cost)}</div>`;
  if(a.note) h+=`<div class="fix">ℹ️ ${esc(a.note)}</div>`;
  if(a.kind==='gen') h+=`<div class="fix">这一步会调模型 API。没配密钥就把 llm_config.json 的 backend 设成 file，请求会进队列等人填答。</div>`;
  h+=`<pre style="margin-top:10px">python tools/pipeline.py ${a.kind==='gen'?'gen':'gate'} ${STATE.project} ${s.id} --scene ${STATE.scene.id}</pre>`;
  box.innerHTML=h;
}

let POLL=null;
async function go(stage){
  $('#logbox').style.display='block';
  $('#logbox').textContent='▶ 启动…\n';
  const r=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({stage:stage,scene:STATE.scene.id})});
  const j=await r.json();
  if(j.error){ $('#logbox').textContent='⛔ '+j.error; return; }
  clearInterval(POLL);
  POLL=setInterval(async()=>{
    const q=await fetch('/api/job?id='+j.job); const o=await q.json();
    const b=$('#logbox'); b.textContent=o.log||''; b.scrollTop=b.scrollHeight;
    if(o.status!=='running'){ clearInterval(POLL);
      b.textContent+='\n── 结束：'+o.status+'（rc='+o.rc+'）──\n';
      b.scrollTop=b.scrollHeight; }
  },900);
}
$('#scene').addEventListener('change',()=>{SEL=null;MED=null;load(true);});

// ── 资源与成片 ─────────────────────────────────────────────────────
let MED=null, TAB='pipe';
function tab(t){
  TAB=t;
  $('#t1').className='tab'+(t==='pipe'?' on':'');
  $('#t2').className='tab'+(t==='media'?' on':'');
  $('#vpipe').style.display = t==='pipe'?'flex':'none';
  $('#vmedia').style.display = t==='media'?'flex':'none';
  if(t==='media') loadMedia();
}
async function loadMedia(){
  const sc=(STATE&&STATE.scene)?STATE.scene.id:'';
  $('#media').innerHTML='<div class="empty">载入中…</div>';
  const r=await fetch('/api/media?scene='+encodeURIComponent(sc));
  MED=await r.json();
  if(MED.error){ $('#media').innerHTML='<div class="empty">⛔ '+esc(MED.error)+'</div>'; return; }
  let h=`<div class="sub" style="margin-bottom:6px">共 ${MED.total} 件 ——
    点开就能看/能放。<b>审查看这一页</b>；判断好坏只有你能做。</div>`;
  for(const g of MED.groups){
    h+=`<div class="grp">${esc(g.title)}<span>${g.items.length} 件</span></div><div class="grid">`;
    for(const it of g.items) h+=card(it);
    h+=`</div>`;
  }
  $('#media').innerHTML=h;
}
function card(it){
  const src='/media?p='+encodeURIComponent(it.rel);
  let media = it.kind==='video'
    ? `<video controls preload="metadata" src="${src}"></video>`
    : `<a href="${src}" target="_blank"><img loading="lazy" src="${src}" alt=""></a>`;
  let pills='';
  if(it.kind==='video'){
    pills+=`<span class="pill">${it.width}×${it.height}</span>`;
    pills+=`<span class="pill">${it.frames}帧 / ${it.duration_s}s</span>`;
    pills+=`<span class="pill">${it.fps}fps</span>`;
    pills+= it.has_audio
      ? `<span class="pill ok">音轨 ${it.audio_sample_rate}Hz</span>`
      : `<span class="pill bad">无音轨</span>`;
    if(it.qc_fail&&it.qc_fail.length)
      pills+=`<span class="pill bad">合规 ${it.qc_fail.length} 项不过</span>`;
    else if(it.qc_pass)
      pills+=`<span class="pill ok">机械合规 ${it.qc_pass} 项过</span>`;
  } else if(it.w){
    pills+=`<span class="pill">${it.w}×${it.h}</span>`;
  }
  if(it.shot) pills+=`<span class="pill">${it.shot}</span>`;
  if(it.kind==='video'&&it.expect_frames&&it.frames!==it.expect_frames)
    pills+=`<span class="pill bad">与镜头表不符（应 ${it.expect_frames} 帧）</span>`;
  const fails=(it.qc_fail||[]).map(x=>`<div class="meta" style="color:var(--fail)">· ${esc(x)}</div>`).join('');
  return `<div class="card2">${media}
    <div class="cap">${esc(it.label)}</div>
    <div>${pills}</div>
    <div class="meta">${esc(it.rel)}<br>${(it.size/1048576).toFixed(2)} MB · ${it.mtime}</div>
    ${fails}</div>`;
}
load(false);
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    proj: Path = None
    scene: str | None = None

    def log_message(self, *a):        # 不要往控制台刷访问日志
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except ValueError:
            body = {}
        if u.path == "/api/run":
            stage = body.get("stage")
            act = ACTIONS.get(stage)
            if not act:
                return self._json({"error": f"没有这个阶段：{stage}"})
            if act["kind"] == "user":
                return self._json({"error": act.get("label", "这一阶段只能人做")})
            argv_sets = act.get("steps") or [act["argv"]]
            j = Job(self.proj.name, stage, argv_sets, body.get("scene") or self.scene)
            JOBS[j.id] = j
            return self._json({"job": j.id, "stage": stage, "label": act["label"]})
        return self._send(404, b"not found", "text/plain")

    def _json(self, obj: dict):
        return self._send(200, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                          "application/json; charset=utf-8")

    # ── 把项目里的图/视频发给浏览器（**审查要看的东西**）──────────────
    def _media(self):
        q = parse_qs(urlparse(self.path).query)
        rel = (q.get("p", [""])[0]).replace("\\", "/").lstrip("/")
        f = (self.proj / rel).resolve()
        root = self.proj.resolve()
        # **只发项目目录里的文件** —— 挡路径穿越（../ 之类）
        if not str(f).startswith(str(root)) or not f.is_file():
            return self._send(404, b"not found", "text/plain")
        ctype = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                 ".webp": "image/webp", ".gif": "image/gif",
                 ".mp4": "video/mp4", ".webm": "video/webm"}.get(
                     f.suffix.lower(), "application/octet-stream")
        size = f.stat().st_size
        # **Range 必须支持**，否则 <video> 拖不动进度条
        rng = self.headers.get("Range") or ""
        start, end = 0, size - 1
        partial = False
        if rng.startswith("bytes="):
            spec = rng[6:].split(",")[0].strip()
            a, _, b = spec.partition("-")
            try:
                if a:
                    start = int(a)
                    end = int(b) if b else size - 1
                elif b:                       # bytes=-N 末尾 N 字节
                    start = max(0, size - int(b))
                partial = True
            except ValueError:
                start, end = 0, size - 1
                partial = False
        end = min(end, size - 1)
        if start > end or start >= size:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return
        length = end - start + 1
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with open(f, "rb") as fh:
            fh.seek(start)
            left = length
            while left > 0:
                chunk = fh.read(min(262144, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionAbortedError):
                    return
                left -= len(chunk)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            html = PAGE.replace("__PROJ__", self.proj.name)
            return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
        if u.path == "/media":
            return self._media()
        if u.path == "/api/media":
            q = parse_qs(u.query)
            scene = (q.get("scene", [None])[0]) or self.scene
            try:
                rules = P.PA.load_rules(self.proj)
                data = P.collect_media(self.proj, rules,
                                       P.pick_scene(self.proj, rules, scene))
            except SystemExit as exc:
                data = {"error": str(exc)}
            return self._json(data)
        if u.path == "/api/state":
            q = parse_qs(u.query)
            scene = (q.get("scene", [None])[0]) or self.scene
            refresh = q.get("refresh", ["0"])[0] == "1"
            try:
                data = get_state(self.proj, scene, refresh)
                data["all_scenes"] = [
                    {k: v for k, v in s.items() if k != "t"}
                    for s in P.find_scenes(self.proj, P.PA.load_rules(self.proj))]
                data["actions"] = {k: {"kind": v["kind"], "label": v["label"],
                                       "note": v.get("note"), "cost": v.get("cost")}
                                   for k, v in ACTIONS.items()}
            except SystemExit as exc:
                data = {"error": str(exc)}
            except Exception as exc:                      # noqa: BLE001
                import traceback
                data = {"error": f"{exc!r}", "trace": traceback.format_exc()}
            return self._json(data)
        if u.path == "/api/job":
            q = parse_qs(u.query)
            j = JOBS.get((q.get("id", [""])[0]))
            if not j:
                return self._json({"error": "没有这个作业"})
            return self._json({"id": j.id, "stage": j.stage, "status": j.status,
                               "rc": j.rc, "log": j.text()})
        return self._send(404, b"not found", "text/plain")


def serve(proj: Path, scene: str | None, port: int) -> int:
    Handler.proj, Handler.scene = proj, scene
    url = f"http://127.0.0.1:{port}/"
    print(f"🖥  漫剧管线界面：{url}")
    print(f"   项目 {proj.name}　场次 {scene or '（第一场）'}")
    print(f"   状态是**点开时现算**的；点「重跑全部门禁」可以强制刷新")
    print(f"   Ctrl+C 停止")
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    # 测的时候用 PIPELINE_UI_NO_OPEN=1 别弹浏览器
    import os
    if not os.environ.get("PIPELINE_UI_NO_OPEN"):
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    return 0
