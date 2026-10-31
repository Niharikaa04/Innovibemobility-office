import RecordsPage,{OPEN_ST,DONE_ST,LOST_ST,inStatus,pctOf,statusCount} from './RecordsPage'
import type {Card,Cfg,Ctx} from './RecordsPage'
import {Box,BarGroup,Donut,Empty,HBars,axis,compact,createdIdx,dmy,text,ymd} from './modkit'

/* Reports & Analytics: report type / period start / period end / owner (unchanged schema).
   Trend = number of reports created per month. Type distribution = records grouped by their "Report type" (blank = Unspecified). Status = status breakdown. */
/* Overdue = has a due date before today and is not Completed, Lost or Cancelled. */
const today=ymd(new Date()),overdue={label:'Overdue reports',match:(r:{due_date:string|null;status:string})=>!!r.due_date&&r.due_date.slice(0,10)<today&&!DONE_ST.includes(r.status)&&!LOST_ST.includes(r.status)}
const cards=(c:Ctx):Card[]=>{const s=c.summary,all=c.items,sch=statusCount(s,'Scheduled');return [
 {clear:true,k:'total',label:'Total reports',value:s?String(s.total):'—',sub:all?`${c.createdThisMonth} created this month`:'',ic:'doc',c:'green'},
 {filter:inStatus('Open / Pending',OPEN_ST),k:'open',label:'Open / Pending',value:s?String(s.open):'—',sub:pctOf(s,s?.open??0),ic:'clip',c:'blue'},
 {filter:inStatus('Completed',DONE_ST),k:'done',label:'Completed',value:s?String(s.completed):'—',sub:pctOf(s,s?.completed??0),ic:'check',c:'purple'},
 {filter:inStatus('Scheduled',['Scheduled']),k:'sch',label:'Scheduled',value:s?String(sch):'—',sub:s?(sch?pctOf(s,sch):'No records with status “Scheduled”'):'',ic:'cal2',c:'teal'},
 {filter:overdue,k:'late',label:'Overdue',value:all?String(all.filter(overdue.match).length):'—',sub:all?'Past due date and not completed':'',ic:'alert',c:'red'}]}

const charts=(c:Ctx)=>{const all=c.items||[],none=(t:string)=><Empty msg={c.err?`Chart data could not be loaded: ${c.err}`:t}/>
 const by=new Map<number,number>();for(const r of all){const i=createdIdx(r);if(i!=null)by.set(i,(by.get(i)||0)+1)}
 const ax=axis([...by.keys()]),types=new Map<string,number>();for(const r of all){const t=String(r.fields?.report_type??'').trim()||'Unspecified';types.set(t,(types.get(t)||0)+1)}
 const owners=new Map<string,number>();for(const x of all){const o=String(x.fields?.owner??'').trim()||'Unassigned';owners.set(o,(owners.get(o)||0)+1)}
 return <>
  <Box title="Reports Trend" ic="bars">{ax.months.length?<BarGroup labels={ax.labels} aria="Reports created by month" fmt={compact} tip={v=>`${v} report(s)`} series={[{name:'Reports',values:ax.months.map(m=>by.get(m)??null),cls:'b2'}]}/>:none('No reports created in this period.')}</Box>
  <Box title="Report Type Distribution" ic="pie">{all.length?<Donut aria="Reports by type" caption="Total reports" data={[...types.entries()].map(([label,value])=>({label,value}))}/>:none('No reports to chart yet.')}</Box>
  <Box title="Reports by Owner" ic="users">{owners.size?<HBars rows={[...owners.entries()].map(([label,value])=>({label,value,text:String(value)})).sort((a,b)=>b.value-a.value).slice(0,8)}/>:none('No reports to chart yet.')}</Box>
  <Box title="Reports by Status" ic="pie">{c.summary&&c.summary.statuses?.length?<Donut aria="Reports by status" caption="Total reports" data={c.summary.statuses.map(s=>({label:s.status,value:s.count}))}/>:<Empty msg="No reports yet."/>}</Box></>}

export const reportsCfg:Cfg={module:'reports-and-analytics',layout:'quad',titleLabel:'Report title',hide:['amount'],
 validate:f=>f.period_start&&f.period_end&&f.period_end<f.period_start?'Period end cannot be before period start.':'',
 subtitle:'Manage reports and analyse reporting activity by type, owner and status.',formTitle:'Add Report',listTitle:'All Reports',noun:'Report',
 footnote:'Trend counts reports by the month they were created; type, owner and status charts use the reports in the selected date range. Overdue = due date passed and not completed, lost or cancelled.',
 fields:[{key:'report_type',label:'Report type',type:'select',options:['Sales','Finance','Operations','People','Customer','Technical','Other']},{key:'period_start',label:'Period start',type:'date'},{key:'period_end',label:'Period end',type:'date'},{key:'owner',label:'Report owner',placeholder:'Enter owner name'}],
 columns:[{label:'Report type',cell:r=>text(r.fields?.report_type)},{label:'Period',cell:r=>r.fields?.period_start||r.fields?.period_end?`${dmy(String(r.fields?.period_start??''))} → ${dmy(String(r.fields?.period_end??''))}`:'—'},{label:'Owner',cell:r=>text(r.fields?.owner)}],
 cards,charts}
export default function ReportsAnalytics({title}:{title:string}){return <RecordsPage title={title} cfg={reportsCfg}/>}
