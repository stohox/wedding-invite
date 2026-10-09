"""
婚礼邀请函埋点数据看板生成器
用法: python gen_track_report.py
流程: ssh 拉取 stats + 最近事件明细 -> 注入 HTML 模板 -> 生成 wedding-track-report.html
凭据: 从 track_config.py（不入库）或环境变量 TRACK_SSH_HOST / TRACK_STATS_URL 读取。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

# ---- 凭据加载：优先 track_config.py，其次环境变量 ----
try:
    from track_config import SSH_HOST, STATS_URL  # type: ignore
except ImportError:
    SSH_HOST = os.environ.get("TRACK_SSH_HOST", "")
    STATS_URL = os.environ.get("TRACK_STATS_URL", "")
if not SSH_HOST or not STATS_URL:
    sys.exit("缺少凭据：请创建 track_config.py（参考 track_config.example.py）"
             "或设置环境变量 TRACK_SSH_HOST / TRACK_STATS_URL")

OUT_HTML = Path(__file__).resolve().parent.parent / "wedding-track-report.html"

REMOTE_CODE = r'''
import json, sqlite3, urllib.request
stats = json.loads(urllib.request.urlopen("__STATS_URL__", timeout=10).read())
con = sqlite3.connect("/home/ubuntu/wedding-track/track.db")
rows = [list(r) for r in con.execute(
    "SELECT ts,sid,event,payload,province,device FROM events ORDER BY ts DESC LIMIT 300")]
total = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
con.close()
print(json.dumps({"stats": stats, "rows": rows, "total": total}))
'''.replace("__STATS_URL__", STATS_URL)

TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>婚礼邀请函 · 数据看板</title>
<script>__ECHARTS_JS__</script>
<style>.errbar{position:fixed;bottom:12px;left:12px;right:12px;background:#b4532a;color:#fff;padding:10px 14px;border-radius:8px;z-index:9999;font-size:12px}</style>
<style>
  :root{
    --bg:#faf7f2; --card:#ffffff; --ink:#3d3229; --sub:#8a7a68;
    --brand:#b4532a; --gold:#c9a227; --line:#eadfcd; --soft:#f4ede1;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--ink);
    font-family:"PingFang SC","Microsoft YaHei",system-ui,sans-serif;
    padding:28px 20px 48px;max-width:1080px;margin:0 auto}
  header{display:flex;align-items:baseline;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:20px}
  h1{font-size:24px;letter-spacing:1px}
  h1 .dot{color:var(--brand)}
  .gen{color:var(--sub);font-size:13px}
  .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:16px}
  .kpi{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px}
  .kpi .v{font-size:26px;font-weight:700;color:var(--brand)}
  .kpi .l{font-size:12px;color:var(--sub);margin-top:2px}
  .kpi .s{font-size:11px;color:var(--gold);margin-top:2px}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}
  @media(max-width:760px){.grid{grid-template-columns:1fr}}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px}
  .card h3{font-size:14px;color:var(--sub);font-weight:600;margin-bottom:8px;letter-spacing:.5px}
  .chart{height:260px}
  .chart.tall{height:300px}
  .full{margin-bottom:14px}
  table{width:100%;border-collapse:collapse;font-size:12.5px}
  th{color:var(--sub);font-weight:600;text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
  td{padding:6px 8px;border-bottom:1px solid #f3ece0;white-space:nowrap}
  tr:hover td{background:var(--soft)}
  .ev{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;background:var(--soft);color:var(--brand)}
  .sid{color:var(--sub);font-family:Consolas,monospace}
  footer{color:var(--sub);font-size:12px;margin-top:18px;line-height:1.7}
  .empty{color:var(--sub);text-align:center;padding:60px 0;font-size:14px}
</style>
</head>
<body>
<header>
  <h1> Wedding Invitation <span class="dot">·</span> 数据看板</h1>
  <div class="gen" id="gen"></div>
</header>
<div class="kpis" id="kpis"></div>
<div class="grid">
  <div class="card"><h3>触达漏斗（各页到达 UV）</h3><div id="funnel" class="chart tall"></div></div>
  <div class="card"><h3>24 小时访问分布（PV）</h3><div id="hours" class="chart tall"></div></div>
  <div class="card"><h3>访客省份（UV）</h3><div id="prov" class="chart" style="height:340px"></div></div>
  <div class="card"><h3>设备分布（UV）</h3><div id="dev" class="chart"></div></div>
  <div class="card full"><h3>互动事件排行（触发次数）</h3><div id="evc" class="chart" style="height:220px"></div></div>
</div>
<div class="card full"><h3>最近事件流（最多 300 条）</h3><div id="logwrap"></div></div>
<footer id="foot"></footer>
<script>
window.onerror = function(msg, src, line){
  var d = document.createElement('div');
  d.className = 'errbar';
  d.textContent = '渲染出错: ' + msg + ' @line ' + line;
  document.body.appendChild(d);
};
const PROV_FIX = n => ({"0":"海外/未知","Netherlands":"荷兰 🇳🇱","Viet Nam":"越南"}[n]||n);
const DATA = __DATA__;

const PAGE_NAMES = {cover:"封面",info:"时间地点",story:"故事",gallery:"相册",memories:"拾光相册",danmaku:"弹幕",tree:"祝福树",ending:"结尾"};
const EV_NAMES = {page_view:"页面浏览",bell:"摇铃铛",seal_tap:"盖印章",nav_click:"一键导航",
  rsvp_open:"打开回执",rsvp_submit:"提交回执",candy_open:"接喜糖·打开",candy_start:"接喜糖·开始",candy_submit:"接喜糖·提交",
  puzzle_open:"拼图·打开",puzzle_start:"拼图·开始",puzzle_submit:"拼图·提交",lantern:"放天灯",
  bgm_toggle:"音乐开关",pile_expand:"照片堆展开",pile_photo_view:"照片堆点开",memory_photo_view:"拾光相册点开",wish_submit:"送祝福"};
const EV_COLORS = {page_view:"#c9b99a",nav_click:"#b4532a",bell:"#c9a227",seal_tap:"#a0522d",
  rsvp_open:"#d97742",rsvp_submit:"#b4532a",candy_open:"#e0a458",candy_start:"#c9a227",candy_submit:"#b4532a",
  puzzle_open:"#d97742",puzzle_start:"#c9a227",puzzle_submit:"#b4532a",lantern:"#c05a3e",
  bgm_toggle:"#a98467",pile_expand:"#d97742",pile_photo_view:"#c9a227",memory_photo_view:"#b4532a",wish_submit:"#b4532a"};

function fmtTs(ts){const d=new Date(ts*1000);const p=n=>String(n).padStart(2,"0");
  return `${d.getMonth()+1}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;}


// ---- KPI ----
const st = DATA.stats;
const uvTotal = st.uv, pvTotal = st.pv;
const rows = DATA.rows;
const interactUv = new Set(rows.filter(r=>r[2]!=="page_view").map(r=>r[1])).size;
const finishUv = new Set(rows.filter(r=>r[2]==="page_view"&&(JSON.parse(r[3]||"{}").page)==="ending").map(r=>r[1])).size;
const evNoPv = Object.fromEntries(Object.entries(st.events).filter(([k])=>k!=="page_view"));
const interactCount = Object.values(evNoPv).reduce((a,b)=>a+b,0);
const kpis = [
  {v:uvTotal, l:"访客 UV", s:"独立会话"},
  {v:pvTotal, l:"页面浏览 PV", s:"人均 "+(uvTotal?(pvTotal/uvTotal).toFixed(1):0)+" 页"},
  {v:interactCount, l:"互动次数", s:interactCount?"":"暂无互动"},
  {v:interactUv, l:"互动 UV", s:"互动率 "+(uvTotal?Math.round(interactUv/uvTotal*100):0)+"%"},
  {v:finishUv, l:"走完全程 UV", s:"到达结尾页"},
];
document.getElementById("kpis").innerHTML = kpis.map(k=>
  `<div class="kpi"><div class="v">${k.v}</div><div class="l">${k.l}</div><div class="s">${k.s}</div></div>`).join("");
document.getElementById("gen").textContent = "生成时间 "+st.generated_at+" · 数据源自托管埋点服务";

const C = {brand:"#b4532a",gold:"#c9a227",ink:"#3d3229",sub:"#8a7a68",line:"#eadfcd",soft:"#f4ede1"};
const AXIS = {axisLine:{lineStyle:{color:C.line}},axisLabel:{color:C.sub},
  splitLine:{lineStyle:{color:"#f3ece0"}}};
function mk(id,opt){const c=echarts.init(document.getElementById(id));c.setOption(opt);
  window.addEventListener("resize",()=>c.resize());}

// ---- 漏斗 ----
mk("funnel",{tooltip:{trigger:"item",formatter:"{b}: {c} UV"},
  series:[{type:"funnel",left:"10%",right:"10%",top:10,bottom:10,minSize:"24%",
    sort:"none",gap:3,
    label:{position:"inside",color:"#fff",fontSize:12,fontWeight:600,
      textBorderColor:"rgba(61,50,41,0.55)",textBorderWidth:2,
      formatter:p=>`${PAGE_NAMES[p.name]||p.name} ${p.value}`},
    itemStyle:{borderRadius:4},
    color:["#b4532a","#c05a3e","#cb6a4a","#d97742","#e08a55","#e79c68","#eeb07e","#c9a227"],
    data:st.funnel_uv.map(f=>({name:f.page,value:f.uv}))}]});

// ---- 24h ----
mk("hours",{grid:{left:40,right:16,top:24,bottom:28},
  tooltip:{trigger:"axis"},
  xAxis:{type:"category",data:st.hours.map((_,i)=>i+"时"),...AXIS},
  yAxis:{type:"value",minInterval:1,...AXIS},
  series:[{type:"bar",data:st.hours,barCategoryGap:"35%",
    itemStyle:{color:new echarts.graphic.LinearGradient(0,0,0,1,[{offset:0,color:"#d97742"},{offset:1,color:"#f0c9a0"}]),borderRadius:[4,4,0,0]},
    label:{show:true,position:"top",color:C.sub,fontSize:10,formatter:p=>p.value||""}}]});

// ---- 省份（横向条形，避免多分类标签遮挡）----
const provSorted = st.provinces.map(p=>({name:PROV_FIX(p.name),value:p.uv}))
  .sort((a,b)=>b.value-a.value);
mk("prov",{grid:{left:86,right:40,top:10,bottom:10},
  tooltip:{trigger:"axis"},
  xAxis:{type:"value",minInterval:1,...AXIS},
  yAxis:{type:"category",data:provSorted.map(p=>p.name).slice().reverse(),
    ...AXIS,axisLabel:{color:C.ink,fontSize:11}},
  series:[{type:"bar",data:provSorted.map(p=>p.value).slice().reverse(),
    barCategoryGap:"30%",
    itemStyle:{color:C.brand,borderRadius:[0,4,4,0]},
    label:{show:true,position:"right",color:C.sub,fontSize:11}}]});

// ---- 设备 ----
mk("dev",{tooltip:{trigger:"item",formatter:"{b}: {c} UV ({d}%)"},
  legend:{bottom:0,textStyle:{color:C.sub,fontSize:11}},
  series:[{type:"pie",radius:["38%","62%"],center:["50%","45%"],
    label:{color:C.ink,fontSize:11,formatter:"{b} {c}"},
    color:["#b4532a","#c9a227","#a98467","#d97742"],
    data:st.devices.map(d=>({name:d.name,value:d.uv}))}]});

// ---- 互动事件 ----
const evNames = Object.keys(evNoPv).map(k=>EV_NAMES[k]||k);
mk("evc",{grid:{left:100,right:40,top:10,bottom:20},
  tooltip:{trigger:"axis"},
  xAxis:{type:"value",minInterval:1,...AXIS},
  yAxis:{type:"category",data:evNames.slice().reverse(),...AXIS,axisLabel:{color:C.ink,fontSize:12}},
  series:[{type:"bar",data:Object.values(evNoPv).slice().reverse(),barCategoryGap:"45%",
    itemStyle:{color:C.brand,borderRadius:[0,4,4,0]},
    label:{show:true,position:"right",color:C.sub}}]});
if(!evNames.length){
  document.getElementById("evc").parentNode.innerHTML =
    '<h3>互动事件排行（触发次数）</h3><div class="empty">暂无互动事件 —— 等待第一批玩起来的访客 ✨</div>';
}

// ---- 明细 ----
const wrap = document.getElementById("logwrap");
if(!rows.length){wrap.innerHTML = '<div class="empty">还没有任何访客数据</div>';}
else{
  wrap.innerHTML = `<table><thead><tr>
    <th>时间</th><th>会话</th><th>事件</th><th>内容</th><th>省份</th><th>设备</th>
  </tr></thead><tbody>` + rows.map(r=>{
    const [ts,sid,ev,payload,prov,dev] = r;
    let pl=""; try{const o=JSON.parse(payload||"{}");pl=o.page?(PAGE_NAMES[o.page]||o.page):Object.values(o).join(" ");}catch(e){}
    const evHtml = `<span class="ev" style="background:${(EV_COLORS[ev]||C.gold)}22;color:${EV_COLORS[ev]||C.brand}">${EV_NAMES[ev]||ev}</span>`;
    return `<tr><td>${fmtTs(ts)}</td><td class="sid">${String(sid).slice(0,10)}</td>
      <td>${evHtml}</td><td>${pl||"—"}</td><td>${PROV_FIX(prov)||"—"}</td><td>${dev||"—"}</td></tr>`;
  }).join("") + "</tbody></table>";
}
document.getElementById("foot").innerHTML =
  "库总量 "+DATA.total+" 条事件 · 会话 UV 以 sessionStorage 会话 ID 计（同一访客新开页面会算新会话，UV 略偏高）· "+
  "刷新方式：在 WorkBuddy 说「看看邀请函数据」即可重新生成本页";
</script>
</body>
</html>
"""


def main():
    echarts_path = Path(__file__).resolve().parent / "echarts.min.js"
    if not echarts_path.exists():
        print("缺少 echarts.min.js，正在下载 ...")
        import urllib.request
        urllib.request.urlretrieve(
            "https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js",
            str(echarts_path))
    echarts_js = echarts_path.read_text(encoding="utf-8")
    # 防御：内联时避免提前终结 <script> 标签
    echarts_js = echarts_js.replace("</script", "<\\/script")

    print("[1/4] 通过 SSH 拉取服务器数据 ...")
    r = subprocess.run(["ssh", SSH_HOST, "python3 -"], input=REMOTE_CODE.encode(),
                       capture_output=True, timeout=60)
    if r.returncode != 0:
        print("SSH/远端失败:", r.stderr.decode(errors="replace"), file=sys.stderr)
        sys.exit(1)
    data = json.loads(r.stdout.decode())
    print(f"      stats OK (pv={data['stats']['pv']}, uv={data['stats']['uv']}), "
          f"明细 {len(data['rows'])} 条, 库总量 {data['total']}")

    print("[2/4] 注入数据生成 HTML ...")
    js = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.replace("__ECHARTS_JS__", echarts_js).replace("__DATA__", js)

    # 渲染 JS 语法自检（node --check）
    print("[3/4] JS 语法自检 ...")
    last_script = html.rsplit("<script>", 1)[1].split("</script>")[0]
    tmp = Path(__file__).resolve().parent / "_render_check.js"
    tmp.write_text(last_script, encoding="utf-8")
    node = None
    import glob as _glob, shutil as _shutil
    if _shutil.which("node"):
        node = "node"
    else:
        cands = sorted(_glob.glob(
            r"C:\Users\tiand.STOHOX\.workbuddy\binaries\node\versions\*\node.exe"))
        if cands:
            node = cands[-1]
    if node:
        chk = subprocess.run([node, "--check", str(tmp)], capture_output=True, timeout=30)
    else:
        chk = None  # 无 node 时跳过语法自检
    tmp.unlink()
    if chk.returncode != 0:
        print("渲染 JS 语法错误:\n", chk.stderr.decode(errors="replace"), file=sys.stderr)
        sys.exit(1)
    print("      语法 OK")

    print("[4/4] 写出", OUT_HTML)
    OUT_HTML.write_text(html, encoding="utf-8")
    print("完成:", OUT_HTML, f"({OUT_HTML.stat().st_size/1024:.0f} KB, echarts 已内联)")


if __name__ == "__main__":
    main()
