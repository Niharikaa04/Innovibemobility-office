import {useEffect,useState,FormEvent} from 'react'; import {api} from './api'
const Pager=({page,pages,total,set}:{page:number;pages:number;total:number;set:(n:number)=>void})=><div style={{display:'flex',gap:8,alignItems:'center'}}><button className="ghost" disabled={page<=1} onClick={()=>set(page-1)}>Previous</button><span className="note">Page {page} of {pages} · {total} total</span><button className="ghost" disabled={page>=pages} onClick={()=>set(page+1)}>Next</button></div>

export function Employees(){
 const [rows,setRows]=useState<any[]>([]),[meta,setMeta]=useState<any>({departments:[]}),[total,setTotal]=useState(0),[page,setPage]=useState(1),[q,setQ]=useState(''),[dep,setDep]=useState(''),[act,setAct]=useState(''),
  [err,setErr]=useState(''),[ok,setOk]=useState(''),[busy,setBusy]=useState(true),[form,setForm]=useState<any|null>(null),[tick,setTick]=useState(0),size=20,pages=Math.max(1,Math.ceil(total/size))
 useEffect(()=>{setBusy(true);const t=setTimeout(()=>{api.call(`/employees?page=${page}&page_size=${size}&q=${encodeURIComponent(q)}${dep?`&department_id=${dep}`:''}${act?`&active=${act}`:''}`,'GET')
  .then(r=>{setRows(r.items);setTotal(r.total);setMeta(r);setErr('')}).catch(e=>setErr(e.message)).finally(()=>setBusy(false))},q?250:0);return()=>clearTimeout(t)},[page,q,dep,act,tick])
 async function save(e:FormEvent){e.preventDefault();setOk('');setErr('');const b:any={designation:form.designation??'',phone:form.phone??''};if(form.department_id)b.department_id=Number(form.department_id)
  try{await api.call(`/employees/${form.id}`,'PATCH',b);setOk('Employee updated.');setForm(null);setTick(t=>t+1)}catch(x:any){setErr(x.message)}}
 async function toggle(r:any){if(!window.confirm(r.is_active?`Deactivate ${r.full_name}? They will be signed out and cannot log in.`:`Reactivate ${r.full_name}?`))return;setOk('');setErr('')
  try{await api.call(`/employees/${r.id}`,'PATCH',{is_active:!r.is_active});setOk(r.is_active?'Employee deactivated.':'Employee reactivated.')}catch(x:any){setErr(x.message)}setTick(t=>t+1)}
 return <div className="panel" style={{minHeight:0}}><h3>Employees</h3>
  <div style={{display:'flex',gap:8,flexWrap:'wrap',marginBottom:8}}><input className="search" aria-label="Search employees" placeholder="Search name, email, code, designation…" value={q} onChange={e=>{setQ(e.target.value);setPage(1)}}/>
   <select className="search" aria-label="Filter by department" style={{maxWidth:200}} value={dep} onChange={e=>{setDep(e.target.value);setPage(1)}}><option value="">All departments</option>{meta.departments.map((d:any)=><option key={d.id} value={d.id}>{d.name}</option>)}</select>
   <select className="search" aria-label="Filter by status" style={{maxWidth:160}} value={act} onChange={e=>{setAct(e.target.value);setPage(1)}}><option value="">Active & inactive</option><option value="true">Active</option><option value="false">Inactive</option></select></div>
  {err&&<div className="err" role="alert">{err}</div>}{ok&&<div role="status" className="note" style={{color:'var(--green)'}}>{ok}</div>}
  {form&&<form onSubmit={save} className="card" style={{width:'100%',margin:'8px 0',boxShadow:'none',border:'1px solid var(--line)'}} aria-label="Edit employee">
   <p className="note">{form.full_name} · {form.employee_code}</p>
   <div><label htmlFor="e_des">Designation</label><input id="e_des" type="text" maxLength={120} value={form.designation??''} onChange={e=>setForm({...form,designation:e.target.value})}/></div>
   <div><label htmlFor="e_ph">Phone</label><input id="e_ph" type="text" value={form.phone??''} onChange={e=>setForm({...form,phone:e.target.value})}/></div>
   <div><label htmlFor="e_dep">Department</label><select id="e_dep" value={form.department_id??''} onChange={e=>setForm({...form,department_id:e.target.value})}><option value="">Unchanged</option>{meta.departments.map((d:any)=><option key={d.id} value={d.id}>{d.name}</option>)}</select></div>
   <button className="go">Save</button> <button type="button" className="ghost" onClick={()=>setForm(null)}>Cancel</button></form>}
  <div className="tw"><table><thead><tr><th>Code</th><th>Name</th><th>Email</th><th>Department</th><th>Designation</th><th>Status</th>{(meta.can_write||meta.can_admin)&&<th>Actions</th>}</tr></thead>
   <tbody>{rows.map(r=><tr key={r.id}><td>{r.employee_code}</td><td>{r.full_name}{r.is_technician&&<small> · technician</small>}</td><td>{r.email}</td><td>{r.department??''}</td><td>{r.designation??''}</td><td>{r.is_active?'Active':'Inactive'}</td>
    {(meta.can_write||meta.can_admin)&&<td>{meta.can_write&&<button className="ghost" onClick={()=>{setForm({...r,department_id:''});setErr('');setOk('')}}>Edit</button>} {meta.can_admin&&<button className="ghost" onClick={()=>toggle(r)}>{r.is_active?'Deactivate':'Reactivate'}</button>}</td>}</tr>)}</tbody></table>
   {busy&&<p className="note">Loading…</p>}{!busy&&!rows.length&&!err&&<p className="note">No employees found.</p>}</div>
  <Pager page={page} pages={pages} total={total} set={setPage}/></div>}

export function AuditLog(){
 const [rows,setRows]=useState<any[]>([]),[total,setTotal]=useState(0),[page,setPage]=useState(1),[ent,setEnt]=useState(''),[action,setAction]=useState(''),[outcome,setOutcome]=useState(''),[err,setErr]=useState(''),[busy,setBusy]=useState(true),size=50,pages=Math.max(1,Math.ceil(total/size))
 useEffect(()=>{setBusy(true);const t=setTimeout(()=>{api.call(`/audit?page=${page}&page_size=${size}${ent?`&entity_type=${encodeURIComponent(ent)}`:''}${action?`&action=${encodeURIComponent(action)}`:''}${outcome?`&outcome=${outcome}`:''}`,'GET')
  .then(r=>{setRows(r.items);setTotal(r.total);setErr('')}).catch(e=>setErr(e.message)).finally(()=>setBusy(false))},action?250:0);return()=>clearTimeout(t)},[page,ent,action,outcome])
 return <div className="panel" style={{minHeight:0}}><h3>Audit Log</h3><p className="note">Append-only record of business changes (who, what, when, before/after). Sign-in and security events are in the separate server log file.</p>
  <div style={{display:'flex',gap:8,flexWrap:'wrap',marginBottom:8}}><select className="search" aria-label="Filter by record type" style={{maxWidth:180}} value={ent} onChange={e=>{setEnt(e.target.value);setPage(1)}}><option value="">All record types</option><option value="task">Task</option><option value="employee">Employee</option></select>
   <input className="search" aria-label="Filter by action" placeholder="Action contains… (e.g. task.approved)" value={action} onChange={e=>{setAction(e.target.value);setPage(1)}}/>
   <select className="search" aria-label="Filter by outcome" style={{maxWidth:160}} value={outcome} onChange={e=>{setOutcome(e.target.value);setPage(1)}}><option value="">Any outcome</option><option value="success">Success</option><option value="denied">Denied</option><option value="failed">Failed</option></select></div>
  {err&&<div className="err" role="alert">{err}</div>}
  <div className="tw"><table><thead><tr><th>Time</th><th>Actor</th><th>Role</th><th>Action</th><th>Record</th><th>Outcome</th><th>IP</th><th>Changes</th></tr></thead>
   <tbody>{rows.map(r=><tr key={r.id}><td>{new Date(r.occurred_at).toLocaleString()}</td><td>{r.actor_id??'system'}</td><td>{r.actor_role??''}</td><td>{r.action}</td><td>{r.entity_type?`${r.entity_type} ${r.entity_id??''}`:''}</td><td>{r.outcome}</td><td>{r.ip??''}</td>
    <td>{(r.before_data||r.after_data)?<details><summary>View</summary><pre style={{whiteSpace:'pre-wrap',maxWidth:360}}>{JSON.stringify({before:r.before_data,after:r.after_data},null,1)}</pre></details>:''}</td></tr>)}</tbody></table>
   {busy&&<p className="note">Loading…</p>}{!busy&&!rows.length&&!err&&<p className="note">No audit entries match.</p>}</div>
  <Pager page={page} pages={pages} total={total} set={setPage}/></div>}
