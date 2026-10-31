import {useCallback,useEffect,useMemo,useRef,useState} from 'react'
import type {FormEvent,ReactNode} from 'react'
import {api} from './api'
import {Icon,dmy,inr,newest,pill,tone,ymd,Empty} from './modkit'
import type {ExportOut,Rec,Summary} from './modkit'
import './module-pages.css'

/* Shared page engine for the record-based CEO pages. Each module supplies its OWN config (fields, cards, charts, columns);
   the engine only handles what is identical between them: the same /workspaces/<module> endpoints the generic workspace used
   (list, summary, create, update, archive, export), filters, paging, CSV export and the page layout. */
export type Bucket={label:string;match:(r:Rec)=>boolean}
export type Field={key:string;label:string;type?:'text'|'number'|'date'|'select'|'url'|'email';options?:string[];placeholder?:string;step?:string;min?:string;max?:string}
export type Card={k:string;label:string;value:string;sub?:string;ic:string;c:'green'|'blue'|'purple'|'red'|'amber'|'teal';filter?:Bucket;clear?:boolean}
export type Col={label:string;cell:(r:Rec)=>ReactNode}
export type Ctx={summary:Summary|null;items:Rec[]|null;truncated:boolean;err:string;extra:unknown;extraErr:string;createdThisMonth:number}
export type Cfg={module:string;subtitle:string;formTitle:string;listTitle:string;noun:string;fields:Field[];columns:Col[];cards:(c:Ctx)=>Card[];charts:(c:Ctx)=>ReactNode;titleLabel?:string;hide?:('amount'|'due_date')[];layout:'wide'|'eq'|'quad';footnote:string;loadExtra?:(rangeQs:string)=>Promise<unknown>;validate?:(f:Record<string,string>)=>string}
type FormState={title:string;status:string;description:string;amount:string;due_date:string}

const LIMIT=25,DESC_MAX=5000
export const STATUSES=['Open','In Progress','Pending','Approved','Completed','Won','Lost','Blocked','Cancelled']
const BLANK:FormState={title:'',status:'Open',description:'',amount:'',due_date:''}
export const pctOf=(s:Summary|null,x:number)=>s&&s.total>0?`${Math.round(x/s.total*100)}% of records`:s?'No records yet':''
/* Cards: a card is a button only when it has a `filter` (shows the matching records) or `clear` (shows all records). */
export const OPEN_ST=['Open','In Progress','Pending'],DONE_ST=['Completed'],LOST_ST=['Lost','Cancelled']
export const inStatus=(label:string,names:string[]):Bucket=>({label,match:r=>names.includes(r.status)})
export const withAmount:Bucket={label:'Records with an amount',match:r=>r.amount!=null}
export const statusCount=(s:Summary|null,name:string)=>s?.statuses?.find(x=>x.status===name)?.count??0

export default function RecordsPage({title,cfg}:{title:string;cfg:Cfg}){
 const M=cfg.module,hide=new Set(cfg.hide||[])
 const [items,setItems]=useState<Rec[]>([]),[total,setTotal]=useState(0),[page,setPage]=useState(1),[summary,setSummary]=useState<Summary|null>(null),[loaded,setLoaded]=useState(false)
 const [insight,setInsight]=useState<{items:Rec[];truncated:boolean}|null>(null),[insightErr,setInsightErr]=useState(''),[extra,setExtra]=useState<unknown>(null),[extraErr,setExtraErr]=useState('')
 const [q,setQ]=useState(''),[appliedQ,setAppliedQ]=useState(''),[statusFilter,setStatusFilter]=useState(''),[from,setFrom]=useState(''),[to,setTo]=useState('')
 const [bucket,setBucket]=useState<Bucket|null>(null),recRef=useRef<HTMLElement>(null),[error,setError]=useState(''),[loadErr,setLoadErr]=useState(''),[formErr,setFormErr]=useState(''),[notice,setNotice]=useState(''),[exporting,setExporting]=useState(false),[busy,setBusy]=useState(false),[edit,setEdit]=useState<Rec|null>(null),[form,setForm]=useState<FormState>(BLANK),[custom,setCustom]=useState<Record<string,string>>({}),[rangeOpen,setRangeOpen]=useState(false)
 const formRef=useRef<HTMLFormElement>(null),rangeRef=useRef<HTMLDivElement>(null),tSeq=useRef(0),iSeq=useRef(0),eSeq=useRef(0)

 const query=useMemo(()=>{const p=new URLSearchParams({q:appliedQ,page:String(page),limit:String(LIMIT)});if(statusFilter)p.set('status',statusFilter);if(from)p.set('date_from',from);if(to)p.set('date_to',to);return p.toString()},[appliedQ,page,statusFilter,from,to])
 const rangeQs=useMemo(()=>{const p=new URLSearchParams();if(from)p.set('date_from',from);if(to)p.set('date_to',to);const s=p.toString();return s?'?'+s:''},[from,to])

 const loadTable=useCallback(async()=>{const id=++tSeq.current;setLoadErr('')
  try{const [r,sm]=await Promise.all([api.call<{items:Rec[];total:number}>(`/workspaces/${M}?${query}`,'GET'),api.call<Summary>(`/workspaces/${M}/summary${rangeQs}`,'GET')]);if(id!==tSeq.current)return;setItems(r.items);setTotal(r.total);setSummary(sm)}
  catch(e){if(id===tSeq.current)setLoadErr((e as Error).message)}finally{if(id===tSeq.current)setLoaded(true)}},[M,query,rangeQs])
 /* Charts read every record in the selected date range through the same export endpoint as the CSV button (server cap: 10,000). */
 const loadInsight=useCallback(async()=>{const id=++iSeq.current;setInsightErr('')
  try{const r=await api.call<ExportOut>(`/workspaces/${M}/export${rangeQs}`,'GET');if(id!==iSeq.current)return;setInsight({items:r.items,truncated:!!r.truncated})}
  catch(e){if(id===iSeq.current){setInsight(null);setInsightErr((e as Error).message)}}},[M,rangeQs])
 const loadExtra=useCallback(async()=>{if(!cfg.loadExtra)return;const id=++eSeq.current;setExtraErr('')
  try{const r=await cfg.loadExtra(rangeQs);if(id===eSeq.current)setExtra(r)}catch(e){if(id===eSeq.current){setExtra(null);setExtraErr((e as Error).message)}}},[cfg,rangeQs])
 useEffect(()=>{void loadTable()},[loadTable]);useEffect(()=>{void loadInsight()},[loadInsight]);useEffect(()=>{void loadExtra()},[loadExtra])
 useEffect(()=>{if(!rangeOpen)return;const h=(e:MouseEvent)=>{if(rangeRef.current&&!rangeRef.current.contains(e.target as Node))setRangeOpen(false)},k=(e:KeyboardEvent)=>{if(e.key==='Escape')setRangeOpen(false)};document.addEventListener('mousedown',h);document.addEventListener('keydown',k);return()=>{document.removeEventListener('mousedown',h);document.removeEventListener('keydown',k)}},[rangeOpen])
 useEffect(()=>{if(!notice)return;const t=window.setTimeout(()=>setNotice(''),4000);return()=>window.clearTimeout(t)},[notice])
 /* Archiving the last row of the last page would otherwise leave the user on an empty page. */
 useEffect(()=>{if(!bucket&&loaded&&!items.length&&total>0&&page>1)setPage(Math.max(1,Math.ceil(total/LIMIT)))},[bucket,loaded,items.length,total,page])

 const ctx:Ctx=useMemo(()=>{const all=insight?.items||null,now=new Date(),key=now.getFullYear()*12+now.getMonth()
  const createdThisMonth=(all||[]).filter(r=>{const d=new Date(r.created_at);return !isNaN(+d)&&d.getFullYear()*12+d.getMonth()===key}).length
  return {summary,items:all?newest(all):null,truncated:!!insight?.truncated,err:insightErr,extra,extraErr,createdThisMonth}},[summary,insight,insightErr,extra,extraErr])
 const cards=useMemo(()=>cfg.cards(ctx),[cfg,ctx])
 /* While a card filter is active the list is built from the same records the charts use (date range applied, newest first). */
 const view=useMemo(()=>{if(!bucket||!ctx.items)return null;const k=appliedQ.trim().toLowerCase();return ctx.items.filter(r=>bucket.match(r)&&(!k||`${r.title} ${r.description??''} ${r.status}`.toLowerCase().includes(k)))},[bucket,ctx.items,appliedQ])
 const shownTotal=bucket?(view?view.length:0):total,pages=Math.max(1,Math.ceil(shownTotal/LIMIT)),pg=Math.min(page,pages)
 const shown=bucket?(view?view.slice((pg-1)*LIMIT,pg*LIMIT):[]):items,bucketWait=!!bucket&&!view&&!insightErr
 const pickCard=(c:Card)=>{if(c.filter){setStatusFilter('');setBucket(c.filter)}else if(c.clear){setStatusFilter('');setBucket(null)}else return;setPage(1);recRef.current?.scrollIntoView({behavior:'smooth',block:'start'})}
 const pickStatus=(v:string)=>{setBucket(null);setStatusFilter(v);setPage(1)}

 const refreshAll=async()=>{await Promise.all([loadTable(),loadInsight(),loadExtra()])}
 const reset=()=>{setEdit(null);setForm(BLANK);setCustom({})}
 const setC=(k:string,v:string)=>setCustom(c=>({...c,[k]:v}))
 const save=async(e:FormEvent)=>{e.preventDefault();setFormErr('');setNotice('')
  const title=form.title.trim();if(!title){setFormErr('Title is required.');return}
  if(form.amount!==''&&!(isFinite(Number(form.amount))&&Number(form.amount)>=0)){setFormErr('Amount must be a number of 0 or more.');return}
  for(const f of cfg.fields){const v=custom[f.key];if(f.type!=='number'||v===undefined||v==='')continue;const x=Number(v)
   if(!isFinite(x)){setFormErr(`${f.label} must be a number.`);return}
   if(f.min!==undefined&&x<Number(f.min)){setFormErr(`${f.label} must be at least ${f.min}.`);return}
   if(f.max!==undefined&&x>Number(f.max)){setFormErr(`${f.label} must be at most ${f.max}.`);return}}
  const bad=cfg.validate?.(custom);if(bad){setFormErr(bad);return}
  setBusy(true)
  try{const fields:Record<string,unknown>={};for(const f of cfg.fields){const v=(custom[f.key]??'').trim();if(v!=='')fields[f.key]=f.type==='number'?Number(v):v}
   const body={...form,title,amount:form.amount===''?null:Number(form.amount),due_date:form.due_date||null,fields}
   if(edit)await api.call(`/workspaces/${M}/records/${edit.id}`,'PATCH',body);else await api.call(`/workspaces/${M}/records`,'POST',body)
   const msg=edit?`${cfg.noun} updated.`:`${cfg.noun} created.`;reset();setNotice(msg);await refreshAll()}
  catch(err){setFormErr((err as Error).message)}finally{setBusy(false)}}
 const archive=async(r:Rec)=>{if(!confirm(`Archive “${r.title}”? It will be removed from this list.`))return;setError('');setNotice('')
  try{await api.call(`/workspaces/${M}/records/${r.id}`,'DELETE');if(edit?.id===r.id)reset();setNotice(`“${r.title}” archived.`);await refreshAll()}catch(err){setError((err as Error).message)}}
 const startEdit=(r:Rec)=>{setNotice('');setFormErr('');setEdit(r);setForm({title:r.title,status:r.status,description:r.description??'',amount:r.amount==null?'':String(r.amount),due_date:r.due_date||''})
  setCustom(Object.fromEntries(cfg.fields.map(f=>[f.key,String(r.fields?.[f.key]??'')])));formRef.current?.scrollIntoView({behavior:'smooth',block:'start'})}
 /* CSV cells starting with = + - @ are prefixed with ' so spreadsheet apps never run them as formulas. */
 const csvCell=(v:unknown)=>{let t=String(v??'');if(/^[=+\-@\t\r]/.test(t))t="'"+t;return `"${t.replace(/"/g,'""')}"`}
 const exportCsv=async()=>{setError('');setNotice('');setExporting(true)
  try{const ep=new URLSearchParams({q:appliedQ});if(statusFilter)ep.set('status',statusFilter);if(from)ep.set('date_from',from);if(to)ep.set('date_to',to)
   let list:Rec[],trunc=false
   if(bucket){if(!view)throw new Error('Records are still loading. Try again in a moment.');list=view;trunc=ctx.truncated}else{const r=await api.call<ExportOut>(`/workspaces/${M}/export?${ep.toString()}`,'GET');list=r.items;trunc=!!r.truncated}
   if(!list.length){setError('No records match the current filters, so there is nothing to export.');return}
   const rows=[['Title','Status','Description','Amount','Due date','Fields','Created','Updated'],...list.map(x=>[x.title,x.status,x.description,x.amount,x.due_date,JSON.stringify(x.fields||{}),x.created_at,x.updated_at])]
   const url=URL.createObjectURL(new Blob(['\ufeff'+rows.map(row=>row.map(csvCell).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'}))
   const a=document.createElement('a');a.href=url;a.download=`${M}-records.csv`;document.body.appendChild(a);a.click();a.remove();window.setTimeout(()=>URL.revokeObjectURL(url),1000)
   if(trunc)setError('Export is limited to the latest 10,000 records.');else setNotice(`Exported ${list.length} record(s).`)}
  catch(err){setError((err as Error).message)}finally{setExporting(false)}}
 const setRange=(f:string,t:string)=>{setFrom(f);setTo(t);setPage(1)}
 const preset=(k:'month'|'3m'|'year'|'all')=>{const d=new Date();if(k==='all')setRange('','');else if(k==='month')setRange(ymd(new Date(d.getFullYear(),d.getMonth(),1)),ymd(new Date(d.getFullYear(),d.getMonth()+1,0)));else if(k==='3m')setRange(ymd(new Date(d.getFullYear(),d.getMonth()-2,1)),ymd(new Date(d.getFullYear(),d.getMonth()+1,0)));else setRange(`${d.getFullYear()}-01-01`,`${d.getFullYear()}-12-31`)}
 const clearFilters=()=>{setBucket(null);setQ('');setAppliedQ('');setStatusFilter('');setRange('','')}
 const rangeLabel=from||to?`${from?pill(from):'Start'} - ${to?pill(to):'Today'}`:'All time'
  const input=(f:Field)=>f.type==='select'
  ?<select value={custom[f.key]||''} onChange={e=>setC(f.key,e.target.value)}><option value="">Select…</option>{f.options?.map(o=><option key={o}>{o}</option>)}</select>
  :<input type={f.type||'text'} step={f.step} min={f.min} max={f.max} placeholder={f.placeholder} value={custom[f.key]||''} onChange={e=>setC(f.key,e.target.value)}/>

 return <div className="sm">
  <header className="sm-head"><p className="sm-lead">{cfg.subtitle}</p>
   <div className="sm-range" ref={rangeRef}><button type="button" className="sm-rangebtn" aria-haspopup="dialog" aria-expanded={rangeOpen} onClick={()=>setRangeOpen(o=>!o)}><Icon n="calendar"/><span>{rangeLabel}</span><Icon n="chev"/></button>
    {rangeOpen&&<div className="sm-pop" role="dialog" aria-label="Date range"><div className="sm-presets">{([['month','This month'],['3m','Last 3 months'],['year','This year'],['all','All time']] as const).map(([k,l])=><button key={k} type="button" onClick={()=>{preset(k);setRangeOpen(false)}}>{l}</button>)}</div>
     <label>From<input type="date" value={from} max={to||undefined} onChange={e=>setRange(e.target.value,to)}/></label><label>To<input type="date" value={to} min={from||undefined} onChange={e=>setRange(from,e.target.value)}/></label></div>}</div></header>

  {loadErr&&<div className="err" role="alert">{loadErr} <button type="button" className="ghost" onClick={()=>void refreshAll()}>Retry</button></div>}
  {error&&<div className="err" role="alert">{error} <button type="button" className="ghost" onClick={()=>setError('')}>Dismiss</button></div>}
  {notice&&<div className="sm-notice" role="status">{notice}</div>}

  <section className="sm-cards" aria-label="Summary">{cards.map(c=>{const body=<><span className="sm-tile"><Icon n={c.ic}/></span><span className="sm-ctext"><span className="sm-lbl">{c.label}</span><strong>{c.value}</strong>{c.sub&&<em>{c.sub}</em>}</span></>
   if(!c.filter&&!c.clear)return <div key={c.k} className={`sm-card t-${c.c}`}>{body}</div>
   const on=c.filter?bucket?.label===c.filter.label:!bucket&&!statusFilter
   return <button key={c.k} type="button" className={`sm-card sm-click t-${c.c}${on?' on':''}`} aria-pressed={on} title={c.filter?`Show: ${c.filter.label}`:'Show all records'} onClick={()=>pickCard(c)}>{body}</button>})}</section>

  <section className={`sm-charts ${cfg.layout}`} aria-label="Charts">{cfg.charts(ctx)}<p className="sm-foot">{cfg.footnote}{ctx.truncated?' Based on the latest 10,000 records.':''}</p></section>

  <form ref={formRef} onSubmit={save} className="sm-box sm-form"><h3><Icon n="doc"/>{edit?`Edit ${cfg.noun}`:cfg.formTitle}</h3>
   <div className="sm-grid">
    <label>{cfg.titleLabel||'Title'} *<input required maxLength={180} placeholder="Enter title" value={form.title} onChange={e=>setForm({...form,title:e.target.value})}/></label>
    <label>Status<select value={form.status} onChange={e=>setForm({...form,status:e.target.value})}>{STATUSES.map(x=><option key={x}>{x}</option>)}</select></label>
    {!hide.has('amount')&&<label>Amount (₹)<input type="number" min="0" step="0.01" placeholder="Enter amount (optional)" value={form.amount} onChange={e=>setForm({...form,amount:e.target.value})}/></label>}
    {!hide.has('due_date')&&<label>Due date<input type="date" value={form.due_date} onChange={e=>setForm({...form,due_date:e.target.value})}/></label>}
    {cfg.fields.map(f=><label key={f.key}>{f.label}{input(f)}</label>)}</div>
   {formErr&&<div className="err sm-formerr" role="alert">{formErr}</div>}
   <div className="sm-descrow"><label className="sm-desc">Description<textarea maxLength={DESC_MAX} placeholder="Enter description / notes…" value={form.description} onChange={e=>setForm({...form,description:e.target.value})}/><small>{form.description.length}/{DESC_MAX}</small></label>
    <div className="sm-actions"><button className="btn" disabled={busy}>{busy?'Saving…':edit?'Save changes':<><Icon n="plus"/> Create record</>}</button><button type="button" className="ghost" onClick={reset}>{edit?'Cancel':'Clear'}</button></div></div></form>

  <section className="sm-box" aria-label="Records" ref={recRef}><div className="sm-tophead"><h3><Icon n="doc"/>{cfg.listTitle}</h3><button type="button" className="ghost sm-export" disabled={exporting} onClick={()=>void exportCsv()}><Icon n="download"/>{exporting?'Exporting…':'Export all matching CSV'}</button></div>
   <div className="sm-filters"><label className="sm-find"><Icon n="search"/><input aria-label="Search records" placeholder="Search title, description, status…" value={q} onChange={e=>setQ(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'){e.preventDefault();setPage(1);setAppliedQ(q)}}}/></label>
    <label>Status<select value={statusFilter} onChange={e=>pickStatus(e.target.value)}><option value="">All statuses</option>{STATUSES.map(x=><option key={x}>{x}</option>)}</select></label>
    <label>Created from<input type="date" value={from} max={to||undefined} onChange={e=>setRange(e.target.value,to)}/></label><label>Created to<input type="date" value={to} min={from||undefined} onChange={e=>setRange(from,e.target.value)}/></label>
    <button type="button" className="btn sm-search" onClick={()=>{setPage(1);setAppliedQ(q)}}>Search</button><button type="button" className="ghost" onClick={clearFilters}>Clear filters</button><span className="note">{shownTotal} record(s)</span></div>
   {bucket&&<div className="sm-bucket" role="status">Showing: <b>{bucket.label}</b> · {shownTotal} record(s) <button type="button" className="ghost" onClick={()=>{setBucket(null);setPage(1)}}>Show all</button></div>}
   {summary?.statuses?.length?<div className="sm-chips" aria-label="Status breakdown">{summary.statuses.map(x=><button key={x.status} type="button" className={`sm-chip ${tone(x.status)}${statusFilter===x.status?' on':''}`} onClick={()=>pickStatus(statusFilter===x.status?'':x.status)}>{x.status} <b>{x.count}</b></button>)}</div>:null}
   {!loaded||bucketWait?<Empty msg="Loading…"/>:!shown.length?<Empty msg={loadErr||(bucket&&insightErr)?'Records could not be loaded. Use Retry above.':'No records found. Create a record above or change your filters.'}/>:<>
    <div className="sm-table"><table><thead><tr><th>#</th><th>Title</th><th>Status</th>{!hide.has('amount')&&<th>Amount (₹)</th>}{!hide.has('due_date')&&<th>Due date</th>}{cfg.columns.map(c=><th key={c.label}>{c.label}</th>)}<th>Created on</th><th>Actions</th></tr></thead>
     <tbody>{shown.map((r,i)=><tr key={r.id}><td>{(pg-1)*LIMIT+i+1}</td><td className="sm-ttl">{r.title}{r.description&&<small title={r.description}>{r.description}</small>}</td><td><span className={`sm-badge ${tone(r.status)}`}>{r.status}</span></td>{!hide.has('amount')&&<td>{inr(r.amount)}</td>}{!hide.has('due_date')&&<td>{dmy(r.due_date)}</td>}{cfg.columns.map(c=><td key={c.label}>{c.cell(r)}</td>)}<td>{dmy(r.created_at)}</td>
      <td className="sm-act"><button type="button" className="sm-icbtn" aria-label={`Edit ${r.title}`} title="Edit" onClick={()=>startEdit(r)}><Icon n="edit"/></button><button type="button" className="sm-icbtn del" aria-label={`Archive ${r.title}`} title="Archive" onClick={()=>void archive(r)}><Icon n="trash"/></button></td></tr>)}</tbody></table></div>
    <div className="sm-pager"><span className="note">Page {pg} of {pages}</span><div><button type="button" className="ghost" disabled={pg<=1} onClick={()=>setPage(pg-1)}>Previous</button> <button type="button" className="ghost" disabled={pg>=pages} onClick={()=>setPage(pg+1)}>Next</button></div></div></>}</section>
 </div>}
