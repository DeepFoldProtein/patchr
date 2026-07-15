"""Daily-activity dashboard: the self-contained HTML page plus the pure
aggregation helpers it is backed by.

``build_daily_stats`` takes already-loaded job and request records (so it stays
free of any server global) and returns the JSON the ``/api/v1/stats/daily``
endpoint serves; ``categorize_job`` classifies a single job record.
"""

from typing import Dict, List

from .models import JobStatus


def categorize_job(rec: dict) -> str:
    """Classify a job record into 'inference' (structure prediction), 'simulation'
    (sim-ready / membrane prep), 'template' (template generation only), or 'other'.
    Sim jobs carry a source_cif/sim_ready_result; prediction jobs have a
    prediction_dir (or a "Prediction error"); the rest are template-gen jobs."""
    if rec.get("source_cif") or rec.get("sim_ready_result") or rec.get("membrane_result"):
        return "simulation"
    if rec.get("prediction_dir"):
        return "inference"
    err = str(rec.get("error") or "")
    prog = str(rec.get("progress") or "")
    if err.startswith("Prediction error") or "prediction" in prog.lower():
        return "inference"
    if rec.get("template_files") or "Template generation" in err or "template" in prog.lower():
        return "template"
    return "other"


def build_daily_stats(jobs: List[dict], requests: List[dict], days: int = 30) -> dict:
    """Aggregate job records (by category + outcome) and HTTP request records into
    per-day buckets plus grand totals. ``days`` keeps the most recent N calendar
    days (0 = all)."""
    def _blank():
        return {"completed": 0, "failed": 0, "running": 0}

    buckets: Dict[str, dict] = {}

    def _day(d: str) -> dict:
        if d not in buckets:
            buckets[d] = {
                "date": d,
                "inference": _blank(), "simulation": _blank(), "template": _blank(),
                "requests": {"total": 0, "failed": 0},
            }
        return buckets[d]

    for rec in jobs:
        d = str(rec.get("created_at", ""))[:10]
        if not d:
            continue
        cat = categorize_job(rec)
        if cat == "other":
            continue
        st = rec.get("status")
        outcome = ("completed" if st == JobStatus.COMPLETED
                   else "failed" if st == JobStatus.FAILED else "running")
        _day(d)[cat][outcome] += 1

    for r in requests:
        d = str(r.get("ts", ""))[:10]
        if not d:
            continue
        b = _day(d)["requests"]
        b["total"] += 1
        if int(r.get("status", 0) or 0) >= 400:
            b["failed"] += 1

    ordered = [buckets[d] for d in sorted(buckets)]
    if days and days > 0:
        ordered = ordered[-days:]

    totals = {"inference": _blank(), "simulation": _blank(), "template": _blank(),
              "requests": {"total": 0, "failed": 0}}
    for b in ordered:
        for k in ("inference", "simulation", "template"):
            for o in ("completed", "failed", "running"):
                totals[k][o] += b[k][o]
        totals["requests"]["total"] += b["requests"]["total"]
        totals["requests"]["failed"] += b["requests"]["failed"]

    return {"days": ordered, "totals": totals}


DASHBOARD_HTML = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>patchr · daily activity</title>
<style>
  :root{ --bg:#0d1117; --panel:#161b22; --border:#30363d; --fg:#e6edf3;
    --muted:#8b949e; --ok:#3fb950; --fail:#f85149; --inf:#58a6ff; --sim:#bc8cff; }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
    font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
  .wrap{max-width:1100px;margin:0 auto;padding:28px 20px 60px}
  h1{font-size:20px;margin:0 0 2px} .sub{color:var(--muted);font-size:13px;margin-bottom:22px}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin-bottom:26px}
  .card{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:16px}
  .card h3{margin:0 0 8px;font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
  .big{font-size:28px;font-weight:700} .card .row{display:flex;gap:14px;align-items:baseline;margin-top:6px;font-size:13px}
  .ok{color:var(--ok)} .fail{color:var(--fail)} .muted{color:var(--muted)}
  .panel{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:18px 18px 10px;margin-bottom:22px}
  .panel-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;flex-wrap:wrap;gap:10px}
  .panel-head h2{font-size:15px;margin:0}
  .legend{display:flex;gap:16px;font-size:12px;color:var(--muted);align-items:center;flex-wrap:wrap}
  .legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
  .btns{display:flex;gap:6px}
  .btns button{background:#21262d;color:var(--fg);border:1px solid var(--border);border-radius:6px;padding:4px 10px;cursor:pointer;font-size:12px}
  .btns button.on{background:var(--inf);border-color:var(--inf);color:#04101f}
  .chart{display:flex;align-items:flex-end;gap:10px;height:250px;overflow-x:auto;padding-top:8px}
  .day{display:flex;flex-direction:column;align-items:center;gap:6px;min-width:38px;flex:1}
  .bars{display:flex;gap:3px;align-items:flex-end;height:220px}
  .bar{width:13px;display:flex;flex-direction:column;justify-content:flex-end;border-radius:3px 3px 0 0;overflow:hidden;background:#21262d}
  .seg{width:100%} .seg.okc{background:var(--ok)} .seg.failc{background:var(--fail)}
  .lbl{font-size:10px;color:var(--muted);white-space:nowrap;transform:rotate(-35deg);transform-origin:top left;height:22px}
  table{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}
  th,td{padding:7px 10px;text-align:right;border-bottom:1px solid var(--border)}
  th:first-child,td:first-child{text-align:left}
  th{color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.03em}
  tbody tr:hover{background:#1c2230}
  .err{color:var(--fail);padding:20px}
</style></head>
<body><div class="wrap">
  <h1>patchr · daily activity</h1>
  <div class="sub" id="sub">loading…</div>
  <div class="cards" id="cards"></div>
  <div class="panel">
    <div class="panel-head">
      <h2>Jobs per day</h2>
      <div class="legend">
        <span><i style="background:var(--inf)"></i>inference</span>
        <span><i style="background:var(--sim)"></i>simulation</span>
        <span><i style="background:var(--ok)"></i>completed</span>
        <span><i style="background:var(--fail)"></i>failed</span>
        <span class="btns" id="range">
          <button data-d="14">14d</button><button data-d="30" class="on">30d</button><button data-d="0">all</button>
        </span>
      </div>
    </div>
    <div class="chart" id="chart"></div>
  </div>
  <div class="panel">
    <div class="panel-head"><h2>Detail</h2></div>
    <div style="overflow-x:auto"><table id="tbl"></table></div>
  </div>
</div>
<script>
let DAYS = 30;
function seg(v,cls){ return v>0 ? '<div class="seg '+cls+'" style="height:'+v+'px" title="'+v+'"></div>' : ''; }
async function load(){
  const chart=document.getElementById('chart'), tbl=document.getElementById('tbl'),
        cards=document.getElementById('cards'), sub=document.getElementById('sub');
  try{
    const r=await fetch('/api/v1/stats/daily?days='+DAYS);
    if(!r.ok) throw new Error('HTTP '+r.status);
    const d=await r.json();
    const days=d.days, t=d.totals;
    sub.textContent='Updated '+new Date().toLocaleString()+' · '+days.length+' day(s)';
    // cards
    const irate=t.inference.completed+t.inference.failed, srate=t.simulation.completed+t.simulation.failed;
    cards.innerHTML=[
      card('Inference jobs', t.inference, irate),
      card('Simulation jobs', t.simulation, srate),
      cardReq('HTTP requests', t.requests),
    ].join('');
    // chart scaling
    let mx=1;
    days.forEach(x=>{ ['inference','simulation'].forEach(k=>{ mx=Math.max(mx, x[k].completed+x[k].failed+x[k].running); }); });
    const H=200;
    chart.innerHTML = days.length? days.map(x=>{
      const bar=(k,col)=>{
        const o=x[k], sc=v=>Math.round(v/mx*H);
        const tip=k+' '+x.date+' — ok:'+o.completed+' fail:'+o.failed+(o.running?' run:'+o.running:'');
        return '<div class="bar" style="outline:2px solid '+col+';outline-offset:-1px" title="'+tip+'">'
          + seg(sc(o.failed),'failc') + seg(sc(o.running),'okc') + seg(sc(o.completed),'okc') + '</div>';
      };
      return '<div class="day"><div class="bars">'+bar('inference','var(--inf)')+bar('simulation','var(--sim)')
        + '</div><div class="lbl">'+x.date.slice(5)+'</div></div>';
    }).join('') : '<div class="muted" style="padding:30px">No activity in range.</div>';
    // table
    tbl.innerHTML='<thead><tr><th>Date</th><th>Inf ✓</th><th>Inf ✗</th><th>Sim ✓</th><th>Sim ✗</th>'
      +'<th>Tmpl ✓</th><th>Tmpl ✗</th><th>Requests</th><th>Req fail</th></tr></thead><tbody>'
      + days.slice().reverse().map(x=>'<tr><td>'+x.date+'</td>'
        +'<td class="ok">'+x.inference.completed+'</td><td class="'+(x.inference.failed?'fail':'muted')+'">'+x.inference.failed+'</td>'
        +'<td class="ok">'+x.simulation.completed+'</td><td class="'+(x.simulation.failed?'fail':'muted')+'">'+x.simulation.failed+'</td>'
        +'<td class="ok">'+x.template.completed+'</td><td class="'+(x.template.failed?'fail':'muted')+'">'+x.template.failed+'</td>'
        +'<td>'+x.requests.total+'</td><td class="'+(x.requests.failed?'fail':'muted')+'">'+x.requests.failed+'</td></tr>').join('')
      +'</tbody>';
  }catch(e){ chart.innerHTML='<div class="err">Failed to load stats: '+e.message+'</div>'; }
}
function card(title,o,tot){
  return '<div class="card"><h3>'+title+'</h3><div class="big">'+tot+'</div>'
    +'<div class="row"><span class="ok">'+o.completed+' completed</span>'
    +'<span class="'+(o.failed?'fail':'muted')+'">'+o.failed+' failed</span>'
    +(o.running?'<span class="muted">'+o.running+' running</span>':'')+'</div></div>';
}
function cardReq(title,o){
  const okp = o.total? Math.round((o.total-o.failed)/o.total*1000)/10 : 100;
  return '<div class="card"><h3>'+title+'</h3><div class="big">'+o.total+'</div>'
    +'<div class="row"><span class="ok">'+okp+'% ok</span>'
    +'<span class="'+(o.failed?'fail':'muted')+'">'+o.failed+' errors</span></div></div>';
}
document.getElementById('range').addEventListener('click',e=>{
  const b=e.target.closest('button'); if(!b) return;
  DAYS=+b.dataset.d; document.querySelectorAll('#range button').forEach(x=>x.classList.remove('on'));
  b.classList.add('on'); load();
});
load(); setInterval(load, 30000);
</script>
</body></html>"""
