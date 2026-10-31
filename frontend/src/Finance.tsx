import {useCallback,useEffect,useState} from 'react'; import type {FormEvent} from 'react'
import {Bar,BarChart,CartesianGrid,Legend,ResponsiveContainer,Tooltip,XAxis,YAxis} from 'recharts'
import {api,download} from './api'; import {Empty} from './Charts'; import {Badge,Pager,Stat,fmtDate,fmtTime,pretty,Drawer,Loading,Notices,PageHead} from './opsui'
import './finance.css'
/* Finance: Revenue & Invoices, Payments & Receivables, Expenses, Budget & Forecast. Everything shown comes from /api/finance (real records only).
   Reuses the Operations building blocks (opsui + ops.css) so the pages match the rest of the dashboard. */

const inr=(v:number|string|null|undefined)=>v==null||v===''?'—':new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR'}).format(Number(v))
const localToday=()=>{const d=new Date(),p=(n:number)=>String(n).padStart(2,'0');return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}`}
const addDays=(iso:string,n:number)=>{const d=new Date(+iso.slice(0,4),+iso.slice(5,7)-1,+iso.slice(8,10)+n),p=(x:number)=>String(x).padStart(2,'0');return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}`}
const fmtMonth=(m:string)=>new Date(+m.slice(0,4),+m.slice(5,7)-1,1).toLocaleDateString(undefined,{month:'short',year:'numeric'})
const r2=(n:number)=>Math.round((n+Number.EPSILON)*100)/100
const num=(v:string)=>v===''?null:Number(v)
const sp={display:'flex',justifyContent:'space-between',alignItems:'center',gap:8,flexWrap:'wrap' as const}
const go=(pairs:Record<string,string>)=>{const p=new URLSearchParams();Object.entries(pairs).forEach(([k,v])=>{if(v)p.set(k,v)});return p}
function useAct(reload:()=>Promise<void>|void){
 const [error,setError]=useState(''),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false)
 const act=async(fn:()=>Promise<unknown>,ok:string,after?:()=>Promise<void>|void)=>{setBusy(true);setError('');setNotice('');try{await fn();setNotice(ok);await reload();if(after)await after()}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
 return {error,setError,notice,setNotice,busy,act}}
const exportTo=async(path:string,name:string,setError:(s:string)=>void)=>{setError('');try{await download(path,name)}catch(e){setError((e as Error).message)}}
const Tabs=({tabs,value,set}:{tabs:[string,string][];value:string;set:(v:string)=>void})=><div className="subtabs" role="tablist">{tabs.map(([k,l])=><button key={k} role="tab" aria-selected={value===k} className={value===k?'on':''} onClick={()=>set(k)}>{l}</button>)}</div>

/* ================= Revenue & Invoices ================= */
type Inv={id:string;invoice_number:string;contact_id:string|null;customer_name:string;customer_email:string|null;customer_address:string|null;customer_tax_id:string|null;issue_date:string;due_date:string;tax_percent:number|string;subtotal:number|string;tax_amount:number|string;total_amount:number|string;paid_amount:number|string;balance:number|string;status:string;payment_status:string;notes:string;cancelled_reason?:string|null}
type Item={description:string;quantity:number|string;unit_price:number|string;line_total?:number|string}
type Pay={id:string;amount:number|string;paid_on:string;method:string;reference:string|null;notes:string;voided:boolean;void_reason:string|null}
type InvList={items:Inv[];total:number;statuses:string[];can_write:boolean;can_export:boolean;can_archive:boolean;can_pay:boolean}
type InvSum={by_status:Record<string,{count:number;total:number}>;invoiced:number;received:number;outstanding:number;count:number}
type InvDet={invoice:Inv;items:Item[];payments:Pay[];methods:string[];can_write:boolean;can_export:boolean;can_archive:boolean;can_pay:boolean}
type Cust={id:string;full_name:string;email:string|null;organization:string|null}
const METHODS=['BANK_TRANSFER','UPI','CARD','CASH','CHEQUE','OTHER']
const blankItem=()=>({description:'',quantity:'1',unit_price:''})
const blankInv=()=>({contact_id:'',customer_name:'',customer_email:'',customer_address:'',customer_tax_id:'',issue_date:localToday(),due_date:addDays(localToday(),30),tax_percent:'0',notes:'',items:[blankItem()]})
const blankPay=(bal:number|string)=>({amount:String(Number(bal)),paid_on:localToday(),method:'BANK_TRANSFER',reference:'',notes:''})

function PayForm({invoiceId,balance,methods,busy,onSubmit}:{invoiceId:string;balance:number|string;methods:string[];busy:boolean;onSubmit:(id:string,body:Record<string,unknown>)=>void}){
 const [f,setF]=useState(blankPay(balance))
 const submit=(e:FormEvent)=>{e.preventDefault();onSubmit(invoiceId,{amount:Number(f.amount),paid_on:f.paid_on,method:f.method,reference:f.reference||null,notes:f.notes})}
 return <form className="formgrid" onSubmit={submit} aria-label="Record payment">
  <label>Amount received * <small>(outstanding {inr(balance)})</small><input type="number" required min="0.01" max={Number(balance)} step="0.01" value={f.amount} onChange={e=>setF({...f,amount:e.target.value})}/></label>
  <label>Received on *<input type="date" required max={localToday()} value={f.paid_on} onChange={e=>setF({...f,paid_on:e.target.value})}/></label>
  <label>Method<select value={f.method} onChange={e=>setF({...f,method:e.target.value})}>{methods.map(m=><option key={m} value={m}>{pretty(m)}</option>)}</select></label>
  <label>Reference / UTR<input maxLength={120} value={f.reference} onChange={e=>setF({...f,reference:e.target.value})}/></label>
  <label className="wide">Notes<input maxLength={1000} value={f.notes} onChange={e=>setF({...f,notes:e.target.value})}/></label>
  <div><button className="btn" disabled={busy}>Record payment</button></div></form>}

export function Invoices(){
 const [data,setData]=useState<InvList|null>(null),[sum,setSum]=useState<InvSum|null>(null),[page,setPage]=useState(1)
 const [q,setQ]=useState(''),[appliedQ,setAppliedQ]=useState(''),[ps,setPs]=useState(''),[from,setFrom]=useState(''),[to,setTo]=useState('')
 const [det,setDet]=useState<InvDet|null>(null),[form,setForm]=useState(blankInv()),[editing,setEditing]=useState<Inv|null>(null),[lockedAmounts,setLocked]=useState(false),[showForm,setShowForm]=useState(false)
 const [cq,setCq]=useState(''),[custs,setCusts]=useState<Cust[]>([])
 const params=useCallback((extra:Record<string,string>={})=>go({q:appliedQ,payment_status:ps,date_from:from,date_to:to,...extra}),[appliedQ,ps,from,to])
 const load=useCallback(async()=>{try{const [l,s]=await Promise.all([api.call<InvList>(`/finance/invoices?${params({page:String(page),limit:'25'})}`,'GET'),api.call<InvSum>(`/finance/invoices/summary?${go({date_from:from,date_to:to})}`,'GET')]);setData(l);setSum(s)}catch(e){m.setError((e as Error).message)}},[params,page,from,to])  // eslint-disable-line
 const m=useAct(load)
 useEffect(()=>{void load()},[load])
 useEffect(()=>{if(cq.trim().length<2){setCusts([]);return}const t=setTimeout(()=>{api.call<Cust[]>(`/finance/customers?q=${encodeURIComponent(cq.trim())}`,'GET').then(setCusts).catch(()=>setCusts([]))},250);return()=>clearTimeout(t)},[cq])
 const open=async(id:string)=>{m.setError('');try{setDet(await api.call<InvDet>(`/finance/invoices/${id}`,'GET'))}catch(e){m.setError((e as Error).message)}}
 const refresh=async()=>{if(det)await open(det.invoice.id)}
 const startNew=()=>{setEditing(null);setLocked(false);setForm(blankInv());setCq('');setCusts([]);setShowForm(true)}
 const startEdit=async(id:string)=>{m.setError('');try{const d=await api.call<InvDet>(`/finance/invoices/${id}`,'GET'),i=d.invoice
  setEditing(i);setLocked(Number(i.paid_amount)>0);setCq('');setCusts([]);setForm({contact_id:i.contact_id||'',customer_name:i.customer_name,customer_email:i.customer_email||'',customer_address:i.customer_address||'',customer_tax_id:i.customer_tax_id||'',issue_date:i.issue_date,due_date:i.due_date,tax_percent:String(i.tax_percent),notes:i.notes||'',items:d.items.map(x=>({description:x.description,quantity:String(x.quantity),unit_price:String(x.unit_price)}))});setShowForm(true)}catch(e){m.setError((e as Error).message)}}
 const lines=form.items.map(i=>r2(Number(i.quantity||0)*Number(i.unit_price||0))),sub=r2(lines.reduce((a,b)=>a+b,0)),tax=r2(sub*Number(form.tax_percent||0)/100),total=r2(sub+tax)
 const setItem=(n:number,k:'description'|'quantity'|'unit_price',v:string)=>setForm({...form,items:form.items.map((x,i)=>i===n?{...x,[k]:v}:x)})
 const save=async(e:FormEvent,send:boolean)=>{e.preventDefault()
  if(!editing&&!form.contact_id&&!form.customer_name.trim()){m.setError('Enter a customer name or pick a customer.');return}
  if(!lockedAmounts&&total<=0){m.setError('Invoice total must be greater than zero.');return}
  if(form.due_date<form.issue_date){m.setError('Due date cannot be before the issue date.');return}
  const cust={contact_id:form.contact_id||null,customer_name:form.customer_name.trim(),customer_email:form.customer_email||null,customer_address:form.customer_address,customer_tax_id:form.customer_tax_id||null,due_date:form.due_date,notes:form.notes}
  const money={issue_date:form.issue_date,tax_percent:Number(form.tax_percent||0),items:form.items.map(i=>({description:i.description,quantity:Number(i.quantity),unit_price:Number(i.unit_price)}))}
  await m.act(async()=>{if(editing)await api.call(`/finance/invoices/${editing.id}`,'PATCH',lockedAmounts?cust:{...cust,...money});else await api.call('/finance/invoices','POST',{...cust,...money,send});setShowForm(false)},editing?'Invoice updated.':send?'Invoice created and marked as sent.':'Draft invoice saved.',editing?refresh:undefined)}
 const pdf=(i:Inv)=>exportTo(`/finance/invoices/${i.id}/pdf`,`${i.invoice_number}.pdf`,m.setError)
 const send=(i:Inv)=>m.act(()=>api.call(`/finance/invoices/${i.id}/send`,'POST'),'Invoice marked as sent.',refresh)
 const cancel=(i:Inv)=>{const reason=window.prompt(`Cancel invoice ${i.invoice_number}? Enter a reason:`);if(!reason?.trim())return;void m.act(()=>api.call(`/finance/invoices/${i.id}/cancel`,'POST',{reason}),'Invoice cancelled.',refresh)}
 const archive=(i:Inv)=>{if(!confirm(`Archive invoice ${i.invoice_number}?`))return;void m.act(()=>api.call(`/finance/invoices/${i.id}`,'DELETE'),'Invoice archived.',()=>{if(det?.invoice.id===i.id)setDet(null)})}
 const addPay=(id:string,body:Record<string,unknown>)=>m.act(()=>api.call(`/finance/invoices/${id}/payments`,'POST',body),'Payment recorded.',refresh)
 const voidPay=(p:Pay)=>{const reason=window.prompt('Void this payment? Enter a reason:');if(!reason?.trim())return;void m.act(()=>api.call(`/finance/payments/${p.id}/void`,'POST',{reason}),'Payment voided.',refresh)}
 const pick=(s:string)=>{setPs(ps===s?'':s);setPage(1)}
 const clear=()=>{setQ('');setAppliedQ('');setPs('');setFrom('');setTo('');setPage(1)}
 const by=sum?.by_status||{}
 return <div className="panel ops"><PageHead title="Revenue & Invoices" subtitle="Create invoices for your customers, track what has been paid and download PDFs. Amounts are in INR.">{data?.can_export&&<button className="ghost" onClick={()=>void exportTo(`/finance/invoices/export?${params()}`,'invoices.csv',m.setError)}>Export CSV</button>}{data?.can_write&&<button className="btn" onClick={startNew}>New invoice</button>}</PageHead>
  <Notices error={m.error} notice={m.notice} onRetry={()=>void load()}/>
  {sum&&<div className="cards" aria-label="Invoice summary"><Stat name="Invoiced" value={inr(sum.invoiced)}/><Stat name="Received" value={inr(sum.received)}/><Stat name="Outstanding" value={inr(sum.outstanding)}/>
   <Stat name="Overdue invoices" value={by.OVERDUE?.count||0} on={ps==='OVERDUE'} alert onClick={()=>pick('OVERDUE')}/><Stat name="Partly paid" value={by.PARTIAL?.count||0} on={ps==='PARTIAL'} onClick={()=>pick('PARTIAL')}/><Stat name="Drafts" value={by.DRAFT?.count||0} on={ps==='DRAFT'} onClick={()=>pick('DRAFT')}/></div>}
  <form className="filters" onSubmit={e=>{e.preventDefault();setAppliedQ(q.trim());setPage(1)}}><label>Search<input aria-label="Search invoices" placeholder="Invoice no., customer or email" value={q} onChange={e=>setQ(e.target.value)}/></label>
   <label>Status<select value={ps} onChange={e=>{setPs(e.target.value);setPage(1)}}><option value="">All</option>{(data?.statuses||[]).map(s=><option key={s} value={s}>{pretty(s)}</option>)}</select></label>
   <label>Issued from<input type="date" value={from} max={to||undefined} onChange={e=>{setFrom(e.target.value);setPage(1)}}/></label><label>To<input type="date" value={to} min={from||undefined} onChange={e=>{setTo(e.target.value);setPage(1)}}/></label>
   <button className="btn">Search</button><button type="button" className="ghost" onClick={clear}>Clear filters</button><span className="note">{data?.total??0} invoice(s)</span></form>
  {!data?.items.length?(data?<Empty msg="No invoices match. Create an invoice or change the filters."/>:<Loading/>):<div className="ops-tablewrap"><table><thead><tr><th>Invoice</th><th>Customer</th><th>Issued</th><th>Due</th><th>Total</th><th>Paid</th><th>Balance</th><th>Status</th><th>Actions</th></tr></thead><tbody>
   {data.items.map(i=><tr key={i.id}><td><button className="ghost" onClick={()=>void open(i.id)} aria-label={`Open ${i.invoice_number}`}>{i.invoice_number}</button></td><td>{i.customer_name}</td><td>{fmtDate(i.issue_date)}</td><td>{fmtDate(i.due_date)}</td><td>{inr(i.total_amount)}</td><td>{inr(i.paid_amount)}</td><td>{inr(i.balance)}</td><td><Badge v={i.payment_status}/></td>
    <td><button className="ghost" onClick={()=>void open(i.id)}>View</button> <button className="ghost" onClick={()=>void pdf(i)} aria-label={`Download PDF ${i.invoice_number}`}>PDF</button>{data.can_write&&i.status!=='CANCELLED'&&<> <button className="ghost" onClick={()=>void startEdit(i.id)} aria-label={`Edit ${i.invoice_number}`}>Edit</button></>}{data.can_write&&i.status==='DRAFT'&&<> <button className="ghost" onClick={()=>void send(i)}>Mark sent</button></>}{data.can_archive&&i.status!=='SENT'&&<> <button className="ghost" onClick={()=>void archive(i)} aria-label={`Archive ${i.invoice_number}`}>Archive</button></>}</td></tr>)}</tbody></table></div>}
  <Pager page={page} total={data?.total||0} limit={25} set={setPage}/>
  {showForm&&<Drawer label={editing?'Edit invoice':'New invoice'} wide onClose={()=>setShowForm(false)}><form className="formgrid" onSubmit={e=>void save(e,((e as unknown as {nativeEvent:{submitter?:HTMLElement|null}}).nativeEvent.submitter)?.dataset.send==='1')} aria-label={editing?'Edit invoice':'New invoice'}><h3 className="wide" style={{margin:0}}>{editing?`Edit ${editing.invoice_number}`:'New invoice'}</h3>
   {lockedAmounts&&<p className="note wide">This invoice already has payments, so amounts and the issue date are locked. Void the payments to change them.</p>}
   <label className="wide">Find an existing customer (CRM)<input aria-label="Search customers" placeholder="Type at least 2 letters of a name, company or email" value={cq} onChange={e=>setCq(e.target.value)}/></label>
   {custs.length>0&&<ul className="wide fin-pick">{custs.map(c=><li key={c.id}><button type="button" className="ghost" onClick={()=>{setForm({...form,contact_id:c.id,customer_name:c.full_name,customer_email:c.email||'',customer_address:form.customer_address});setCq('');setCusts([])}}>{c.full_name}{c.organization?` — ${c.organization}`:''}{c.email?` (${c.email})`:''}</button></li>)}</ul>}
   <label>Customer name *<input required maxLength={180} value={form.customer_name} onChange={e=>setForm({...form,customer_name:e.target.value,contact_id:''})}/></label>
   <label>Customer email<input type="email" maxLength={254} value={form.customer_email} onChange={e=>setForm({...form,customer_email:e.target.value})}/></label>
   <label>Tax ID (e.g. GSTIN)<input maxLength={40} value={form.customer_tax_id} onChange={e=>setForm({...form,customer_tax_id:e.target.value})}/></label>
   <label>Address<input maxLength={500} value={form.customer_address} onChange={e=>setForm({...form,customer_address:e.target.value})}/></label>
   <label>Issue date *<input type="date" required disabled={lockedAmounts} value={form.issue_date} onChange={e=>setForm({...form,issue_date:e.target.value})}/></label>
   <label>Due date *<input type="date" required min={form.issue_date} value={form.due_date} onChange={e=>setForm({...form,due_date:e.target.value})}/></label>
   <label>Tax %<input type="number" min="0" max="100" step="0.01" disabled={lockedAmounts} value={form.tax_percent} onChange={e=>setForm({...form,tax_percent:e.target.value})}/></label>
   <div className="wide"><div style={sp}><h3 style={{margin:0}}>Line items</h3>{!lockedAmounts&&<button type="button" className="ghost" disabled={form.items.length>=50} onClick={()=>setForm({...form,items:[...form.items,blankItem()]})}>Add line</button>}</div>
    <div className="ops-tablewrap"><table><thead><tr><th>Description *</th><th>Qty *</th><th>Unit price *</th><th>Amount</th><th/></tr></thead><tbody>{form.items.map((it,n)=><tr key={n}>
     <td><input aria-label={`Item ${n+1} description`} required maxLength={300} disabled={lockedAmounts} value={it.description} onChange={e=>setItem(n,'description',e.target.value)}/></td>
     <td><input aria-label={`Item ${n+1} quantity`} type="number" required min="0.01" step="0.01" disabled={lockedAmounts} value={it.quantity} onChange={e=>setItem(n,'quantity',e.target.value)}/></td>
     <td><input aria-label={`Item ${n+1} unit price`} type="number" required min="0" step="0.01" disabled={lockedAmounts} value={it.unit_price} onChange={e=>setItem(n,'unit_price',e.target.value)}/></td>
     <td>{inr(lines[n])}</td><td>{!lockedAmounts&&form.items.length>1&&<button type="button" className="ghost" aria-label={`Remove item ${n+1}`} onClick={()=>setForm({...form,items:form.items.filter((_,i)=>i!==n)})}>Remove</button>}</td></tr>)}</tbody></table></div>
    <p className="note" style={{textAlign:'right'}}>Subtotal {inr(sub)} · Tax {inr(tax)} · <strong>Total {inr(total)}</strong></p></div>
   <label className="wide">Notes<textarea maxLength={3000} value={form.notes} onChange={e=>setForm({...form,notes:e.target.value})}/></label>
   <div className="wide" style={{display:'flex',gap:8,flexWrap:'wrap'}}><button className="btn" disabled={m.busy}>{editing?'Save changes':'Save as draft'}</button>{!editing&&<button type="submit" data-send="1" className="ghost" disabled={m.busy}>Save & mark as sent</button>}<button type="button" className="ghost" onClick={()=>setShowForm(false)}>Cancel</button></div></form></Drawer>}
  {det&&!showForm&&<Drawer label={`Invoice ${det.invoice.invoice_number}`} wide onClose={()=>setDet(null)}>
   <div style={sp}><h3 style={{margin:0}}>{det.invoice.invoice_number} — {det.invoice.customer_name}</h3><div style={{display:'flex',gap:8,flexWrap:'wrap'}}><button className="ghost" onClick={()=>void pdf(det.invoice)}>Download PDF</button>{det.can_write&&det.invoice.status!=='CANCELLED'&&<button className="ghost" onClick={()=>void startEdit(det.invoice.id)}>Edit</button>}{det.can_write&&det.invoice.status==='DRAFT'&&<button className="btn" disabled={m.busy} onClick={()=>void send(det.invoice)}>Mark as sent</button>}{det.can_write&&det.invoice.status!=='CANCELLED'&&Number(det.invoice.paid_amount)===0&&<button className="ghost" disabled={m.busy} onClick={()=>cancel(det.invoice)}>Cancel invoice</button>}<button className="ghost" onClick={()=>setDet(null)}>Close</button></div></div>
   <dl><div><dt>Status</dt><dd><Badge v={det.invoice.payment_status}/></dd></div><div><dt>Issued</dt><dd>{fmtDate(det.invoice.issue_date)}</dd></div><div><dt>Due</dt><dd>{fmtDate(det.invoice.due_date)}</dd></div><div><dt>Email</dt><dd>{det.invoice.customer_email||'—'}</dd></div><div><dt>Tax ID</dt><dd>{det.invoice.customer_tax_id||'—'}</dd></div><div><dt>Address</dt><dd>{det.invoice.customer_address||'—'}</dd></div>
    <div><dt>Subtotal</dt><dd>{inr(det.invoice.subtotal)}</dd></div><div><dt>Tax ({Number(det.invoice.tax_percent)}%)</dt><dd>{inr(det.invoice.tax_amount)}</dd></div><div><dt>Total</dt><dd>{inr(det.invoice.total_amount)}</dd></div><div><dt>Paid</dt><dd>{inr(det.invoice.paid_amount)}</dd></div><div><dt>Balance</dt><dd>{inr(det.invoice.balance)}</dd></div></dl>
   {det.invoice.cancelled_reason&&<p className="note">Cancelled: {det.invoice.cancelled_reason}</p>}{det.invoice.notes&&<p style={{whiteSpace:'pre-wrap'}}>{det.invoice.notes}</p>}
   <h3>Line items</h3><div className="ops-tablewrap"><table><thead><tr><th>Description</th><th>Qty</th><th>Unit price</th><th>Amount</th></tr></thead><tbody>{det.items.map((x,n)=><tr key={n}><td>{x.description}</td><td>{Number(x.quantity)}</td><td>{inr(x.unit_price)}</td><td>{inr(x.line_total)}</td></tr>)}</tbody></table></div>
   <h3>Payments ({det.payments.filter(p=>!p.voided).length})</h3>
   {det.payments.length?<div className="ops-tablewrap"><table><thead><tr><th>Received</th><th>Amount</th><th>Method</th><th>Reference</th><th>Status</th><th/></tr></thead><tbody>{det.payments.map(p=><tr key={p.id}><td>{fmtDate(p.paid_on)}</td><td>{inr(p.amount)}</td><td>{pretty(p.method)}</td><td>{p.reference||'—'}</td><td>{p.voided?<span title={p.void_reason||''}><Badge v="VOIDED"/></span>:<Badge v="PAID"/>}</td><td>{det.can_pay&&!p.voided&&<button className="ghost" disabled={m.busy} onClick={()=>voidPay(p)}>Void</button>}</td></tr>)}</tbody></table></div>:<p className="note">No payments recorded yet.</p>}
   {det.can_pay&&det.invoice.status==='SENT'&&Number(det.invoice.balance)>0&&<><h3>Record a payment</h3><PayForm key={`${det.invoice.id}-${det.invoice.balance}`} invoiceId={det.invoice.id} balance={det.invoice.balance} methods={det.methods} busy={m.busy} onSubmit={(id,b)=>void addPay(id,b)}/></>}
   {det.invoice.status==='DRAFT'&&<p className="note">Payments can be recorded once the invoice is marked as sent.</p>}
  </Drawer>}
 </div>}

/* ================= Payments & Receivables ================= */
type Recv={billed:number;received:number;outstanding:number;overdue_amount:number;overdue_count:number;partial_count:number;pending_count:number;paid_count:number;received_this_month:number;aging:Record<string,number>;top_debtors:{customer_name:string;outstanding:number;invoices:number}[]}
type RecItem=Inv&{days_overdue:number}
type PayRow={id:string;invoice_id:string;invoice_number:string;customer_name:string;amount:number|string;paid_on:string;method:string;reference:string|null;voided:boolean;void_reason:string|null}
export function Payments(){
 const [tab,setTab]=useState('recv'),[sum,setSum]=useState<Recv|null>(null),[rl,setRl]=useState<{items:RecItem[];total:number;methods:string[];can_write:boolean;can_export:boolean}|null>(null),[pl,setPl]=useState<{items:PayRow[];total:number;methods:string[];can_write:boolean;can_export:boolean}|null>(null)
 const [rp,setRp]=useState(1),[pp,setPp]=useState(1),[q,setQ]=useState(''),[aq,setAq]=useState(''),[st,setSt]=useState(''),[method,setMethod]=useState(''),[from,setFrom]=useState(''),[to,setTo]=useState(''),[voided,setVoided]=useState(false),[payFor,setPayFor]=useState<RecItem|null>(null)
 const load=useCallback(async()=>{try{
   if(tab==='recv'){const [s,l]=await Promise.all([api.call<Recv>('/finance/receivables/summary','GET'),api.call<NonNullable<typeof rl>>(`/finance/receivables?${go({q:aq,payment_status:st,page:String(rp),limit:'25'})}`,'GET')]);setSum(s);setRl(l)}
   else setPl(await api.call<NonNullable<typeof pl>>(`/finance/payments?${go({q:aq,method,date_from:from,date_to:to,include_voided:voided?'true':'',page:String(pp),limit:'25'})}`,'GET'))}catch(e){m.setError((e as Error).message)}},[tab,aq,st,method,from,to,voided,rp,pp])  // eslint-disable-line
 const m=useAct(load)
 useEffect(()=>{void load()},[load])
 const addPay=(id:string,body:Record<string,unknown>)=>m.act(()=>api.call(`/finance/invoices/${id}/payments`,'POST',body),'Payment recorded.',()=>setPayFor(null))
 const voidPay=(p:PayRow)=>{const reason=window.prompt(`Void the ${inr(p.amount)} payment on ${p.invoice_number}? Enter a reason:`);if(!reason?.trim())return;void m.act(()=>api.call(`/finance/payments/${p.id}/void`,'POST',{reason}),'Payment voided.')}
 const clear=()=>{setQ('');setAq('');setSt('');setMethod('');setFrom('');setTo('');setVoided(false);setRp(1);setPp(1)}
 const switchTab=(t:string)=>{clear();setTab(t)}
 return <div className="panel ops"><PageHead title="Payments & Receivables" subtitle="Money received against invoices, what is still owed and what is overdue. Overdue = past the due date with a balance left.">
   {tab==='recv'&&rl?.can_export&&<button className="ghost" onClick={()=>void exportTo(`/finance/receivables/export?${go({q:aq,payment_status:st})}`,'receivables.csv',m.setError)}>Export receivables CSV</button>}
   {tab==='pay'&&pl?.can_export&&<button className="ghost" onClick={()=>void exportTo(`/finance/payments/export?${go({q:aq,method,date_from:from,date_to:to,include_voided:voided?'true':''})}`,'payments.csv',m.setError)}>Export payments CSV</button>}</PageHead>
  <Notices error={m.error} notice={m.notice} onRetry={()=>void load()}/>
  <Tabs tabs={[['recv','Receivables'],['pay','Payments received']]} value={tab} set={switchTab}/>
  {tab==='recv'&&<>
   {sum&&<div className="cards" aria-label="Receivables summary"><Stat name="Total outstanding" value={inr(sum.outstanding)}/><Stat name="Overdue amount" value={inr(sum.overdue_amount)} alert/><Stat name="Overdue invoices" value={sum.overdue_count} on={st==='OVERDUE'} alert onClick={()=>{setSt(st==='OVERDUE'?'':'OVERDUE');setRp(1)}}/><Stat name="Partly paid" value={sum.partial_count} on={st==='PARTIAL'} onClick={()=>{setSt(st==='PARTIAL'?'':'PARTIAL');setRp(1)}}/><Stat name="Pending (not due)" value={sum.pending_count} on={st==='UNPAID'} onClick={()=>{setSt(st==='UNPAID'?'':'UNPAID');setRp(1)}}/><Stat name="Received this month" value={inr(sum.received_this_month)}/></div>}
   {sum&&<div style={{display:'flex',gap:16,flexWrap:'wrap',alignItems:'flex-start'}}>
    <div className="ops-card" style={{flex:'1 1 280px'}}><h3 style={{marginTop:0}}>Overdue ageing</h3><table><thead><tr><th>Days past due</th><th>Outstanding</th></tr></thead><tbody>{Object.entries(sum.aging).map(([k,v])=><tr key={k}><td>{k}</td><td>{inr(v)}</td></tr>)}</tbody></table></div>
    <div className="ops-card" style={{flex:'1 1 280px'}}><h3 style={{marginTop:0}}>Largest balances</h3>{sum.top_debtors.length?<table><thead><tr><th>Customer</th><th>Invoices</th><th>Outstanding</th></tr></thead><tbody>{sum.top_debtors.map(d=><tr key={d.customer_name}><td>{d.customer_name}</td><td>{d.invoices}</td><td>{inr(d.outstanding)}</td></tr>)}</tbody></table>:<p className="note">Nothing outstanding.</p>}</div></div>}
   <form className="filters" onSubmit={e=>{e.preventDefault();setAq(q.trim());setRp(1)}}><label>Search<input aria-label="Search receivables" placeholder="Invoice no., customer or email" value={q} onChange={e=>setQ(e.target.value)}/></label>
    <label>Status<select value={st} onChange={e=>{setSt(e.target.value);setRp(1)}}><option value="">All outstanding</option><option value="OVERDUE">Overdue</option><option value="PARTIAL">Partly paid</option><option value="UNPAID">Pending (not due)</option></select></label><button className="btn">Search</button><button type="button" className="ghost" onClick={clear}>Clear filters</button><span className="note">{rl?.total??0} invoice(s) with a balance</span></form>
   {!rl?.items.length?(rl?<Empty msg="No outstanding invoices match."/>:<Loading/>):<div className="ops-tablewrap"><table><thead><tr><th>Invoice</th><th>Customer</th><th>Due</th><th>Total</th><th>Paid</th><th>Outstanding</th><th>Status</th><th>Days overdue</th><th>Actions</th></tr></thead><tbody>
    {rl.items.map(i=><tr key={i.id}><td>{i.invoice_number}</td><td>{i.customer_name}</td><td>{fmtDate(i.due_date)}</td><td>{inr(i.total_amount)}</td><td>{inr(i.paid_amount)}</td><td>{inr(i.balance)}</td><td><Badge v={i.payment_status}/></td><td>{i.days_overdue||'—'}</td><td>{rl.can_write?<button className="ghost" onClick={()=>setPayFor(i)} aria-label={`Record payment for ${i.invoice_number}`}>Record payment</button>:'—'}</td></tr>)}</tbody></table></div>}
   <Pager page={rp} total={rl?.total||0} limit={25} set={setRp}/></>}
  {tab==='pay'&&<>
   <form className="filters" onSubmit={e=>{e.preventDefault();setAq(q.trim());setPp(1)}}><label>Search<input aria-label="Search payments" placeholder="Invoice, customer or reference" value={q} onChange={e=>setQ(e.target.value)}/></label>
    <label>Method<select value={method} onChange={e=>{setMethod(e.target.value);setPp(1)}}><option value="">All</option>{METHODS.map(x=><option key={x} value={x}>{pretty(x)}</option>)}</select></label>
    <label>Received from<input type="date" value={from} max={to||undefined} onChange={e=>{setFrom(e.target.value);setPp(1)}}/></label><label>To<input type="date" value={to} min={from||undefined} onChange={e=>{setTo(e.target.value);setPp(1)}}/></label>
    <label><input type="checkbox" checked={voided} onChange={e=>{setVoided(e.target.checked);setPp(1)}}/> Show voided</label><button className="btn">Search</button><button type="button" className="ghost" onClick={clear}>Clear filters</button><span className="note">{pl?.total??0} payment(s)</span></form>
   {!pl?.items.length?(pl?<Empty msg="No payments match."/>:<Loading/>):<div className="ops-tablewrap"><table><thead><tr><th>Received</th><th>Invoice</th><th>Customer</th><th>Amount</th><th>Method</th><th>Reference</th><th>Status</th><th>Actions</th></tr></thead><tbody>
    {pl.items.map(p=><tr key={p.id}><td>{fmtDate(p.paid_on)}</td><td>{p.invoice_number}</td><td>{p.customer_name}</td><td>{inr(p.amount)}</td><td>{pretty(p.method)}</td><td>{p.reference||'—'}</td><td>{p.voided?<span title={p.void_reason||''}><Badge v="VOIDED"/></span>:<Badge v="PAID"/>}</td><td>{pl.can_write&&!p.voided?<button className="ghost" disabled={m.busy} onClick={()=>voidPay(p)}>Void</button>:'—'}</td></tr>)}</tbody></table></div>}
   <Pager page={pp} total={pl?.total||0} limit={25} set={setPp}/></>}
  {payFor&&rl&&<Drawer label={`Record payment for ${payFor.invoice_number}`} onClose={()=>setPayFor(null)}><h3 style={{margin:0}}>{payFor.invoice_number} — {payFor.customer_name}</h3><p className="note">Total {inr(payFor.total_amount)} · already paid {inr(payFor.paid_amount)}. A partial amount is fine: the rest stays outstanding.</p><PayForm invoiceId={payFor.id} balance={payFor.balance} methods={rl.methods} busy={m.busy} onSubmit={(id,b)=>void addPay(id,b)}/></Drawer>}
 </div>}

/* ================= Expenses ================= */
type Exp={id:string;expense_number:string;expense_date:string;category:string;vendor:string;description:string;amount:number|string;receipt_number:string|null;receipt_url:string|null;status:string;submitted_by:string;reviewed_by:string|null;reviewed_at:string|null;review_note:string|null}
type ExpList={items:Exp[];total:number;filtered_amount:number;categories:string[];statuses:string[];can_write:boolean;can_approve:boolean;can_export:boolean;can_archive:boolean;me:string}
type ExpSum={by_status:Record<string,{count:number;total:number}>;approved_this_month:number;count:number}
type Rep={count:number;total:number;by_category:{category:string;count:number;total:number;share:number}[];by_vendor:{vendor:string;count:number;total:number}[];by_month:{month:string;count:number;total:number}[]}
const blankExp=()=>({expense_date:localToday(),category:'OTHER',vendor:'',amount:'',receipt_number:'',receipt_url:'',description:''})
export function Expenses(){
 const [tab,setTab]=useState('list'),[data,setData]=useState<ExpList|null>(null),[sum,setSum]=useState<ExpSum|null>(null),[page,setPage]=useState(1)
 const [q,setQ]=useState(''),[aq,setAq]=useState(''),[st,setSt]=useState(''),[cat,setCat]=useState(''),[vendor,setVendor]=useState(''),[from,setFrom]=useState(''),[to,setTo]=useState('')
 const [form,setForm]=useState(blankExp()),[editing,setEditing]=useState<Exp|null>(null),[showForm,setShowForm]=useState(false),[view,setView]=useState<Exp|null>(null)
 const [rep,setRep]=useState<Rep|null>(null),[rst,setRst]=useState('APPROVED'),[rfrom,setRfrom]=useState(''),[rto,setRto]=useState('')
 const params=useCallback((extra:Record<string,string>={})=>go({q:aq,status:st,category:cat,vendor:vendor.trim(),date_from:from,date_to:to,...extra}),[aq,st,cat,vendor,from,to])
 const load=useCallback(async()=>{try{
   if(tab==='list'){const [l,s]=await Promise.all([api.call<ExpList>(`/finance/expenses?${params({page:String(page),limit:'25'})}`,'GET'),api.call<ExpSum>('/finance/expenses/summary','GET')]);setData(l);setSum(s)}
   else setRep(await api.call<Rep>(`/finance/expenses/report?${go({status:rst,date_from:rfrom,date_to:rto})}`,'GET'))}catch(e){m.setError((e as Error).message)}},[tab,params,page,rst,rfrom,rto])  // eslint-disable-line
 const m=useAct(load)
 useEffect(()=>{void load()},[load])
 useEffect(()=>{if(tab==='report'&&!data)api.call<ExpList>('/finance/expenses?limit=1','GET').then(setData).catch(()=>undefined)},[tab,data])
 const startNew=()=>{setEditing(null);setForm(blankExp());setShowForm(true)}
 const startEdit=(x:Exp)=>{setView(null);setEditing(x);setForm({expense_date:x.expense_date,category:x.category,vendor:x.vendor,amount:String(x.amount),receipt_number:x.receipt_number||'',receipt_url:x.receipt_url||'',description:x.description||''});setShowForm(true)}
 const save=async(e:FormEvent)=>{e.preventDefault();const body={expense_date:form.expense_date,category:form.category,vendor:form.vendor.trim(),amount:num(form.amount),receipt_number:form.receipt_number||null,receipt_url:form.receipt_url||null,description:form.description}
  await m.act(async()=>{if(editing)await api.call(`/finance/expenses/${editing.id}`,'PATCH',body);else await api.call('/finance/expenses','POST',body);setShowForm(false);setEditing(null)},editing?(editing.status==='REJECTED'?'Expense updated and sent for review again.':'Expense updated.'):'Expense added and waiting for approval.')}
 const approve=(x:Exp)=>m.act(()=>api.call(`/finance/expenses/${x.id}/approve`,'POST',{note:''}),'Expense approved.',()=>setView(null))
 const reject=(x:Exp)=>{const note=window.prompt(`Reject ${x.expense_number}? Enter the reason:`);if(!note?.trim())return;void m.act(()=>api.call(`/finance/expenses/${x.id}/reject`,'POST',{note}),'Expense rejected.',()=>setView(null))}
 const archive=(x:Exp)=>{if(!confirm(`Archive expense ${x.expense_number}?`))return;void m.act(()=>api.call(`/finance/expenses/${x.id}`,'DELETE'),'Expense archived.',()=>setView(null))}
 const clear=()=>{setQ('');setAq('');setSt('');setCat('');setVendor('');setFrom('');setTo('');setPage(1)}
 const by=sum?.by_status||{},cats=data?.categories||[]
 const actions=(x:Exp)=><>{data?.can_approve&&x.status==='PENDING'&&x.submitted_by!==data.me&&<> <button className="ghost" disabled={m.busy} onClick={()=>void approve(x)} aria-label={`Approve ${x.expense_number}`}>Approve</button> <button className="ghost" disabled={m.busy} onClick={()=>reject(x)} aria-label={`Reject ${x.expense_number}`}>Reject</button></>}{data?.can_write&&x.status!=='APPROVED'&&<> <button className="ghost" onClick={()=>startEdit(x)} aria-label={`Edit ${x.expense_number}`}>Edit</button></>}{data?.can_archive&&x.status!=='APPROVED'&&<> <button className="ghost" onClick={()=>archive(x)} aria-label={`Archive ${x.expense_number}`}>Archive</button></>}</>
 return <div className="panel ops"><PageHead title="Expenses" subtitle="Record spending, attach a receipt number or link, and route it for approval. Only approved expenses count in reports and budgets.">
   {tab==='list'&&data?.can_export&&<button className="ghost" onClick={()=>void exportTo(`/finance/expenses/export?${params()}`,'expenses.csv',m.setError)}>Export CSV</button>}
   {tab==='report'&&data?.can_export&&<button className="ghost" onClick={()=>void exportTo(`/finance/expenses/report/export?${go({status:rst,date_from:rfrom,date_to:rto})}`,'expense-report.csv',m.setError)}>Export report CSV</button>}
   {data?.can_write&&<button className="btn" onClick={startNew}>Add expense</button>}</PageHead>
  <Notices error={m.error} notice={m.notice} onRetry={()=>void load()}/>
  <Tabs tabs={[['list','Expenses'],['report','Expense report']]} value={tab} set={setTab}/>
  {tab==='list'&&<>
   {sum&&<div className="cards" aria-label="Expense summary"><Stat name="Waiting for approval" value={by.PENDING?.count||0} on={st==='PENDING'} onClick={()=>{setSt(st==='PENDING'?'':'PENDING');setPage(1)}}/><Stat name="Pending amount" value={inr(by.PENDING?.total||0)}/><Stat name="Approved" value={by.APPROVED?.count||0} on={st==='APPROVED'} onClick={()=>{setSt(st==='APPROVED'?'':'APPROVED');setPage(1)}}/><Stat name="Approved this month" value={inr(sum.approved_this_month)}/><Stat name="Rejected" value={by.REJECTED?.count||0} on={st==='REJECTED'} onClick={()=>{setSt(st==='REJECTED'?'':'REJECTED');setPage(1)}}/></div>}
   <form className="filters" onSubmit={e=>{e.preventDefault();setAq(q.trim());setPage(1)}}><label>Search<input aria-label="Search expenses" placeholder="Expense no., vendor, receipt or description" value={q} onChange={e=>setQ(e.target.value)}/></label>
    <label>Category<select value={cat} onChange={e=>{setCat(e.target.value);setPage(1)}}><option value="">All</option>{cats.map(c=><option key={c} value={c}>{pretty(c)}</option>)}</select></label>
    <label>Status<select value={st} onChange={e=>{setSt(e.target.value);setPage(1)}}><option value="">All</option>{(data?.statuses||[]).map(s=><option key={s} value={s}>{pretty(s)}</option>)}</select></label>
    <label>Vendor<input value={vendor} onChange={e=>{setVendor(e.target.value);setPage(1)}}/></label><label>From<input type="date" value={from} max={to||undefined} onChange={e=>{setFrom(e.target.value);setPage(1)}}/></label><label>To<input type="date" value={to} min={from||undefined} onChange={e=>{setTo(e.target.value);setPage(1)}}/></label>
    <button className="btn">Search</button><button type="button" className="ghost" onClick={clear}>Clear filters</button><span className="note">{data?.total??0} expense(s) · {inr(data?.filtered_amount??0)}</span></form>
   {!data?.items.length?(data?<Empty msg="No expenses match. Add an expense or change the filters."/>:<Loading/>):<div className="ops-tablewrap"><table><thead><tr><th>Expense</th><th>Date</th><th>Category</th><th>Vendor</th><th>Amount</th><th>Receipt</th><th>Status</th><th>Actions</th></tr></thead><tbody>
    {data.items.map(x=><tr key={x.id}><td><button className="ghost" onClick={()=>setView(x)} aria-label={`Open ${x.expense_number}`}>{x.expense_number}</button></td><td>{fmtDate(x.expense_date)}</td><td>{pretty(x.category)}</td><td>{x.vendor}</td><td>{inr(x.amount)}</td>
     <td>{x.receipt_url?<a href={x.receipt_url} target="_blank" rel="noopener noreferrer">{x.receipt_number||'Open receipt'}</a>:(x.receipt_number||'—')}</td><td><Badge v={x.status}/></td><td>{actions(x)}</td></tr>)}</tbody></table></div>}
   <Pager page={page} total={data?.total||0} limit={25} set={setPage}/></>}
  {tab==='report'&&<>
   <form className="filters" onSubmit={e=>e.preventDefault()}><label>Status<select value={rst} onChange={e=>setRst(e.target.value)}>{['APPROVED','PENDING','REJECTED'].map(s=><option key={s} value={s}>{pretty(s)}</option>)}</select></label><label>From<input type="date" value={rfrom} max={rto||undefined} onChange={e=>setRfrom(e.target.value)}/></label><label>To<input type="date" value={rto} min={rfrom||undefined} onChange={e=>setRto(e.target.value)}/></label><button type="button" className="ghost" onClick={()=>{setRst('APPROVED');setRfrom('');setRto('')}}>Reset</button></form>
   {!rep?<Loading/>:<>
    <div className="cards"><Stat name={`${pretty(rst)} expenses`} value={rep.count}/><Stat name="Total amount" value={inr(rep.total)}/></div>
    {!rep.count?<Empty msg="No expenses match this report."/>:<div style={{display:'flex',gap:16,flexWrap:'wrap',alignItems:'flex-start'}}>
     <div className="ops-card" style={{flex:'1 1 320px'}}><h3 style={{marginTop:0}}>By category</h3><table><thead><tr><th>Category</th><th>Count</th><th>Total</th><th>Share</th></tr></thead><tbody>{rep.by_category.map(c=><tr key={c.category}><td>{pretty(c.category)}</td><td>{c.count}</td><td>{inr(c.total)}</td><td>{c.share}%</td></tr>)}</tbody></table></div>
     <div className="ops-card" style={{flex:'1 1 320px'}}><h3 style={{marginTop:0}}>Top vendors</h3><table><thead><tr><th>Vendor</th><th>Count</th><th>Total</th></tr></thead><tbody>{rep.by_vendor.map(v=><tr key={v.vendor}><td>{v.vendor}</td><td>{v.count}</td><td>{inr(v.total)}</td></tr>)}</tbody></table></div>
     <div className="ops-card" style={{flex:'1 1 320px'}}><h3 style={{marginTop:0}}>By month</h3><table><thead><tr><th>Month</th><th>Count</th><th>Total</th></tr></thead><tbody>{rep.by_month.map(v=><tr key={v.month}><td>{fmtMonth(v.month)}</td><td>{v.count}</td><td>{inr(v.total)}</td></tr>)}</tbody></table></div></div>}</>}</>}
  {showForm&&<Drawer label={editing?'Edit expense':'Add expense'} wide onClose={()=>{setShowForm(false);setEditing(null)}}><form className="formgrid" onSubmit={save} aria-label={editing?'Edit expense':'Add expense'}><h3 className="wide" style={{margin:0}}>{editing?`Edit ${editing.expense_number}`:'Add expense'}</h3>
   {editing?.status==='REJECTED'&&<p className="note wide">Rejected: {editing.review_note}. Saving sends it back for approval.</p>}
   <label>Date *<input type="date" required max={localToday()} value={form.expense_date} onChange={e=>setForm({...form,expense_date:e.target.value})}/></label>
   <label>Category *<select value={form.category} onChange={e=>setForm({...form,category:e.target.value})}>{cats.map(c=><option key={c} value={c}>{pretty(c)}</option>)}</select></label>
   <label>Vendor *<input required maxLength={180} value={form.vendor} onChange={e=>setForm({...form,vendor:e.target.value})}/></label>
   <label>Amount (INR) *<input type="number" required min="0.01" step="0.01" value={form.amount} onChange={e=>setForm({...form,amount:e.target.value})}/></label>
   <label>Receipt number<input maxLength={80} value={form.receipt_number} onChange={e=>setForm({...form,receipt_number:e.target.value})}/></label>
   <label>Receipt link<input type="url" maxLength={500} placeholder="https://…" value={form.receipt_url} onChange={e=>setForm({...form,receipt_url:e.target.value})}/></label>
   <label className="wide">Description<textarea maxLength={2000} value={form.description} onChange={e=>setForm({...form,description:e.target.value})}/></label>
   <div className="wide" style={{display:'flex',gap:8}}><button className="btn" disabled={m.busy}>{editing?'Save changes':'Add expense'}</button><button type="button" className="ghost" onClick={()=>{setShowForm(false);setEditing(null)}}>Cancel</button></div></form></Drawer>}
  {view&&<Drawer label={`Expense ${view.expense_number}`} onClose={()=>setView(null)}><div style={sp}><h3 style={{margin:0}}>{view.expense_number} — {view.vendor}</h3><div style={{display:'flex',gap:8}}>{actions(view)}<button className="ghost" onClick={()=>setView(null)}>Close</button></div></div>
   <dl><div><dt>Status</dt><dd><Badge v={view.status}/></dd></div><div><dt>Date</dt><dd>{fmtDate(view.expense_date)}</dd></div><div><dt>Category</dt><dd>{pretty(view.category)}</dd></div><div><dt>Amount</dt><dd>{inr(view.amount)}</dd></div><div><dt>Receipt number</dt><dd>{view.receipt_number||'—'}</dd></div>
    <div><dt>Receipt link</dt><dd>{view.receipt_url?<a href={view.receipt_url} target="_blank" rel="noopener noreferrer">Open receipt</a>:'—'}</dd></div>{view.reviewed_at&&<div><dt>Reviewed</dt><dd>{fmtTime(view.reviewed_at)}</dd></div>}</dl>
   {view.description&&<p style={{whiteSpace:'pre-wrap'}}>{view.description}</p>}{view.review_note&&<p className="note">Review note: {view.review_note}</p>}
   {data?.can_approve&&view.status==='PENDING'&&view.submitted_by===data.me&&<p className="note">You submitted this expense, so another approver must review it.</p>}</Drawer>}
 </div>}

/* ================= Budget & Forecast ================= */
type Cmp={year:number;months:{month:string;budget_revenue:number|null;actual_revenue:number;budget_expenses:number|null;actual_expenses:number;future:boolean}[];categories:{category:string;budget:number|null;actual:number}[];totals:{budget_revenue:number|null;actual_revenue:number;budget_expenses:number|null;actual_expenses:number};basis:string;can_write:boolean;can_export:boolean
 forecast:{available:boolean;reason?:string;method?:string;history_months:number;required_months:number;items?:{month:string;revenue:number;expenses:number;net:number}[]}}
type Line={id:string;kind:string;category:string;month:string;amount:number|string;notes:string}
const variance=(actual:number,budget:number|null,good:'over'|'under')=>{if(budget==null)return <span className="note">No budget</span>;const d=r2(actual-budget),bad=good==='over'?d<0:d>0;return <span style={{color:d===0?undefined:bad?'#b91c1c':'#047857',fontWeight:600}}>{d>0?'+':''}{inr(d)}</span>}
export function Budget(){
 const thisYear=new Date().getFullYear(),[year,setYear]=useState(thisYear),[cmp,setCmp]=useState<Cmp|null>(null),[lines,setLines]=useState<Line[]>([]),[cats,setCats]=useState<string[]>([])
 const [f,setF]=useState({kind:'REVENUE',category:'TRAVEL',month:`${thisYear}-${String(new Date().getMonth()+1).padStart(2,'0')}`,amount:'',notes:''}),[showForm,setShowForm]=useState(false)
 const load=useCallback(async()=>{try{const [c,l]=await Promise.all([api.call<Cmp>(`/finance/budget/compare?year=${year}`,'GET'),api.call<{items:Line[];categories:string[]}>(`/finance/budgets?year=${year}`,'GET')]);setCmp(c);setLines(l.items);setCats(l.categories)}catch(e){m.setError((e as Error).message)}},[year])  // eslint-disable-line
 const m=useAct(load)
 useEffect(()=>{void load()},[load])
 const edit=(l:Line)=>{setF({kind:l.kind,category:l.kind==='EXPENSE'?l.category:'TRAVEL',month:l.month,amount:String(l.amount),notes:l.notes||''});setShowForm(true)}
 const save=async(e:FormEvent)=>{e.preventDefault();await m.act(async()=>{await api.call('/finance/budgets','PUT',{kind:f.kind,category:f.kind==='EXPENSE'?f.category:'REVENUE',month:f.month,amount:num(f.amount),notes:f.notes});setShowForm(false)},'Budget saved.')}
 const del=(l:Line)=>{if(!confirm(`Delete the ${pretty(l.kind)} budget for ${fmtMonth(l.month)}${l.kind==='EXPENSE'?` (${pretty(l.category)})`:''}?`))return;void m.act(()=>api.call(`/finance/budgets/${l.id}`,'DELETE'),'Budget line deleted.')}
 const t=cmp?.totals,fc=cmp?.forecast
 const chart=(cmp?.months||[]).map(x=>({name:fmtMonth(x.month).split(' ')[0],'Budget revenue':x.budget_revenue,'Actual revenue':x.actual_revenue,'Budget expenses':x.budget_expenses,'Actual expenses':x.actual_expenses}))
 return <div className="panel ops"><PageHead title="Budget & Forecast" subtitle="Plan monthly revenue and expense budgets and compare them with what actually happened. Forecasts appear only when there is enough history.">
   {cmp?.can_export&&<button className="ghost" onClick={()=>void exportTo(`/finance/budget/export?year=${year}`,`budget-vs-actual-${year}.csv`,m.setError)}>Export CSV</button>}{cmp?.can_write&&<button className="btn" onClick={()=>setShowForm(true)}>Set budget</button>}</PageHead>
  <Notices error={m.error} notice={m.notice} onRetry={()=>void load()}/>
  <div className="filters"><label>Year<input type="number" min="2000" max="2100" value={year} onChange={e=>{const v=Number(e.target.value);if(v>=2000&&v<=2100)setYear(v)}}/></label><button className="ghost" onClick={()=>setYear(year-1)}>Previous year</button><button className="ghost" onClick={()=>setYear(year+1)}>Next year</button></div>
  {!cmp||!t?<Loading/>:<>
   <div className="cards" aria-label="Budget summary"><Stat name="Budgeted revenue" value={t.budget_revenue==null?'—':inr(t.budget_revenue)}/><Stat name="Actual revenue" value={inr(t.actual_revenue)}/><Stat name="Budgeted expenses" value={t.budget_expenses==null?'—':inr(t.budget_expenses)}/><Stat name="Actual expenses" value={inr(t.actual_expenses)}/><Stat name="Actual net" value={inr(r2(t.actual_revenue-t.actual_expenses))}/></div>
   <p className="note">{cmp.basis} Months without a budget show “No budget” rather than zero.</p>
   {chart.some(c=>c['Actual revenue']||c['Actual expenses']||c['Budget revenue']||c['Budget expenses'])&&<div className="chartbox" style={{height:300}}><ResponsiveContainer width="100%" height="100%"><BarChart data={chart} margin={{top:8,right:8,left:8,bottom:0}}><CartesianGrid strokeDasharray="3 3" vertical={false}/><XAxis dataKey="name"/><YAxis tickFormatter={(v:number)=>v>=100000?`${r2(v/100000)}L`:v>=1000?`${r2(v/1000)}k`:String(v)}/><Tooltip formatter={(v:unknown)=>inr(v as number)}/><Legend/>
     <Bar dataKey="Budget revenue" fill="#93c5fd"/><Bar dataKey="Actual revenue" fill="#1d4ed8"/><Bar dataKey="Budget expenses" fill="#fcd34d"/><Bar dataKey="Actual expenses" fill="#b45309"/></BarChart></ResponsiveContainer></div>}
   <h3>Monthly budget vs actual</h3>
   <div className="ops-tablewrap"><table><thead><tr><th>Month</th><th>Revenue budget</th><th>Revenue actual</th><th>Revenue variance</th><th>Expense budget</th><th>Expense actual</th><th>Expense variance</th></tr></thead><tbody>
    {cmp.months.map(x=><tr key={x.month}><td>{fmtMonth(x.month)}{x.future&&<span className="note"> (upcoming)</span>}</td><td>{inr(x.budget_revenue)}</td><td>{inr(x.actual_revenue)}</td><td>{x.future&&!x.actual_revenue?'—':variance(x.actual_revenue,x.budget_revenue,'over')}</td><td>{inr(x.budget_expenses)}</td><td>{inr(x.actual_expenses)}</td><td>{x.future&&!x.actual_expenses?'—':variance(x.actual_expenses,x.budget_expenses,'under')}</td></tr>)}</tbody></table></div>
   {cmp.categories.length>0&&<><h3>Expenses by category ({cmp.year})</h3><div className="ops-tablewrap"><table><thead><tr><th>Category</th><th>Budget</th><th>Actual</th><th>Variance</th></tr></thead><tbody>{cmp.categories.map(c=><tr key={c.category}><td>{pretty(c.category)}</td><td>{inr(c.budget)}</td><td>{inr(c.actual)}</td><td>{variance(c.actual,c.budget,'under')}</td></tr>)}</tbody></table></div></>}
   <h3>Forecast</h3>
   {fc?.available&&fc.items?<><p className="note">{fc.method}. Based on {fc.history_months} month(s) with activity. This is a simple average, not a prediction of seasonal changes.</p><div className="ops-tablewrap"><table><thead><tr><th>Month</th><th>Expected revenue</th><th>Expected expenses</th><th>Expected net</th></tr></thead><tbody>{fc.items.map(x=><tr key={x.month}><td>{fmtMonth(x.month)}</td><td>{inr(x.revenue)}</td><td>{inr(x.expenses)}</td><td>{inr(x.net)}</td></tr>)}</tbody></table></div></>
    :<div className="notconf">{fc?.reason||'Not enough history yet.'} ({fc?.history_months??0} of {fc?.required_months??3} months)</div>}
   <h3>Budget lines for {year} ({lines.length})</h3>
   {lines.length?<div className="ops-tablewrap"><table><thead><tr><th>Month</th><th>Type</th><th>Category</th><th>Amount</th><th>Notes</th><th>Actions</th></tr></thead><tbody>{lines.map(l=><tr key={l.id}><td>{fmtMonth(l.month)}</td><td>{pretty(l.kind)}</td><td>{l.kind==='EXPENSE'?pretty(l.category):'—'}</td><td>{inr(l.amount)}</td><td>{l.notes||'—'}</td><td>{cmp.can_write?<><button className="ghost" onClick={()=>edit(l)}>Edit</button> <button className="ghost" onClick={()=>del(l)}>Delete</button></>:'—'}</td></tr>)}</tbody></table></div>:<Empty msg={`No budgets set for ${year}.${cmp.can_write?' Use “Set budget” to add one.':''}`}/>}</>}
  {showForm&&<Drawer label="Set budget" onClose={()=>setShowForm(false)}><form className="formgrid" onSubmit={save} aria-label="Set budget"><h3 className="wide" style={{margin:0}}>Set budget</h3><p className="note wide">Saving a month that already has a budget for the same type and category replaces its amount.</p>
   <label>Type *<select value={f.kind} onChange={e=>setF({...f,kind:e.target.value})}><option value="REVENUE">Revenue</option><option value="EXPENSE">Expense</option></select></label>
   {f.kind==='EXPENSE'&&<label>Category *<select value={f.category} onChange={e=>setF({...f,category:e.target.value})}>{cats.map(c=><option key={c} value={c}>{pretty(c)}</option>)}</select></label>}
   <label>Month *<input type="month" required value={f.month} onChange={e=>setF({...f,month:e.target.value})}/></label>
   <label>Amount (INR) *<input type="number" required min="0" step="0.01" value={f.amount} onChange={e=>setF({...f,amount:e.target.value})}/></label>
   <label className="wide">Notes<input maxLength={500} value={f.notes} onChange={e=>setF({...f,notes:e.target.value})}/></label>
   <div className="wide" style={{display:'flex',gap:8}}><button className="btn" disabled={m.busy}>Save budget</button><button type="button" className="ghost" onClick={()=>setShowForm(false)}>Cancel</button></div></form></Drawer>}
 </div>}
