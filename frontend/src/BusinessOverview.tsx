import {useState} from 'react'
import RecordsPage,{OPEN_ST,DONE_ST,inStatus,pctOf} from './RecordsPage'
import type {Card,Cfg,Ctx} from './RecordsPage'
import {api} from './api'
import {Box,BarGroup,Donut,Empty,HBars,Line,axis,compact,compactInr,createdIdx,dateIdx,inr,latestMonthly,n,num,text} from './modkit'
import type {ExportOut,Rec} from './modkit'

/* Business Overview: its own records are metric / value / department / owner / period (unchanged schema).
   The "Invoiced vs Expenses" panel is the only cross-module panel. Rule: sum of `amount` on non-cancelled, non-lost records of the
   Revenue & Invoices module (month = "Issued on", else created date) versus the same sum on the Expenses module (month = created date).
   It is NOT a profit figure: no profit, margin or customer/fleet/pipeline numbers are calculated here, because this module has no source for them. */
type Fin={inv:Rec[]|null;exp:Rec[]|null;invErr:string;expErr:string}
const loadFin=async(qs:string):Promise<Fin>=>{const get=(m:string)=>api.call<ExportOut>(`/workspaces/${m}/export${qs}`,'GET')
 const [a,b]=await Promise.allSettled([get('revenue-and-invoices'),get('expenses')])
 return {inv:a.status==='fulfilled'?a.value.items:null,exp:b.status==='fulfilled'?b.value.items:null,invErr:a.status==='rejected'?(a.reason as Error).message:'',expErr:b.status==='rejected'?(b.reason as Error).message:''}}
const OUT=new Set(['Cancelled','Lost'])
const monthly=(recs:Rec[],idx:(r:Rec)=>number|null)=>{const m=new Map<number,number>();for(const r of recs){if(OUT.has(r.status)||r.amount==null)continue;const i=idx(r);if(i!=null)m.set(i,(m.get(i)||0)+Number(r.amount))}return m}
const distinct=(items:Rec[]|null,key:string)=>new Set((items||[]).map(r=>String(r.fields?.[key]??'').trim()).filter(Boolean))

const cards=(c:Ctx):Card[]=>{const s=c.summary,all=c.items;return [
 {clear:true,k:'total',label:'Business records',value:s?String(s.total):'—',sub:all?`${c.createdThisMonth} added this month`:'',ic:'build',c:'green'},
 {filter:{label:'Records with a department',match:r=>String(r.fields?.department??'').trim()!==''},k:'dept',label:'Departments',value:all?String(distinct(all,'department').size):'—',sub:all?'With at least one record':'',ic:'users',c:'teal'},
 {filter:{label:'Records with a metric',match:r=>String(r.fields?.metric??'').trim()!==''},k:'metric',label:'Metrics tracked',value:all?String(distinct(all,'metric').size):'—',sub:all?'Distinct metric names':'',ic:'trend',c:'red'},
 {filter:inStatus('Open / Pending',OPEN_ST),k:'open',label:'Open / Pending',value:s?String(s.open):'—',sub:pctOf(s,s?.open??0),ic:'clip',c:'blue'},
 {filter:inStatus('Completed',DONE_ST),k:'done',label:'Completed',value:s?String(s.completed):'—',sub:pctOf(s,s?.completed??0),ic:'check',c:'purple'}]}

function BusinessCharts({c}:{c:Ctx}){
 const [pick,setPick]=useState('')
 const none=(t:string)=><Empty msg={c.err?`Chart data could not be loaded: ${c.err}`:t}/>
 const all=(c.items||[]).filter(r=>n(r.fields?.value)!=null&&String(r.fields?.metric??'').trim())     // items are newest first
 const metrics=[...new Set(all.map(r=>String(r.fields.metric).trim()))],metric=metrics.includes(pick)?pick:metrics[0]||'',mine=all.filter(r=>String(r.fields.metric).trim()===metric)
 const tr=latestMonthly(mine,['value']),dept=new Map<string,Rec>();for(const r of mine){const d=String(r.fields?.department??'').trim()||'Unassigned';if(!dept.has(d))dept.set(d,r)}
 const fin=c.extra as Fin|null,iM=fin?.inv?monthly(fin.inv,r=>dateIdx(r.fields?.issued_on)??createdIdx(r)):new Map<number,number>(),eM=fin?.exp?monthly(fin.exp,createdIdx):new Map<number,number>()
 const ax=axis([...iM.keys(),...eM.keys()]),note=[fin?.invErr&&`Revenue & Invoices: ${fin.invErr}`,fin?.expErr&&`Expenses: ${fin.expErr}`,c.extraErr].filter(Boolean).join(' · ')
 const picker=metrics.length>1?<label className="sm-sel">Metric<select aria-label="Metric" value={metric} onChange={e=>setPick(e.target.value)}>{metrics.map(m=><option key={m}>{m}</option>)}</select></label>:null
 return <>
  <Box title="Invoiced vs Expenses" ic="bars" legend={[{name:'Invoiced',cls:'b1'},{name:'Expenses',cls:'b2'}]}>
   {ax.months.length?<BarGroup labels={ax.labels} aria="Invoiced amount versus expenses by month" fmt={compactInr} tip={v=>inr(v)} series={[{name:'Invoiced',values:ax.months.map(m=>iM.get(m)??null),cls:'b1'},{name:'Expenses',values:ax.months.map(m=>eM.get(m)??null),cls:'b2'}]}/>:<Empty msg={note?`Not available: ${note}`:'No invoice or expense amounts recorded yet.'}/>}</Box>
  <Box title={`Metric Trend${metric?`: ${metric}`:''}`} ic="trend" actions={picker}>
   {tr.vals.value.some(v=>v!=null)?<Line labels={tr.labels} values={tr.vals.value} cls="c1" aria={`${metric} by month`} fmt={compact} tip={v=>`${metric}: ${num(v)}`}/>:none('Add records with a metric name and a value to see a trend.')}</Box>
  <Box title={`Value by Department${metric?`: ${metric}`:''}`} ic="users">
   {dept.size?<HBars rows={[...dept.entries()].map(([d,r])=>({label:d,value:n(r.fields.value) as number,text:num(n(r.fields.value))})).sort((a,b)=>b.value-a.value).slice(0,8)}/>:none('No department values recorded for a metric yet.')}</Box>
  <Box title="Records by Status" ic="pie">{c.summary&&c.summary.statuses?.length?<Donut aria="Business overview records by status" caption="Total records" data={c.summary.statuses.map(s=>({label:s.status,value:s.count}))}/>:<Empty msg="No records yet."/>}</Box></>}

export const businessCfg:Cfg={module:'business-overview',layout:'quad',loadExtra:loadFin,titleLabel:'Metric / activity name',hide:['amount','due_date'],
 subtitle:'Operations by department: metrics, activity, status mix and invoiced vs expenses.',formTitle:'Add Business Metric / Activity',listTitle:'All Business Overview Records',noun:'Business Overview Record',
 footnote:'Metric panels use the latest value entered per month for the selected metric. Invoiced vs Expenses = amounts on Revenue & Invoices vs Expenses records (cancelled/lost excluded); it is not a profit figure.',
 fields:[{key:'department',label:'Department',placeholder:'Enter department'},{key:'owner',label:'Owner',placeholder:'Enter owner name'},{key:'period',label:'Reporting period',placeholder:'e.g., Oct 2026'},{key:'metric',label:'Metric',placeholder:'Enter metric name'},{key:'value',label:'Value',type:'number',step:'any',placeholder:'Enter value'},{key:'unit',label:'Unit',placeholder:'e.g., units, ₹, %'}],
 columns:[{label:'Department',cell:r=>text(r.fields?.department)},{label:'Metric',cell:r=>text(r.fields?.metric)},{label:'Value',cell:r=>num(n(r.fields?.value))},{label:'Unit',cell:r=>text(r.fields?.unit)},{label:'Reporting period',cell:r=>text(r.fields?.period)},{label:'Owner',cell:r=>text(r.fields?.owner)}],
 cards,charts:c=><BusinessCharts c={c}/>}
export default function BusinessOverview({title}:{title:string}){return <RecordsPage title={title} cfg={businessCfg}/>}
