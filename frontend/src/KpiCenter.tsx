import {useState} from 'react'
import RecordsPage from './RecordsPage'
import type {Card,Cfg,Ctx} from './RecordsPage'
import {Box,BarGroup,Empty,HBars,Line,axis,compact,inr,monthIdx,n,num,oldest,text} from './modkit'
import type {Rec} from './modkit'

/* KPI Center: fields target / actual / unit / owner / period / verified source (unchanged schema).
   Calculation rules (shown under the charts): Completion = actual ÷ target × 100 for records that have a target above 0 and an actual value.
   Because KPIs use different units, "Performance Trend" and "Target vs Actual" only ever compare ONE unit at a time (chosen in the selector). */
const unitOf=(r:Rec)=>String(r.fields?.unit??'').trim()||'No unit'
const completion=(r:Rec)=>{const t=n(r.fields?.target),a=n(r.fields?.actual);return t!=null&&t>0&&a!=null?a/t*100:null}
/* Performance status (calculated, never stored): Achieved = achievement ≥ 100%; On track = 80% to under 100%; At risk = under 80%.
   Records without a target above 0 and a numeric actual are "Not measurable" and are excluded from every percentage. Assumes higher actual is better. */
type Perf='Achieved'|'On track'|'At risk'
const perf=(r:Rec):Perf|null=>{const p=completion(r);return p==null?null:p>=100?'Achieved':p>=80?'On track':'At risk'}
const PERF_TONE={'Achieved':'green','On track':'blue','At risk':'red'} as const
const is=(p:Perf)=>({label:p,match:(r:Rec)=>perf(r)===p})
const cards=(c:Ctx):Card[]=>{const s=c.summary,all=c.items,cnt=(p:Perf)=>all?String(all.filter(r=>perf(r)===p).length):'—',ms=(all||[]).map(completion).filter((v):v is number=>v!=null),avg=ms.length?ms.reduce((a,v)=>a+v,0)/ms.length:null
 const un=all?all.filter(r=>perf(r)==null).length:0,of=(p:Perf)=>all&&ms.length?`${Math.round(all.filter(r=>perf(r)===p).length/ms.length*100)}% of measurable KPIs`:all?'No measurable KPIs yet':''
 return [
 {clear:true,k:'total',label:'Total KPIs',value:s?String(s.total):'—',sub:all?`${un} not measurable (no valid target/actual)`:'',ic:'target',c:'blue'},
 {filter:is('On track'),k:'on',label:'On track',value:cnt('On track'),sub:of('On track'),ic:'trend',c:'teal'},
 {filter:is('At risk'),k:'risk',label:'At risk',value:cnt('At risk'),sub:of('At risk'),ic:'alert',c:'red'},
 {filter:is('Achieved'),k:'ach',label:'Achieved',value:cnt('Achieved'),sub:of('Achieved'),ic:'check',c:'green'},
 {filter:{label:'Measurable KPIs',match:r=>perf(r)!=null},k:'avg',label:'Avg achievement',value:avg==null?'—':`${num(Math.round(avg*10)/10)}%`,sub:all?`Across ${ms.length} measurable KPI(s)`:'',ic:'percent',c:'purple'}]}

function KpiCharts({c}:{c:Ctx}){
 const [pick,setPick]=useState('')
 const all=(c.items||[]).filter(r=>n(r.fields?.target)!=null||n(r.fields?.actual)!=null)
 const counts=new Map<string,number>();all.forEach(r=>counts.set(unitOf(r),(counts.get(unitOf(r))||0)+1))
 const units=[...counts.entries()].sort((a,b)=>b[1]-a[1]).map(x=>x[0]),unit=units.includes(pick)?pick:units[0]||'',mine=all.filter(r=>unitOf(r)===unit)
 const none=(t:string)=><Empty msg={c.err?`Chart data could not be loaded: ${c.err}`:t}/>
 // Performance trend: mean target and mean actual per month, for the selected unit
 const by=new Map<number,{t:number[];a:number[]}>();for(const r of mine){const i=monthIdx(r);if(i==null)continue;const e=by.get(i)||{t:[],a:[]};const t=n(r.fields?.target),a=n(r.fields?.actual);if(t!=null)e.t.push(t);if(a!=null)e.a.push(a);by.set(i,e)}
 const mean=(x:number[])=>x.length?x.reduce((s,v)=>s+v,0)/x.length:null
 const ax=axis([...by.keys()]),tgt=ax.months.map(m=>mean(by.get(m)?.t||[])),act=ax.months.map(m=>mean(by.get(m)?.a||[]))
 // Completion rate: mean of per-record completion % per month (unit independent)
 const cb=new Map<number,number[]>();for(const r of all){const v=completion(r),i=monthIdx(r);if(v!=null&&i!=null){const e=cb.get(i)||[];e.push(v);cb.set(i,e)}}
 const cx=axis([...cb.keys()]),comp=cx.months.map(m=>mean(cb.get(m)||[]))
 // Target vs actual per KPI record: latest 8 in this unit
 const recent=oldest(mine).slice(-8),short=(s:string)=>s.length>11?s.slice(0,10)+'…':s
 const pickUi=units.length>1?<label className="sm-sel">Unit<select aria-label="Chart unit" value={unit} onChange={e=>setPick(e.target.value)}>{units.map(u=><option key={u}>{u}</option>)}</select></label>:null
 const dep=new Map<string,number[]>();for(const r of c.items||[]){const v=completion(r);if(v==null)continue;const d=String(r.fields?.department??'').trim()||'Unassigned';dep.set(d,[...(dep.get(d)||[]),v])}
 return <>
  <Box title="KPI Performance Trend" ic="bars" wide actions={pickUi} legend={[{name:'Actual',cls:'b1'},{name:'Target',cls:'b3'}]}>
   {tgt.some(v=>v!=null)||act.some(v=>v!=null)?<BarGroup labels={ax.labels} aria={`Average actual versus target by month (${unit})`} fmt={compact} tip={v=>`${num(v)} ${unit==='No unit'?'':unit}`} series={[{name:'Actual',values:act,cls:'b1'},{name:'Target',values:tgt,cls:'b3'}]}/>:none('No KPI targets or actual values entered yet.')}</Box>
  <Box title="KPI Completion Rate (%)" ic="percent">{comp.some(v=>v!=null)?<Line labels={cx.labels} values={comp} cls="c2" aria="Average KPI completion rate by month" fmt={compact} tip={v=>`${num(v)}% of target`}/>:none('Completion needs records with a target above 0 and an actual value.')}</Box>
  <Box title={`Target vs Actual${unit?` (${unit})`:''}`} ic="target" legend={[{name:'Target',cls:'b3'},{name:'Actual',cls:'b1'}]}>
   {recent.length?<BarGroup labels={recent.map(r=>short(r.title))} aria={`Target versus actual for the latest KPIs (${unit})`} fmt={compact} tip={v=>num(v)} series={[{name:'Target',values:recent.map(r=>n(r.fields?.target)),cls:'b3'},{name:'Actual',values:recent.map(r=>n(r.fields?.actual)),cls:'b1'}]}/>:none('No KPI targets or actual values entered yet.')}</Box>
  <Box title="Department Performance (avg achievement %)" ic="users">{dep.size?<HBars rows={[...dep.entries()].map(([d,v])=>({label:d,value:v.reduce((a,x)=>a+x,0)/v.length,text:`${num(Math.round(v.reduce((a,x)=>a+x,0)/v.length*10)/10)}% · ${v.length}`})).sort((a,b)=>b.value-a.value).slice(0,8)}/>:none('Add KPIs with a department, target and actual to compare departments.')}</Box></>}

export const kpiCfg:Cfg={module:'kpi-center',layout:'quad',titleLabel:'KPI name',hide:['amount'],
 subtitle:'Performance against targets: achievement, risk status and department comparison.',formTitle:'Add KPI',listTitle:'All KPI Records',noun:'KPI Record',
 footnote:'Achievement = actual ÷ target × 100. Achieved ≥ 100%, On track 80–99%, At risk < 80%; KPIs without a target above 0 and a numeric actual are not measurable and excluded. Trend and Target vs Actual compare one unit at a time.',
 fields:[{key:'department',label:'Department',placeholder:'Enter department'},{key:'owner',label:'KPI owner',placeholder:'Enter name'},{key:'target',label:'Target',type:'number',step:'any',min:'0',placeholder:'Enter target value'},{key:'actual',label:'Actual',type:'number',step:'any',placeholder:'Enter actual value'},{key:'unit',label:'Unit',placeholder:'e.g., %, count, ₹'},{key:'period',label:'Measurement period',placeholder:'e.g., Oct 2026'},{key:'source',label:'Verified source',placeholder:'e.g., Zoho, Excel, Report'}],
 columns:[{label:'Department',cell:r=>text(r.fields?.department)},{label:'KPI owner',cell:r=>text(r.fields?.owner)},{label:'Target',cell:r=>num(n(r.fields?.target))},{label:'Actual',cell:r=>num(n(r.fields?.actual))},{label:'Achievement',cell:r=>{const v=completion(r);return v==null?'—':`${num(Math.round(v*10)/10)}%`}},{label:'Performance',cell:r=>{const p=perf(r);return p?<span className={`sm-badge ${PERF_TONE[p]}`}>{p}</span>:<span className="sm-badge gray">Not measurable</span>}},{label:'Unit',cell:r=>text(r.fields?.unit)},{label:'Measurement period',cell:r=>text(r.fields?.period)},{label:'Verified source',cell:r=>text(r.fields?.source)}],
 cards,charts:c=><KpiCharts c={c}/>}
export default function KpiCenter({title}:{title:string}){return <RecordsPage title={title} cfg={kpiCfg}/>}
