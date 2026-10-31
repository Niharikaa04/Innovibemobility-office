import {useEffect,useState,FormEvent,ReactNode} from 'react'; import {api} from './api'
import './Attendance.css'
// Attendance dashboard. Times come from the SERVER clock; the server decides what each user may do (can_write / can_approve / can_configure / own_only).
// Every number shown here comes from the existing /attendance/* endpoints. Nothing is estimated: where an endpoint cannot supply a value, the UI says so.
type Rec={id:string;work_date:string;check_in:string;check_out:string|null;late_minutes:number|null;early_minutes:number|null;worked_minutes:number|null;source?:string}
const DAYS=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'],SUN_FIRST=['Sun','Mon','Tue','Wed','Thu','Fri','Sat']
const fmt=(t?:string|null,tz?:string)=>t?new Date(t).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',timeZone:tz}):'—',mins=(m?:number|null)=>m==null?'—':`${Math.floor(m/60)}h ${m%60}m`
const pad=(n:number)=>String(n).padStart(2,'0'),num=(n:number)=>String(Math.round(n*10)/10)
const thisMonth=()=>{const d=new Date();return `${d.getFullYear()}-${pad(d.getMonth()+1)}`}
const shiftMonth=(m:string,by:number)=>{const [y,mo]=m.split('-').map(Number),d=new Date(Date.UTC(y,mo-1+by,1));return `${d.getUTCFullYear()}-${pad(d.getUTCMonth()+1)}`}
const monthLabel=(m:string)=>{const [y,mo]=m.split('-').map(Number);return new Date(Date.UTC(y,mo-1,1)).toLocaleDateString([],{month:'long',year:'numeric',timeZone:'UTC'})}
const dayLabel=(iso:string)=>new Date(iso+'T00:00:00Z').toLocaleDateString([],{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'})
const lateAfter=(start:string,grace:number)=>{const [h,m]=start.split(':').map(Number),t=h*60+m+grace;return `${pad(Math.floor(t/60)%24)}:${pad(t%60)}`}
const csvCell=(v:any)=>{let s=String(v??'');if(/^[=+\-@\t\r]/.test(s))s="'"+s;return `"${s.replace(/"/g,'""')}"`}

const ICONS:Record<string,ReactNode>={
 check:<><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></>,clock:<><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
 cal:<><rect x="4" y="5" width="16" height="15" rx="2"/><path d="M8 3v4M16 3v4M4 10h16"/></>,out:<><path d="M10 5H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h4"/><path d="m15 8 4 4-4 4M19 12H9"/></>,
 timer:<><circle cx="12" cy="13" r="8"/><path d="M12 9v4l2 2M9 3h6"/></>,miss:<><circle cx="12" cy="12" r="9"/><path d="m9 9 6 6M15 9l-6 6"/></>,user:<><circle cx="12" cy="8" r="3.5"/><path d="M5 20a7 7 0 0 1 14 0"/></>}
const Icon=({n}:{n:string})=><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{ICONS[n]}</svg>
const Card=({title,aside,className='',children}:{title:string;aside?:ReactNode;className?:string;children:ReactNode})=><section className={`att-card ${className}`}><header className="att-card-h"><h3>{title}</h3>{aside}</header>{children}</section>
const Badge=({tone,children}:{tone:'ok'|'warn'|'bad'|'muted';children:ReactNode})=><span className={`att-badge att-badge--${tone}`}>{children}</span>
const Empty=({children}:{children:ReactNode})=><p className="att-empty">{children}</p>
const Kpi=({icon,tone,label,value,sub}:{icon:string;tone:string;label:string;value:ReactNode;sub:string})=><div className="att-kpi"><span className={`att-kpi-i att-tone--${tone}`}><Icon n={icon}/></span><div><div className="att-kpi-l">{label}</div><div className="att-kpi-v">{value}</div><div className="att-kpi-s">{sub}</div></div></div>

// Live clock driven by the SERVER time (offset captured when /attendance/today was fetched), shown in the office timezone.
function Clock({serverTime,tz}:{serverTime?:string;tz?:string}){
 const [now,setNow]=useState<number|null>(null)
 useEffect(()=>{if(!serverTime){setNow(null);return};const off=new Date(serverTime).getTime()-Date.now(),t=()=>setNow(Date.now()+off);t();const id=setInterval(t,1000);return()=>clearInterval(id)},[serverTime])
 return <div className="att-clock" aria-label="Server time">{now==null?'—':new Date(now).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',timeZone:tz})}</div>}

function Donut({parts,center,label}:{parts:{label:string;value:number;color:string}[];center:string;label:string}){
 const R=52,C=2*Math.PI*R,total=parts.reduce((a,p)=>a+p.value,0);let off=0
 return <svg className="att-donut" viewBox="0 0 140 140" role="img" aria-label={parts.map(p=>`${p.label} ${num(p.value)}`).join(', ')}>
  <g transform="rotate(-90 70 70)"><circle cx="70" cy="70" r={R} fill="none" stroke="var(--att-track)" strokeWidth="18"/>
   {parts.filter(p=>p.value>0).map(p=>{const len=p.value/total*C,el=<circle key={p.label} cx="70" cy="70" r={R} fill="none" stroke={p.color} strokeWidth="18" strokeDasharray={`${len} ${C-len}`} strokeDashoffset={-off}/>;off+=len;return el})}</g>
  <text x="70" y="68" textAnchor="middle" className="att-donut-n">{center}</text><text x="70" y="86" textAnchor="middle" className="att-donut-l">{label}</text></svg>}

function Hours({items}:{items:Rec[]}){
 const data=items.filter(r=>r.worked_minutes!=null).sort((a,b)=>a.work_date.localeCompare(b.work_date))
 if(!data.length)return <Empty>No completed shifts this month yet. Hours appear after check-out.</Empty>
 const maxH=Math.max(2,Math.ceil(Math.max(...data.map(d=>d.worked_minutes as number))/60/2)*2),ticks=[maxH,maxH/2,0],labelled=data.length<=8
 return <div className="att-hours" role="img" aria-label={`Hours worked on ${data.length} days: ${data.map(d=>`${dayLabel(d.work_date)} ${mins(d.worked_minutes)}`).join(', ')}`}>
  <div className="att-hours-y" aria-hidden="true">{ticks.map(t=><span key={t}>{t}h</span>)}</div>
  <div className="att-hours-plot"><div className="att-hours-bars">{data.map(d=><div key={d.id} className="att-bar" title={`${dayLabel(d.work_date)}: ${mins(d.worked_minutes)}`}>
   {labelled&&<span className="att-bar-v">{mins(d.worked_minutes)}</span>}<span className="att-bar-fill" style={{height:`${(d.worked_minutes as number)/60/maxH*100}%`}}/><span className="att-bar-x">{d.work_date.slice(8)}</span></div>)}</div></div></div>}

const CAL_TEXT:Record<string,string>={ok:'On time',late:'Late',none:'No record',off:'Day off'}
function Calendar({month,recs,todayStr,wd}:{month:string;recs:Rec[];todayStr?:string;wd:number[]}){
 const [y,m]=month.split('-').map(Number),first=new Date(Date.UTC(y,m-1,1)).getUTCDay(),n=new Date(Date.UTC(y,m,0)).getUTCDate(),by=new Map(recs.map(r=>[r.work_date,r]))
 return <><div className="att-cal" role="list" aria-label={`Attendance calendar, ${monthLabel(month)}`}>
  {SUN_FIRST.map(d=><span key={d} className="att-cal-h" aria-hidden="true">{d}</span>)}
  {Array.from({length:first},(_,i)=><span key={'b'+i} aria-hidden="true"/>)}
  {Array.from({length:n},(_,i)=>{const d=i+1,iso=`${month}-${pad(d)}`,idx=(first+i)%7,r=by.get(iso)
   const st=r?(r.late_minutes?'late':'ok'):!wd.includes(idx===0?7:idx)?'off':todayStr&&iso<todayStr?'none':''
   return <span key={iso} role="listitem" className={`att-cal-d${iso===todayStr?' is-today':''}`} aria-label={`${dayLabel(iso)}${st?`: ${CAL_TEXT[st]}`:''}${iso===todayStr?' (today)':''}`} title={r?`In ${fmt(r.check_in)}${r.check_out?`, out ${fmt(r.check_out)}`:''}`:CAL_TEXT[st]||''}>{d}{st&&<i className={`att-dot att-dot--${st}`}/>}</span>})}</div>
  <ul className="att-legend att-legend--row">{(['ok','late','none','off'] as const).map(k=><li key={k}><i className={`att-dot att-dot--${k}`}/>{CAL_TEXT[k]}</li>)}</ul>
  <p className="att-fine">“No record” can also be approved leave or a holiday. The leave and holiday counts for the month are in the overview.</p></>}

export default function Attendance(){
 const [cfg,setCfg]=useState<any>(null),[today,setToday]=useState<any>(null),[month,setMonth]=useState(thisMonth()),[recs,setRecs]=useState<{month:string;items:Rec[]}|null>(null),[sumRaw,setSum]=useState<any>(null),
  [team,setTeam]=useState<any>(null),[corr,setCorr]=useState<any[]|null>(null),[err,setErr]=useState(''),[ok,setOk]=useState(''),[tick,setTick]=useState(0),[form,setForm]=useState<any|null>(null),[cform,setCform]=useState<any|null>(null),[busy,setBusy]=useState(false)
 const tz=cfg?.config?.timezone,ready=!!cfg,configured=!!cfg?.configured
 // Config, today, corrections and team: reloaded after every action (tick). Cancelled on unmount so late replies are ignored.
 useEffect(()=>{let live=true;const fail=(e:any)=>{if(live)setErr(e.message)}
  api.call('/attendance/config','GET').then(c=>{if(!live)return;setCfg(c)
   api.call('/attendance/today','GET').then(t=>live&&setToday(t)).catch(fail)
   api.call('/attendance/corrections','GET').then(r=>live&&setCorr(r.items)).catch(fail)
   if(c.configured&&!c.own_only)api.call('/attendance/team','GET').then(t=>live&&setTeam(t)).catch(()=>live&&setTeam(null))}).catch(fail)
  return()=>{live=false}},[tick])
 // Month-scoped data. Results are tagged with their month so a slow reply for another month is never shown.
 useEffect(()=>{if(!ready)return;let live=true
  api.call(`/attendance/records?month=${month}`,'GET').then(r=>live&&setRecs({month,items:r.items})).catch(e=>live&&setErr(e.message))
  if(configured)api.call(`/attendance/summary?month=${month}`,'GET').then(s=>live&&setSum(s)).catch(()=>live&&setSum(null))
  return()=>{live=false}},[ready,configured,month,tick])
 async function act(path:string,msg:string){setErr('');setOk('');setBusy(true);try{await api.call(path,'POST');setOk(msg);setTick(t=>t+1)}catch(x:any){setErr(x.message)}finally{setBusy(false)}}
 async function saveCfg(e:FormEvent){e.preventDefault();setErr('');setOk('');try{await api.call('/attendance/config','PUT',{start_time:form.start_time,end_time:form.end_time,grace_minutes:Number(form.grace_minutes),timezone:form.timezone,working_days:form.working_days});setOk('Attendance settings saved.');setForm(null);setTick(t=>t+1)}catch(x:any){setErr(x.message)}}
 async function sendCorr(e:FormEvent){e.preventDefault();setErr('');setOk('');const b:any={work_date:cform.work_date,reason:cform.reason||''};if(cform.ci)b.check_in_time=cform.ci;if(cform.co)b.check_out_time=cform.co
  try{await api.call('/attendance/corrections','POST',b);setOk('Correction request sent for approval.');setCform(null);setTick(t=>t+1)}catch(x:any){setErr(x.message)}}
 async function decide(q:any,decision:'approve'|'reject'){setErr('');setOk('');let note:string|null='';if(decision==='reject'){note=window.prompt('Reason for rejecting this request');if(!note)return}
  try{await api.call(`/attendance/corrections/${q.id}/decision`,'POST',{decision,note});setOk(decision==='approve'?'Correction approved.':'Correction rejected.');setTick(t=>t+1)}catch(x:any){setErr(x.message)}}
 function exportTeam(){if(!team)return
  const lines=[['Name','Check in','Check out','Worked','Status'],...team.items.map((r:any)=>[r.name??r.user_id,fmt(r.check_in,tz),fmt(r.check_out,tz),mins(r.worked_minutes),r.late_minutes?`Late ${r.late_minutes} min`:'Present']),...team.on_leave.map((x:any)=>[x.name??'—','—','—','—',x.half_day?'Half-day leave':'On leave'])]
  const a=document.createElement('a');a.href=URL.createObjectURL(new Blob(['\ufeff'+lines.map(l=>l.map(csvCell).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'}));a.download=`team-attendance-${team.date}.csv`;a.click();URL.revokeObjectURL(a.href)}

 const rec=today?.record,todayStr:string|undefined=today?.work_date,mine=recs?.month===month?recs.items:null,sum=sumRaw?.month===month?sumRaw:null,cfgc=cfg?.config
 const tItems:any[]|null=team?.items??null,onLeave:any[]=team?.on_leave??[]
 const done=tItems?tItems.filter(x=>x.worked_minutes!=null):[],avg=done.length?Math.round(done.reduce((a,x)=>a+x.worked_minutes,0)/done.length):null
 // KPI strip: team figures for people who can see the team, otherwise the signed-in user's own month. Headcount is not exposed by the API, so no "total" or "absent" figure is shown.
 const kpis=cfg?.own_only?[
  {icon:'check',tone:'green',label:'Days present',value:sum?.days_present,sub:monthLabel(month)},{icon:'clock',tone:'amber',label:'Late days',value:sum?.late_days,sub:'After shift start + grace'},
  {icon:'out',tone:'blue',label:'Early departures',value:sum?.early_departure_days,sub:'Left before shift end'},{icon:'miss',tone:'red',label:'No record',value:sum?.no_record_days,sub:'Working days without a record'},
  {icon:'timer',tone:'violet',label:'Hours worked',value:sum?mins(sum.worked_minutes):undefined,sub:monthLabel(month)}]:[
  {icon:'check',tone:'green',label:'Present today',value:tItems?.length,sub:'Checked in so far'},{icon:'clock',tone:'amber',label:'Late today',value:tItems?.filter(x=>x.late_minutes>0).length,sub:'After shift start + grace'},
  {icon:'cal',tone:'blue',label:'On leave today',value:tItems?onLeave.length:undefined,sub:'Approved leave'},{icon:'out',tone:'red',label:'Checked out',value:tItems?.filter(x=>x.check_out).length,sub:'Finished for the day'},
  {icon:'timer',tone:'violet',label:'Avg working hours',value:tItems?(avg==null?'—':mins(avg)):undefined,sub:avg==null&&tItems?'No completed shifts yet':'Completed shifts today'}]
 const sp=sum?[{label:'On time',value:Math.max(0,sum.days_present-sum.late_days),color:'var(--att-green)'},{label:'Late',value:sum.late_days,color:'var(--att-amber)'},{label:'No record',value:sum.no_record_days,color:'var(--att-red)'},{label:'Leave',value:sum.leave_days,color:'var(--att-blue)'}]:[]
 const spTotal=sp.reduce((a,p)=>a+p.value,0)

 return <div className="att">
  <header className="att-head"><div><h2>Attendance</h2><p>Check in, review your records and manage correction requests.</p></div>
   <div className="att-head-r">{cfg?.can_configure&&<button className="att-btn att-btn--line" onClick={()=>{setForm({...(cfgc||{start_time:'',end_time:'',grace_minutes:0,timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,working_days:[1,2,3,4,5]})});setErr('');setOk('')}}>{configured?'Edit settings':'Set up attendance'}</button>}
    <label className="att-month"><span className="att-sr">Month</span><input id="a_m" type="month" value={month} onChange={e=>e.target.value&&setMonth(e.target.value)}/></label></div></header>
  {err&&<div className="att-alert att-alert--err" role="alert">{err}</div>}{ok&&<div className="att-alert att-alert--ok" role="status">{ok}</div>}
  {cfg&&!configured&&<Empty>Attendance is not set up yet. {cfg.can_configure?'Use “Set up attendance” to enter the shift times, timezone and working days.':'An administrator (CEO) must set the shift, timezone and working days before check-in is possible.'}</Empty>}
  {form&&<form onSubmit={saveCfg} className="att-card att-form" aria-label="Attendance settings">
   <div><label htmlFor="a_s">Shift start *</label><input id="a_s" type="time" value={form.start_time} onChange={e=>setForm({...form,start_time:e.target.value})} required/></div>
   <div><label htmlFor="a_e">Shift end *</label><input id="a_e" type="time" value={form.end_time} onChange={e=>setForm({...form,end_time:e.target.value})} required/></div>
   <div><label htmlFor="a_g">Grace period (minutes)</label><input id="a_g" type="number" min={0} max={240} value={form.grace_minutes} onChange={e=>setForm({...form,grace_minutes:e.target.value})}/></div>
   <div><label htmlFor="a_t">Timezone (e.g. Asia/Kolkata) *</label><input id="a_t" type="text" value={form.timezone} onChange={e=>setForm({...form,timezone:e.target.value})} required/></div>
   <fieldset><legend>Working days</legend>{DAYS.map((d,i)=><label key={d} className="att-check"><input type="checkbox" checked={form.working_days.includes(i+1)} onChange={e=>setForm({...form,working_days:e.target.checked?[...form.working_days,i+1]:form.working_days.filter((x:number)=>x!==i+1)})}/> {d}</label>)}</fieldset>
   <div className="att-actions"><button className="att-btn att-btn--primary">Save settings</button><button type="button" className="att-btn att-btn--line" onClick={()=>setForm(null)}>Cancel</button></div></form>}

  {configured&&<>
   <div className="att-kpis">{kpis.map(k=><Kpi key={k.label} {...k} value={k.value==null?'—':k.value} sub={k.value==null?'Not available':k.sub}/>)}</div>
   <div className="att-grid">
    <Card title="Today’s attendance" aside={todayStr&&<span className="att-chip">Today · {dayLabel(todayStr)}</span>} className="att-today">
     <Clock serverTime={today?.server_time} tz={tz}/>
     <p className="att-fine" role="status">{!today?'Loading…':!rec?'Not checked in today':`Checked in ${fmt(rec.check_in,tz)}${rec.check_out?`, out ${fmt(rec.check_out,tz)}`:''}${rec.late_minutes?` · late ${rec.late_minutes} min`:''}`}</p>
     {cfg.can_write?<><div className="att-actions"><button className="att-btn att-btn--in" disabled={busy||!today||!!rec} onClick={()=>act('/attendance/check-in','Checked in.')}>Check in</button><button className="att-btn att-btn--out" disabled={busy||!rec||!!rec?.check_out} onClick={()=>act('/attendance/check-out','Checked out.')}>Check out</button></div>
      <button className="att-btn att-btn--line att-wide" onClick={()=>{setCform({work_date:'',ci:'',co:'',reason:''});setErr('');setOk('')}}>Request correction</button></>:<Empty>Your role can view attendance but not check in.</Empty>}
     {cform&&<form onSubmit={sendCorr} className="att-form att-form--inline" aria-label="Request attendance correction">
      <div><label htmlFor="c_d">Date *</label><input id="c_d" type="date" max={todayStr} value={cform.work_date} onChange={e=>setCform({...cform,work_date:e.target.value})} required/></div>
      <div><label htmlFor="c_i">Correct check-in time</label><input id="c_i" type="time" value={cform.ci} onChange={e=>setCform({...cform,ci:e.target.value})}/></div>
      <div><label htmlFor="c_o">Correct check-out time</label><input id="c_o" type="time" value={cform.co} onChange={e=>setCform({...cform,co:e.target.value})}/></div>
      <div><label htmlFor="c_r">Reason *</label><input id="c_r" type="text" maxLength={500} value={cform.reason} onChange={e=>setCform({...cform,reason:e.target.value})} required/></div>
      <div className="att-actions"><button className="att-btn att-btn--primary">Send for approval</button><button type="button" className="att-btn att-btn--line" onClick={()=>setCform(null)}>Cancel</button></div></form>}
     <dl className="att-info"><dt>Shift time</dt><dd>{cfgc.start_time} – {cfgc.end_time} ({cfgc.timezone})</dd><dt>Working days</dt><dd>{cfgc.working_days.map((d:number)=>DAYS[d-1]).join(', ')}</dd>
      <dt>Grace time</dt><dd>{cfgc.grace_minutes} minutes</dd><dt>Late after</dt><dd>{lateAfter(cfgc.start_time,cfgc.grace_minutes)} (shift start + grace)</dd><dt>Early departure</dt><dd>Checked out before {cfgc.end_time}</dd></dl>
     <details className="att-fine"><summary>How attendance is counted</summary>{cfg.definitions}</details></Card>

    <div className="att-mid">
     <Card title="Attendance overview" aside={<span className="att-chip att-chip--n">{monthLabel(month)}</span>}>
      {!sum?<Empty>Monthly summary is not available.</Empty>:!spTotal?<Empty>No attendance days have been counted for this month yet.</Empty>:<div className="att-ov"><Donut parts={sp} center={String(sum.days_present)} label="days present"/>
       <ul className="att-legend">{sp.map(p=><li key={p.label}><i className="att-dot" style={{background:p.color}}/>{p.label}<b>{num(p.value)}</b></li>)}</ul></div>}
      {sum&&<dl className="att-stats"><div><dt>Working days so far</dt><dd>{sum.working_days_elapsed}</dd></div><div><dt>Early departures</dt><dd>{sum.early_departure_days}</dd></div><div><dt>Missing check-out</dt><dd>{sum.missing_checkout_days}</dd></div><div><dt>Holidays</dt><dd>{sum.holiday_days}</dd></div><div><dt>Hours worked</dt><dd>{mins(sum.worked_minutes)}</dd></div></dl>}</Card>
     <Card title="Working hours" aside={<span className="att-chip att-chip--n">{monthLabel(month)}</span>}>{!mine?<Empty>Loading…</Empty>:<Hours items={mine}/>}</Card></div>

    <Card title="Monthly calendar" aside={<div className="att-nav"><button className="att-btn att-btn--icon" aria-label="Previous month" onClick={()=>setMonth(shiftMonth(month,-1))}>‹</button><span>{monthLabel(month)}</span><button className="att-btn att-btn--icon" aria-label="Next month" onClick={()=>setMonth(shiftMonth(month,1))}>›</button></div>}>
     {!mine?<Empty>Loading…</Empty>:<Calendar month={month} recs={mine} todayStr={todayStr} wd={cfgc.working_days}/>}</Card></div>

   <div className={`att-pair${cfg.own_only?' att-pair--one':''}`}>
    <Card title="My attendance records"><div className="att-scroll"><table aria-label="My attendance records"><thead><tr><th>Date</th><th>In</th><th>Out</th><th>Worked</th><th>Status</th><th>Late</th><th>Early out</th><th>Source</th></tr></thead>
     <tbody>{(mine||[]).map(r=><tr key={r.id}><td>{r.work_date}</td><td>{fmt(r.check_in,tz)}</td><td>{r.check_out?fmt(r.check_out,tz):todayStr&&r.work_date<todayStr?<span className="att-miss">Missing</span>:'—'}</td><td>{mins(r.worked_minutes)}</td>
      <td>{r.late_minutes?<Badge tone="warn">Late</Badge>:<Badge tone="ok">Present</Badge>}</td><td>{r.late_minutes?`${r.late_minutes} min`:'—'}</td><td>{r.early_minutes?`${r.early_minutes} min`:'—'}</td><td>{r.source==='correction'?'Corrected':'Self'}</td></tr>)}</tbody></table></div>
     {!mine?<Empty>Loading…</Empty>:!mine.length&&<Empty>No attendance records for this month.</Empty>}</Card>
    {!cfg.own_only&&<Card title="Team today" aside={<button className="att-btn att-btn--line att-btn--sm" disabled={!team||!(team.items.length||onLeave.length)} onClick={exportTeam}>Export CSV</button>}>
     {!team?<Empty>Team attendance could not be loaded.</Empty>:<><div className="att-scroll"><table aria-label="Team attendance today"><thead><tr><th>Name</th><th>Check in</th><th>Check out</th><th>Worked</th><th>Status</th></tr></thead>
      <tbody>{team.items.map((r:any)=><tr key={r.id}><td>{r.name??r.user_id}</td><td>{fmt(r.check_in,tz)}</td><td>{fmt(r.check_out,tz)}</td><td>{mins(r.worked_minutes)}</td><td>{r.late_minutes?<Badge tone="warn">Late · {r.late_minutes} min</Badge>:<Badge tone="ok">Present</Badge>}</td></tr>)}
       {onLeave.map((x,i)=><tr key={'l'+i}><td>{x.name??'—'}</td><td>—</td><td>—</td><td>—</td><td><Badge tone="muted">{x.half_day?'Half-day leave':'On leave'}</Badge></td></tr>)}</tbody></table></div>
      {!team.items.length&&!onLeave.length&&<Empty>Nobody has checked in yet today.</Empty>}</>}</Card>}</div>

   <Card title="Correction requests"><div className="att-scroll"><table aria-label="Correction requests"><thead><tr><th>Who</th><th>Date</th><th>Requested</th><th>Reason</th><th>Status</th><th>Actions</th></tr></thead>
    <tbody>{(corr||[]).map(q=><tr key={q.id}><td>{q.name??'—'}</td><td>{q.work_date}</td><td>{q.requested_check_in?`in ${fmt(q.requested_check_in,tz)} `:''}{q.requested_check_out?`out ${fmt(q.requested_check_out,tz)}`:''}</td><td>{q.reason}{q.decision_note&&<small> · {q.decision_note}</small>}</td>
     <td><Badge tone={q.status==='approved'?'ok':q.status==='rejected'?'bad':'warn'}>{q.status}</Badge>{q.decided_by_name&&<small> by {q.decided_by_name}</small>}</td>
     <td>{q.can_decide&&<div className="att-actions"><button className="att-btn att-btn--line att-btn--sm" onClick={()=>decide(q,'approve')}>Approve</button><button className="att-btn att-btn--line att-btn--sm" onClick={()=>decide(q,'reject')}>Reject</button></div>}</td></tr>)}</tbody></table></div>
    {!corr?<Empty>Loading…</Empty>:!corr.length&&<Empty>No correction requests.</Empty>}</Card></>}
 </div>}
