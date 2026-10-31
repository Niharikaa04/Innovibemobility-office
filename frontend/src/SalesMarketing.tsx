import {useCallback,useEffect,useMemo,useRef,useState} from 'react'; import type {FormEvent,ReactElement} from 'react'
import {Bar,BarChart,CartesianGrid,Legend,Line,LineChart,ResponsiveContainer,Tooltip,XAxis,YAxis} from 'recharts'
import {api} from './api'; import {Empty} from './Charts'; import {Badge,Pager,Stat,fmtDate,Loading,Notices,PageHead} from './opsui'
import './salesmarketing.css'
/* Sales & Marketing: executive overview of campaigns. Campaigns are the records of the existing 'sales-and-marketing' workspace
   (office_dashboard.module_records, /api/workspaces). Every number is calculated from what is stored on those records; nothing is invented.
   Core columns used: title, status, amount (= spend), due_date (= end date). Extra values live in the record's existing `fields` JSON:
   channel, owner, budget, leads_generated (existing) plus start_date, conversions, revenue (optional, entered by the user). */
const MODULE='sales-and-marketing',BASE=`/workspaces/${MODULE}`
type Rec={id:string;title:string;status:string;description:string;amount:number|string|null;due_date:string|null;fields:Record<string,unknown>|null;created_at:string;updated_at?:string}
type Camp={id:string;rec:Rec;name:string;status:string;channel:string;owner:string;budget:number|null;spend:number|null;leads:number|null;conv:number|null;revenue:number|null;start:string;end:string;period:string}
const CHANNELS=['Website','Email','WhatsApp','Referral','Event','Other'],STATUSES=['Open','Pending','Approved','In Progress','Completed','Blocked','Cancelled']
const ACTIVE='In Progress'
const num=(v:unknown):number|null=>{if(v==null||v==='')return null;const x=Number(v);return Number.isFinite(x)?x:null}
const str=(v:unknown)=>v==null?'':String(v)
const toCamp=(r:Rec):Camp=>{const f=r.fields||{},start=str(f.start_date);return {id:r.id,rec:r,name:r.title,status:r.status,channel:str(f.channel),owner:str(f.owner),budget:num(f.budget),spend:num(r.amount),leads:num(f.leads_generated),conv:num(f.conversions),revenue:num(f.revenue),start,end:r.due_date||'',period:start||str(r.created_at).slice(0,10)}}
const fmt=(v:number|null,d=0)=>v==null?'N/A':v.toLocaleString('en-IN',{maximumFractionDigits:d})
const pct=(c:number|null,l:number|null)=>c==null||!l?null:Math.round(c/l*1000)/10
const sum=(xs:(number|null)[])=>{const v=xs.filter((x):x is number=>x!=null);return v.length?v.reduce((a,b)=>a+b,0):null}
const month=(d:string)=>d.slice(0,7),monthLabel=(m:string)=>new Date(+m.slice(0,4),+m.slice(5,7)-1,1).toLocaleDateString(undefined,{month:'short',year:'2-digit'})
const statusKey=(s:string)=>s.toUpperCase().replace(/[^A-Z0-9]+/g,'_')
const norm=(s:string)=>s.trim().replace(/\s+/g,' ').toLowerCase()
const csvCell=(v:unknown)=>{let s=String(v??'');if(/^[=+\-@\t\r]/.test(s))s="'"+s;return `"${s.replace(/"/g,'""')}"`}
const EMPTY={title:'',status:'Open',channel:'',owner:'',budget:'',amount:'',start_date:'',due_date:'',leads_generated:'',conversions:'',revenue:'',description:''}
const PAGE=10
function Plot({data,empty,children}:{data:unknown[];empty:string;children:ReactElement}){return data.length?<div className="sm-plot"><ResponsiveContainer width="100%" height="100%">{children}</ResponsiveContainer></div>:<div className="sm-empty">{empty}</div>}
export default function SalesMarketing(){
 const [all,setAll]=useState<Rec[]|null>(null),[truncated,setTruncated]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false),[perms,setPerms]=useState<Set<string>|null>(null)
 const [q,setQ]=useState(''),[status,setStatus]=useState(''),[from,setFrom]=useState(''),[to,setTo]=useState(''),[page,setPage]=useState(1)
 const [open,setOpen]=useState(false),[form,setForm]=useState(EMPTY),[editing,setEditing]=useState<Rec|null>(null),[formError,setFormError]=useState('')
 const lock=useRef(false),formRef=useRef<HTMLDivElement>(null)
 const load=useCallback(async()=>{setError('');try{const items:Rec[]=[];let total=0;for(let p=1;p<=20;p++){const r=await api.call<{items:Rec[];total:number}>(`${BASE}?page=${p}&limit=100`,'GET');items.push(...r.items);total=r.total;if(items.length>=total||!r.items.length)break}setAll(items);setTruncated(items.length<total)}catch(e){setError((e as Error).message);setAll(a=>a||[])}},[])
 useEffect(()=>{void load()},[load])
 useEffect(()=>{api.call<{permissions:string[]}>('/auth/permissions','GET').then(r=>setPerms(new Set(r.permissions))).catch(()=>setPerms(null))},[])   // buttons only; the server enforces every action
 const can=(a:string)=>perms==null||perms.has(`sales.${a}`)
 const camps=useMemo(()=>(all||[]).map(toCamp),[all])
 const statuses=useMemo(()=>Array.from(new Set([...STATUSES,...camps.map(c=>c.status)])),[camps])
 const inRange=useCallback((c:Camp)=>(!from||c.period>=from)&&(!to||c.period<=to),[from,to])
 const matches=useCallback((c:Camp)=>!q.trim()||[c.name,c.channel,c.owner,c.status,c.rec.description].some(x=>x.toLowerCase().includes(q.trim().toLowerCase())),[q])
 const shown=useMemo(()=>camps.filter(c=>inRange(c)&&(!status||c.status===status)&&matches(c)),[camps,inRange,status,matches])
 const k=useMemo(()=>{const leads=sum(shown.map(c=>c.leads)),both=shown.filter(c=>c.leads&&c.conv!=null),rate=pct(sum(both.map(c=>c.conv)),sum(both.map(c=>c.leads)))
  return {total:shown.length,active:shown.filter(c=>c.status===ACTIVE).length,leads,rate,both:both.length,spend:sum(shown.map(c=>c.spend)),revenue:sum(shown.map(c=>c.revenue))}},[shown])
 const perf=useMemo(()=>shown.filter(c=>c.leads!=null).sort((a,b)=>(b.leads||0)-(a.leads||0)).slice(0,8).map(c=>({name:c.name.length>14?c.name.slice(0,13)+'…':c.name,Leads:c.leads,Conversions:c.conv})),[shown])
 const byChannel=useMemo(()=>{const m=new Map<string,number>();shown.forEach(c=>{if(c.leads!=null)m.set(c.channel||'Not set',(m.get(c.channel||'Not set')||0)+c.leads)});return Array.from(m,([name,Leads])=>({name,Leads})).sort((a,b)=>b.Leads-a.Leads)},[shown])
 const spendByMonth=useMemo(()=>{const m=new Map<string,number>();shown.forEach(c=>{if(c.spend!=null&&c.period)m.set(month(c.period),(m.get(month(c.period))||0)+c.spend)});return Array.from(m,([mo,Spend])=>({name:monthLabel(mo),mo,Spend})).sort((a,b)=>a.mo.localeCompare(b.mo))},[shown])
 const trend=useMemo(()=>{const m=new Map<string,[number,number]>();shown.forEach(c=>{if(c.leads&&c.conv!=null&&c.period){const t=m.get(month(c.period))||[0,0];m.set(month(c.period),[t[0]+c.conv,t[1]+c.leads])}});return Array.from(m,([mo,[cv,ld]])=>({name:monthLabel(mo),mo,'Conversion rate (%)':Math.round(cv/ld*1000)/10})).sort((a,b)=>a.mo.localeCompare(b.mo))},[shown])
 const pages=Math.max(1,Math.ceil(shown.length/PAGE)),cur=Math.min(page,pages),rows=shown.slice((cur-1)*PAGE,cur*PAGE)
 const hasFilter=!!(q||status||from||to)
 const reset=()=>{setForm(EMPTY);setEditing(null);setFormError('')}
 const startEdit=(c:Camp)=>{const f=c.rec.fields||{};setEditing(c.rec);setFormError('');setForm({title:c.rec.title,status:c.rec.status,channel:str(f.channel),owner:str(f.owner),budget:str(f.budget),amount:c.rec.amount==null?'':String(c.rec.amount),start_date:str(f.start_date),due_date:c.rec.due_date||'',leads_generated:str(f.leads_generated),conversions:str(f.conversions),revenue:str(f.revenue),description:c.rec.description||''});setOpen(true);setTimeout(()=>formRef.current?.scrollIntoView?.({behavior:'smooth',block:'start'}),50)}
 const validate=():string=>{const t=form.title.trim();if(!t)return 'Enter the campaign title.'
  if(camps.some(c=>c.id!==editing?.id&&norm(c.name)===norm(t)))return 'A campaign with this title already exists. Use a different title or edit the existing one.'
  if(form.start_date&&form.due_date&&form.due_date<form.start_date)return 'End date cannot be before the start date.'
  for(const [l,v] of [['Budget',form.budget],['Amount spent',form.amount],['Leads generated',form.leads_generated],['Conversions',form.conversions],['Revenue',form.revenue]] as [string,string][])if(v!==''&&!(Number(v)>=0))return `${l} must be zero or more.`
  if(form.leads_generated!==''&&form.conversions!==''&&Number(form.conversions)>Number(form.leads_generated))return 'Conversions cannot be more than leads generated.'
  return ''}
 const save=async(e:FormEvent)=>{e.preventDefault();if(lock.current)return;const bad=validate();if(bad){setFormError(bad);return}
  lock.current=true;setBusy(true);setFormError('');setError('');setNotice('')
  try{const fields:Record<string,unknown>={...(editing?.fields||{})};const put=(key:string,v:string,numeric:boolean)=>{if(v.trim()==='')delete fields[key];else fields[key]=numeric?Number(v):v.trim()}
   put('channel',form.channel,false);put('owner',form.owner,false);put('budget',form.budget,true);put('start_date',form.start_date,false);put('leads_generated',form.leads_generated,true);put('conversions',form.conversions,true);put('revenue',form.revenue,true)
   const body={title:form.title.trim(),status:form.status,description:form.description.trim(),amount:form.amount===''?null:Number(form.amount),due_date:form.due_date||null,fields}
   if(editing)await api.call(`${BASE}/records/${editing.id}`,'PATCH',body);else await api.call(`${BASE}/records`,'POST',body)
   setNotice(editing?'Campaign updated.':'Campaign created.');reset();setOpen(false);await load()}
  catch(er){setFormError((er as Error).message)}finally{lock.current=false;setBusy(false)}}
 const archive=async(c:Camp)=>{if(!confirm(`Delete campaign “${c.name}”? It is archived, not erased, and leaves this list.`))return;if(lock.current)return;lock.current=true;setBusy(true);setError('');setNotice('')
  try{await api.call(`${BASE}/records/${c.id}`,'DELETE');setNotice('Campaign deleted.');if(editing?.id===c.id){reset();setOpen(false)};await load()}catch(er){setError((er as Error).message)}finally{lock.current=false;setBusy(false)}}
 const exportCsv=async()=>{setError('');try{const p=new URLSearchParams({q:q.trim()});if(status)p.set('status',status)
   const r=await api.call<{items:Rec[];truncated:boolean}>(`${BASE}/export?${p}`,'GET'),list=r.items.map(x=>toCamp({...x,id:''})).filter(inRange)
   const head=['Campaign','Channel','Owner','Status','Start date','End date','Budget','Amount spent','Leads generated','Conversions','Conversion rate (%)','Revenue','Description']
   const body=list.map(c=>[c.name,c.channel,c.owner,c.status,c.start,c.end,c.budget,c.spend,c.leads,c.conv,pct(c.conv,c.leads),c.revenue,c.rec.description])
   const a=document.createElement('a');a.href=URL.createObjectURL(new Blob(['﻿'+[head,...body].map(row=>row.map(csvCell).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'}));a.download='campaigns.csv';a.click();URL.revokeObjectURL(a.href)
   if(r.truncated)setError('Export is limited to the latest 10,000 records.')}catch(er){setError((er as Error).message)}}
 const set=(key:keyof typeof EMPTY)=>(e:{target:{value:string}})=>setForm({...form,[key]:e.target.value})
 const clearFilters=()=>{setQ('');setStatus('');setFrom('');setTo('');setPage(1)}
 return <div className="panel ops"><PageHead title="Sales & Marketing" subtitle="Campaign performance at a glance. Figures come from the campaign records below; “N/A” means nothing has been recorded to calculate it.">
   {can('export')&&<button className="ghost" onClick={()=>void exportCsv()}>Export CSV</button>}{can('write')&&<button className="btn" aria-expanded={open} aria-controls="campaign-form" onClick={()=>{if(open&&!editing){setOpen(false)}else{if(editing)reset();setOpen(true)}}}>{open&&!editing?'Close form':'Create campaign'}</button>}</PageHead>
  <Notices error={error} notice={notice} onRetry={()=>void load()}/>
  {all==null?<Loading/>:<>
  <form className="filters" onSubmit={e=>e.preventDefault()} aria-label="Filters"><label>Search<input aria-label="Search campaigns" placeholder="Name, channel, owner or status" value={q} onChange={e=>{setQ(e.target.value);setPage(1)}}/></label>
   <label>Status<select aria-label="Filter by status" value={status} onChange={e=>{setStatus(e.target.value);setPage(1)}}><option value="">All statuses</option>{statuses.map(s=><option key={s} value={s}>{s}</option>)}</select></label>
   <label>Starts from<input type="date" value={from} max={to||undefined} onChange={e=>{setFrom(e.target.value);setPage(1)}}/></label><label>Starts to<input type="date" value={to} min={from||undefined} onChange={e=>{setTo(e.target.value);setPage(1)}}/></label>
   <button type="button" className="ghost" onClick={clearFilters} disabled={!hasFilter}>Clear filters</button><span className="note">{shown.length} of {camps.length} campaign(s). Date filters use each campaign’s start date (or the date it was added if none is set).</span></form>
  <div className="cards" aria-label="Campaign KPIs"><Stat name="Total campaigns" value={k.total}/><Stat name="Active campaigns" value={k.active}/><Stat name="Total leads generated" value={fmt(k.leads)}/><Stat name="Conversion rate" value={k.rate==null?'N/A':`${k.rate}%`}/><Stat name="Total marketing spend" value={fmt(k.spend,2)}/><Stat name="Revenue" value={fmt(k.revenue,2)}/></div>
  <p className="note">Active = status “In Progress”. Conversion rate uses the {k.both} campaign(s) that have both leads and conversions recorded. Amounts are shown as entered (no currency conversion). Revenue is the figure recorded against each campaign.{truncated&&' Showing the most recent 2,000 campaigns only.'}</p>
  <div className="sm-charts">
   <div className="ops-card"><h3>Campaign performance</h3><Plot data={perf} empty="No leads recorded on any campaign yet."><BarChart data={perf} margin={{top:8,right:8,left:0,bottom:0}}><CartesianGrid strokeDasharray="3 3" vertical={false}/><XAxis dataKey="name" interval={0} tick={{fontSize:11}}/><YAxis allowDecimals={false}/><Tooltip/><Legend/><Bar dataKey="Leads" fill="#1d4ed8"/><Bar dataKey="Conversions" fill="#10b981"/></BarChart></Plot></div>
   <div className="ops-card"><h3>Leads generated by channel</h3><Plot data={byChannel} empty="No leads recorded on any campaign yet."><BarChart data={byChannel} margin={{top:8,right:8,left:0,bottom:0}}><CartesianGrid strokeDasharray="3 3" vertical={false}/><XAxis dataKey="name" interval={0} tick={{fontSize:11}}/><YAxis allowDecimals={false}/><Tooltip/><Bar dataKey="Leads" fill="#0ea5e9"/></BarChart></Plot></div>
   <div className="ops-card"><h3>Monthly marketing spend</h3><Plot data={spendByMonth} empty="No spend (amount) recorded on any campaign yet."><BarChart data={spendByMonth} margin={{top:8,right:8,left:0,bottom:0}}><CartesianGrid strokeDasharray="3 3" vertical={false}/><XAxis dataKey="name"/><YAxis/><Tooltip formatter={(v:unknown)=>fmt(Number(v),2)}/><Bar dataKey="Spend" fill="#f59e0b"/></BarChart></Plot></div>
   <div className="ops-card"><h3>Campaign conversion trend</h3><Plot data={trend} empty="Needs campaigns with both leads and conversions recorded."><LineChart data={trend} margin={{top:8,right:8,left:0,bottom:0}}><CartesianGrid strokeDasharray="3 3" vertical={false}/><XAxis dataKey="name"/><YAxis unit="%"/><Tooltip/><Line type="monotone" dataKey="Conversion rate (%)" stroke="#6d28d9" strokeWidth={2} dot/></LineChart></Plot></div>
  </div>
  <div className="sm-sec"><h3 style={{margin:0}}>Campaign performance table</h3></div>
  {!shown.length?<Empty msg={camps.length?'No campaigns match the filters.':'No campaigns yet. Use “Create campaign” to add the first one.'}/>:<div className="ops-tablewrap"><table><thead><tr><th>Campaign</th><th>Channel</th><th>Period</th><th>Budget</th><th>Spend</th><th>Leads</th><th>Conversions</th><th>Status</th><th>Actions</th></tr></thead><tbody>
   {rows.map(c=><tr key={c.id}><td>{c.name}{c.owner&&<small>Owner: {c.owner}</small>}</td><td>{c.channel||'—'}</td><td>{c.start?fmtDate(c.start):'—'}{c.end&&<small>to {fmtDate(c.end)}</small>}</td><td>{fmt(c.budget,2)}</td><td>{fmt(c.spend,2)}</td><td>{fmt(c.leads)}</td><td>{fmt(c.conv)}{pct(c.conv,c.leads)!=null&&<small>{pct(c.conv,c.leads)}% of leads</small>}</td><td><Badge v={statusKey(c.status)}/></td>
    <td>{can('write')&&<button className="ghost" onClick={()=>startEdit(c)} aria-label={`Edit ${c.name}`}>Edit</button>}{can('archive')&&<> <button className="ghost" disabled={busy} onClick={()=>void archive(c)} aria-label={`Delete ${c.name}`}>Delete</button></>}{!can('write')&&!can('archive')&&'—'}</td></tr>)}</tbody></table></div>}
  <Pager page={cur} total={shown.length} limit={PAGE} set={setPage}/>
  {open&&<div ref={formRef} id="campaign-form" className="ops-card sm-form"><form className="formgrid" onSubmit={save} aria-label={editing?'Edit campaign':'Create campaign'} noValidate={false}><h3 className="wide" style={{margin:0}}>{editing?`Edit “${editing.title}”`:'Create campaign'}</h3>
   {formError&&<div className="err wide" role="alert"><span>{formError}</span></div>}
   <label className="wide">Title *<input required maxLength={180} value={form.title} onChange={set('title')}/></label>
   <label>Status<select value={form.status} onChange={set('status')}>{statuses.map(s=><option key={s} value={s}>{s}</option>)}</select></label>
   <label>Campaign channel<select value={form.channel} onChange={set('channel')}><option value="">Not set</option>{Array.from(new Set([...CHANNELS,...(form.channel?[form.channel]:[])])).map(c=><option key={c} value={c}>{c}</option>)}</select></label>
   <label>Owner<input maxLength={120} value={form.owner} onChange={set('owner')}/></label>
   <label>Budget<input type="number" min="0" step="0.01" value={form.budget} onChange={set('budget')}/></label>
   <label>Amount spent<input type="number" min="0" step="0.01" value={form.amount} onChange={set('amount')}/></label>
   <label>Start date<input type="date" max={form.due_date||undefined} value={form.start_date} onChange={set('start_date')}/></label>
   <label>End date<input type="date" min={form.start_date||undefined} value={form.due_date} onChange={set('due_date')}/></label>
   <label>Leads generated<input type="number" min="0" step="1" value={form.leads_generated} onChange={set('leads_generated')}/></label>
   <label>Conversions<input type="number" min="0" step="1" value={form.conversions} onChange={set('conversions')}/></label>
   <label>Revenue from campaign<input type="number" min="0" step="0.01" value={form.revenue} onChange={set('revenue')}/></label>
   <label className="wide">Description<textarea maxLength={5000} value={form.description} onChange={set('description')}/></label>
   <div className="wide" style={{display:'flex',gap:8,flexWrap:'wrap'}}><button className="btn" disabled={busy}>{busy?'Saving…':editing?'Save changes':'Create campaign'}</button><button type="button" className="ghost" onClick={reset} disabled={busy}>Clear form</button><button type="button" className="ghost" onClick={()=>{reset();setOpen(false)}}>Close</button></div></form></div>}
  </>}
 </div>}
