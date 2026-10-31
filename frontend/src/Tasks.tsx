import {useEffect,useRef,useState,FormEvent,KeyboardEvent as ReactKey,ReactNode} from 'react'; import {createPortal} from 'react-dom'; import {api} from './api'
import './Tasks.css'
// Tasks & Approvals dashboard. The server decides what each row allows (can_edit / can_change_status / can_decide) and what each role may do (can_write / can_assign / can_archive); this page only reflects it.
// Every figure comes from the existing GET /tasks endpoint: KPI counts are its `total` for a status (page_size=1), overdue is counted from real due dates.
// The server filters only by q / status / mine. Priority, assignee and due-date filters therefore load every matching page and filter locally, so results are never silently limited to one page.
type Task={id:string;title:string;description?:string|null;assignee_id?:string|null;assignee_name?:string|null;priority:string;due_date?:string|null;status:string;requires_approval?:boolean;decision_note?:string|null;can_edit?:boolean;can_change_status?:boolean;can_decide?:boolean}
type Panel={mode:'edit';form:any}|{mode:'view';id:string;snap:Task}
const PRIORITY:Record<string,string>={low:'Low',normal:'Normal',high:'High'},PRIORITY_TONE:Record<string,string>={low:'grey',normal:'blue',high:'red'}
const STATUS_TONE:Record<string,string>={open:'info',in_progress:'blue',pending_approval:'amber',done:'green',cancelled:'grey'},EDITABLE=['open','in_progress','done','cancelled']
const DUE:Record<string,string>={overdue:'Overdue',today:'Due today',week:'Due in next 7 days',none:'No due date'}
const SIZE=20,BIG=100,MAX_PAGES=20 // rows per page shown; rows per request when loading everything; safety cap on pages (2,000 tasks)
const pad=(n:number)=>String(n).padStart(2,'0'),iso=(d:Date)=>`${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`
const day=(s:string)=>new Date(s+'T00:00:00Z').toLocaleDateString([],{day:'2-digit',month:'short',year:'numeric',timeZone:'UTC'})
const initials=(n?:string|null)=>(n||'').split(/\s+/).filter(Boolean).slice(0,2).map(w=>w[0].toUpperCase()).join('')||'–'
// One definition of "overdue", used by the KPI card and the due-date filter: past its due date and still open or in progress.
const isOverdue=(r:Task,today:string)=>!!r.due_date&&r.due_date<today&&(r.status==='open'||r.status==='in_progress')
const dueOk=(r:Task,f:string,today:string,week:string)=>f==='overdue'?isOverdue(r,today):f==='today'?r.due_date===today:f==='week'?!!r.due_date&&r.due_date>=today&&r.due_date<=week:f==='none'?!r.due_date:true
// Loads every page for a query. Uses the server's own page_size if it clamps ours. `truncated` is true if the safety cap stopped it.
async function fetchAll(qs:string){
 const first=await api.call(`/tasks?page=1&page_size=${BIG}${qs}`,'GET'),n=first.items.length,size=first.page_size||(first.total>n?n:BIG)||1,pages=Math.min(MAX_PAGES,Math.ceil(first.total/size))
 const rest=await Promise.all(Array.from({length:Math.max(0,pages-1)},(_,i)=>api.call(`/tasks?page=${i+2}&page_size=${size}${qs}`,'GET')))
 return {meta:first,items:[first,...rest].flatMap((r:any)=>r.items) as Task[],total:first.total as number,truncated:first.total>pages*size}}

const ICONS:Record<string,ReactNode>={list:<path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"/>,timer:<><circle cx="12" cy="13" r="8"/><path d="M12 9v4l2 2M9 3h6"/></>,
 check:<><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></>,alert:<><path d="M12 4 2.5 20h19L12 4z"/><path d="M12 10v4M12 17h.01"/></>,shield:<><path d="M12 3 5 6v5c0 4.5 3 8 7 10 4-2 7-5.5 7-10V6l-7-3z"/><path d="m9 12 2 2 4-4"/></>}
const Icon=({n}:{n:string})=><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{ICONS[n]}</svg>
const Badge=({tone,children,className=''}:{tone:string;children:ReactNode;className?:string})=><span className={`tk-badge tk-badge--${tone} ${className}`}>{children}</span>

// Right-hand side panel for details and create/edit. Esc or the backdrop closes it; Tab stays inside; focus returns to where it came from.
function SidePanel({title,onClose,children}:{title:string;onClose:()=>void;children:ReactNode}){
 const ref=useRef<HTMLElement>(null),close=useRef(onClose);close.current=onClose
 useEffect(()=>{const prev=document.activeElement as HTMLElement|null;ref.current?.focus();return()=>{prev?.focus?.()}},[])
 const key=(e:ReactKey<HTMLElement>)=>{if(e.key==='Escape'){e.stopPropagation();close.current();return}
  if(e.key!=='Tab'||!ref.current)return;const f=[...ref.current.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[href]')];if(!f.length)return
  const a=document.activeElement;if(e.shiftKey&&(a===f[0]||a===ref.current)){e.preventDefault();f[f.length-1].focus()}else if(!e.shiftKey&&a===f[f.length-1]){e.preventDefault();f[0].focus()}}
 return createPortal(<div className="tk-layer"><div className="tk-backdrop" onClick={onClose}/><aside ref={ref} className="tk-panel" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} onKeyDown={key}>
  <header className="tk-panel-h"><h3>{title}</h3><button type="button" className="tk-x" aria-label="Close panel" onClick={onClose}>×</button></header><div className="tk-panel-b">{children}</div></aside></div>,document.body)}

export default function Tasks(){
 const [data,setData]=useState<{items:Task[];total:number;truncated:boolean}>({items:[],total:0,truncated:false}),[meta,setMeta]=useState<any>({statuses:[],status_labels:{}}),[page,setPage]=useState(1),[q,setQ]=useState(''),[status,setStatus]=useState(''),[mine,setMine]=useState(false),
  [priority,setPriority]=useState(''),[assignee,setAssignee]=useState(''),[due,setDue]=useState(''),[err,setErr]=useState(''),[ok,setOk]=useState(''),[busy,setBusy]=useState(true),[panel,setPanel]=useState<Panel|null>(null),[tick,setTick]=useState(0),
  [people,setPeople]=useState<any[]>([]),[counts,setCounts]=useState<{total:number;inProgress:number;done:number;pending:number}|null>(null),[late,setLate]=useState<{n:number;truncated:boolean}|null>(null)
 const today=iso(new Date()),week=iso(new Date(Date.now()+7*864e5)),local=!!(priority||assignee||due),pageKey=local?0:page,lab=(s:string)=>meta.status_labels?.[s]??s,loadFailed=useRef(false)

 // Table data. Server-paged normally; every page when a local-only filter (priority / assignee / due date) is active.
 useEffect(()=>{let live=true;setBusy(true);const t=setTimeout(()=>{const qs=`&q=${encodeURIComponent(q)}${status?`&status=${status}`:''}${mine?'&mine=true':''}`
  const load=local?fetchAll(qs):api.call(`/tasks?page=${page}&page_size=${SIZE}${qs}`,'GET').then((r:any)=>({meta:r,items:r.items as Task[],total:r.total as number,truncated:false}))
  load.then(r=>{if(!live)return;setData({items:r.items,total:r.total,truncated:r.truncated});setMeta(r.meta);if(loadFailed.current){loadFailed.current=false;setErr('')}})
   .catch(e=>{if(!live)return;loadFailed.current=true;setErr(e.message)}).finally(()=>{if(live)setBusy(false)})},q?250:0)
  return()=>{live=false;clearTimeout(t)}},[pageKey,q,status,mine,local,tick])
 // KPI figures: independent of the table filters, and of each other, so one failure leaves only that card as "—".
 useEffect(()=>{let live=true;const n=(s:string)=>api.call(`/tasks?page=1&page_size=1${s?`&status=${s}`:''}`,'GET').then((r:any)=>r.total as number)
  Promise.all([n(''),n('in_progress'),n('done'),n('pending_approval')]).then(([total,inProgress,done,pending])=>{if(live)setCounts({total,inProgress,done,pending})}).catch(()=>{if(live)setCounts(null)})
  Promise.all([fetchAll('&status=open'),fetchAll('&status=in_progress')]).then(rs=>{if(live)setLate({n:rs.reduce((a,r)=>a+r.items.filter(t=>isOverdue(t,today)).length,0),truncated:rs.some(r=>r.truncated)})}).catch(()=>{if(live)setLate(null)})
  return()=>{live=false}},[tick,today])
 useEffect(()=>{if(!meta.can_assign)return;api.call('/tasks/assignees','GET').then(r=>setPeople(r.items)).catch(()=>{})},[meta.can_assign])

 async function save(e:FormEvent){e.preventDefault();if(panel?.mode!=='edit')return;const form=panel.form;setOk('');setErr('');const b:any={title:form.title,description:form.description??'',priority:form.priority||'normal',requires_approval:!!form.requires_approval}
  if(form.due_date)b.due_date=form.due_date;else if(form.id)b.due_date=null;if(meta.can_assign&&form.assignee_id)b.assignee_id=form.assignee_id
  try{await api.call(`/tasks${form.id?'/'+form.id:''}`,form.id?'PATCH':'POST',b);setOk('Task saved.');setPanel(null);setTick(t=>t+1)}catch(x:any){setErr(x.message)}}
 async function setSt(r:Task,to:string){setOk('');setErr('');try{const n=await api.call(`/tasks/${r.id}`,'PATCH',{status:to});setOk(n.status==='pending_approval'?'Submitted for approval.':'Status updated.')}catch(x:any){setErr(x.message)}setTick(t=>t+1)}
 async function decide(r:Task,decision:'approve'|'reject'){setOk('');setErr('');let note:string|null='';if(decision==='reject'){note=window.prompt('Reason for rejecting this task');if(!note){return}}
  try{await api.call(`/tasks/${r.id}/decision`,'POST',{decision,note});setOk(decision==='approve'?'Task approved.':'Task sent back.')}catch(x:any){setErr(x.message)}setTick(t=>t+1)}
 async function del(r:Task){if(!window.confirm('Delete this task? It will be archived: hidden from the lists, with its history kept.'))return;setOk('');try{await api.call(`/tasks/${r.id}`,'DELETE');setOk('Task deleted (archived).');setPanel(null)}catch(x:any){setErr(x.message)}setTick(t=>t+1)}
 const openEdit=(r?:Task)=>{setPanel({mode:'edit',form:r?{...r,description:r.description??'',due_date:r.due_date??''}:{priority:'normal'}});setErr('');setOk('')}
 const apply=(s:string,d:string)=>{setStatus(s);setDue(d);setPage(1)}
 const clear=()=>{setQ('');setStatus('');setMine(false);setPriority('');setAssignee('');setDue('');setPage(1)}

 // Derived view. In local mode the full result set is filtered and paged here; otherwise the server's page is shown as-is.
 const view=local?data.items.filter(r=>(!priority||r.priority===priority)&&(!assignee||r.assignee_name===assignee)&&dueOk(r,due,today,week)):data.items
 const total=local?view.length:data.total,pages=Math.max(1,Math.ceil(total/SIZE)),shown=local?view.slice((page-1)*SIZE,page*SIZE):view,filtered=!!(q||status||mine||local)
 const names=[...new Set([...people.map(p=>p.name),...data.items.map(r=>r.assignee_name)].filter((x):x is string=>typeof x==='string'&&!!x))].sort((a,b)=>a.localeCompare(b))
 const kpis=[{label:'Total tasks',value:counts?.total,sub:'All tasks you can see',icon:'list',tone:'blue',on:!status&&!due,go:()=>apply('','')},
  {label:'In progress',value:counts?.inProgress,sub:'Being worked on',icon:'timer',tone:'violet',on:status==='in_progress',go:()=>apply('in_progress','')},
  {label:'Completed',value:counts?.done,sub:'Marked done',icon:'check',tone:'green',on:status==='done',go:()=>apply('done','')},
  {label:'Overdue',value:late?`${late.n}${late.truncated?'+':''}`:undefined,sub:'Open or in progress, past due',icon:'alert',tone:'red',on:due==='overdue',go:()=>apply('','overdue')},
  {label:'Pending approvals',value:counts?.pending,sub:'Waiting for a decision',icon:'shield',tone:'amber',on:status==='pending_approval',go:()=>apply('pending_approval','')}]

 const statusCell=(r:Task)=>r.can_change_status?<select aria-label={`Status of ${r.title}`} className={`tk-badge tk-badge--${STATUS_TONE[r.status]??'grey'} tk-badge-select`} value={r.status} onChange={e=>setSt(r,e.target.value)}>{(EDITABLE.includes(r.status)?EDITABLE:[r.status,...EDITABLE]).map(s=><option key={s} value={s}>{lab(s)}</option>)}</select>:<Badge tone={STATUS_TONE[r.status]??'grey'}>{lab(r.status)}</Badge>
 const dueCell=(r:Task)=>r.due_date?<span className={isOverdue(r,today)?'tk-due is-late':'tk-due'}>{day(r.due_date)}{isOverdue(r,today)&&<small> overdue</small>}</span>:'—'
 const actions=(r:Task)=><div className="tk-actions">{r.can_decide&&<><button className="tk-btn tk-btn--ok tk-btn--sm" onClick={()=>decide(r,'approve')}>Approve</button><button className="tk-btn tk-btn--line tk-btn--sm" onClick={()=>decide(r,'reject')}>Reject</button></>}
  {r.can_edit&&<button className="tk-btn tk-btn--line tk-btn--sm" onClick={()=>openEdit(r)}>Edit</button>}{meta.can_archive&&<button className="tk-btn tk-btn--danger tk-btn--sm" onClick={()=>del(r)}>Delete</button>}</div>
 const viewing=panel?.mode==='view'?data.items.find(r=>r.id===panel.id)??panel.snap:null,form=panel?.mode==='edit'?panel.form:null,setForm=(f:any)=>setPanel({mode:'edit',form:f})

 return <div className="tk">
  <header className="tk-head"><div><h2>Tasks &amp; Approvals</h2><p>Track work, due dates and approvals in one place.</p></div>{meta.can_write&&<button className="tk-btn tk-btn--primary" onClick={()=>openEdit()}>Add task</button>}</header>
  {err&&<div className="tk-alert tk-alert--err" role="alert">{err}</div>}{ok&&<div className="tk-alert tk-alert--ok" role="status">{ok}</div>}
  <div className="tk-kpis">{kpis.map(k=><button key={k.label} type="button" className={`tk-kpi${k.on?' is-on':''}`} aria-pressed={k.on} onClick={k.go}><span className={`tk-kpi-i tk-tone--${k.tone}`}><Icon n={k.icon}/></span>
   <span><span className="tk-kpi-l">{k.label}</span><span className="tk-kpi-v">{k.value??'—'}</span><span className="tk-kpi-s">{k.value==null?'Not available':k.sub}</span></span></button>)}</div>

  <section className="tk-card tk-filters" aria-label="Filters">
   <input className="tk-in tk-search" type="search" aria-label="Search tasks" placeholder="Search tasks…" value={q} onChange={e=>{setQ(e.target.value);setPage(1)}}/>
   <select className="tk-in" aria-label="Filter by status" value={status} onChange={e=>{setStatus(e.target.value);setPage(1)}}><option value="">All statuses</option>{(meta.statuses||[]).map((s:string)=><option key={s} value={s}>{lab(s)}</option>)}</select>
   <select className="tk-in" aria-label="Filter by priority" value={priority} onChange={e=>{setPriority(e.target.value);setPage(1)}}><option value="">All priorities</option>{Object.entries(PRIORITY).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select>
   {names.length>0&&<select className="tk-in" aria-label="Filter by assignee" value={assignee} onChange={e=>{setAssignee(e.target.value);setPage(1)}}><option value="">All assignees</option>{names.map(n=><option key={n} value={n}>{n}</option>)}</select>}
   <select className="tk-in" aria-label="Filter by due date" value={due} onChange={e=>{setDue(e.target.value);setPage(1)}}><option value="">Any due date</option>{Object.entries(DUE).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select>
   <label className="tk-toggle"><input type="checkbox" checked={mine} onChange={e=>{setMine(e.target.checked);setPage(1)}}/> Assigned to me</label>
   {filtered&&<button className="tk-btn tk-btn--link" onClick={clear}>Clear filters</button>}</section>

  <section className="tk-card">
   {local&&data.truncated&&<p className="tk-fine">Showing the first {data.items.length} matching tasks. Narrow the search to see the rest.</p>}
   <div className="tk-scroll"><table className="tk-table" aria-label="Tasks"><thead><tr><th>Title</th><th>Assignee</th><th>Priority</th><th>Due</th><th>Status</th><th>Actions</th></tr></thead>
    <tbody>{shown.map(r=><tr key={r.id}><td data-label="Task"><button type="button" className="tk-title" onClick={()=>setPanel({mode:'view',id:r.id,snap:r})}>{r.title}</button>{r.requires_approval&&<small> · needs approval</small>}{r.decision_note&&<small> · note: {r.decision_note}</small>}</td>
     <td data-label="Assignee">{r.assignee_name?<span className="tk-who"><span className="tk-avatar" aria-hidden="true">{initials(r.assignee_name)}</span>{r.assignee_name}</span>:'—'}</td>
     <td data-label="Priority"><Badge tone={PRIORITY_TONE[r.priority]??'grey'}>{PRIORITY[r.priority]??r.priority}</Badge></td><td data-label="Due">{dueCell(r)}</td><td data-label="Status">{statusCell(r)}</td><td data-label="Actions">{actions(r)}</td></tr>)}</tbody></table></div>
   {busy&&<p className="tk-empty">Loading…</p>}{!busy&&!shown.length&&!err&&<p className="tk-empty">{filtered?'No tasks match these filters.':'No tasks found.'}{!filtered&&meta.can_write?' Use "Add task" to create the first one.':''}</p>}
   <div className="tk-pager"><button className="tk-btn tk-btn--line tk-btn--sm" disabled={page<=1} onClick={()=>setPage(page-1)}>Previous</button><span>Page {page} of {pages} · {total} total</span><button className="tk-btn tk-btn--line tk-btn--sm" disabled={page>=pages} onClick={()=>setPage(page+1)}>Next</button></div></section>

  {viewing&&<SidePanel title="Task details" onClose={()=>setPanel(null)}><h4 className="tk-dt">{viewing.title}</h4>
   <div className="tk-chips">{statusCell(viewing)}<Badge tone={PRIORITY_TONE[viewing.priority]??'grey'}>{PRIORITY[viewing.priority]??viewing.priority} priority</Badge></div>
   <dl className="tk-dl"><dt>Assignee</dt><dd>{viewing.assignee_name??'—'}</dd><dt>Due</dt><dd>{dueCell(viewing)}</dd><dt>Approval</dt><dd>{viewing.requires_approval?'Needs approval before it counts as done':'Not required'}</dd>{viewing.decision_note&&<><dt>Approver note</dt><dd>{viewing.decision_note}</dd></>}</dl>
   {viewing.description?<><h5>Description</h5><p className="tk-desc">{viewing.description}</p></>:<p className="tk-fine">No description.</p>}{actions(viewing)}</SidePanel>}
  {form&&<SidePanel title={form.id?'Edit task':'New task'} onClose={()=>setPanel(null)}><form onSubmit={save} className="tk-form" aria-label={`${form.id?'Edit':'Add'} task`}>
   <div><label htmlFor="t_title">Title *</label><input id="t_title" type="text" maxLength={160} required value={form.title??''} onChange={e=>setForm({...form,title:e.target.value})}/></div>
   <div><label htmlFor="t_desc">Description</label><textarea id="t_desc" rows={4} maxLength={4000} value={form.description??''} onChange={e=>setForm({...form,description:e.target.value})}/></div>
   {meta.can_assign&&<div><label htmlFor="t_who">Assign to</label><select id="t_who" value={form.assignee_id??''} onChange={e=>setForm({...form,assignee_id:e.target.value})}><option value="">Me</option>{people.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></div>}
   <div className="tk-form-2"><div><label htmlFor="t_pri">Priority</label><select id="t_pri" value={form.priority??'normal'} onChange={e=>setForm({...form,priority:e.target.value})}>{Object.entries(PRIORITY).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></div>
    <div><label htmlFor="t_due">Due date</label><input id="t_due" type="date" value={form.due_date??''} onChange={e=>setForm({...form,due_date:e.target.value})}/></div></div>
   <label className="tk-check"><input type="checkbox" checked={!!form.requires_approval} onChange={e=>setForm({...form,requires_approval:e.target.checked})}/> Needs approval before it counts as done</label>
   <div className="tk-actions"><button className="tk-btn tk-btn--primary">Save task</button><button type="button" className="tk-btn tk-btn--line" onClick={()=>setPanel(null)}>Cancel</button></div></form></SidePanel>}
 </div>}
