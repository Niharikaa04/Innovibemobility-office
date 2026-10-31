import RecordsPage from './RecordsPage'
import type {Card,Cfg,Ctx} from './RecordsPage'
import {Box,BarGroup,Empty,Line,compact,compactInr,inr,latestMonthly,n,num,text} from './modkit'

/* Startup Metrics = financial health + growth. Every number comes from this module's own records (fields stored in the existing `fields` JSON).
   Monthly values use the latest entry per reporting month; headline cards use the most recent month that has a value. Runway = latest cash balance ÷ latest monthly burn (only when both are > 0). */
const KEYS=['monthly_revenue','monthly_burn','cash_balance','new_customers','churn_rate']
const last=(a:(number|null)[])=>{for(let i=a.length-1;i>=0;i--)if(a[i]!=null)return {v:a[i] as number,i};return null}
const has=(k:string,label:string)=>({label,match:(r:{fields:Record<string,unknown>})=>n(r.fields?.[k])!=null})
const cards=(c:Ctx):Card[]=>{const all=c.items,m=latestMonthly(all||[],KEYS),L=(k:string)=>last(m.vals[k]),rev=L('monthly_revenue'),burn=L('monthly_burn'),cash=L('cash_balance'),cus=L('new_customers'),ch=L('churn_rate')
 const at=(x:{i:number}|null)=>!all?'':x?`As of ${m.labels[x.i]}`:'Not entered yet'
 const runway=cash&&burn&&cash.v>0&&burn.v>0?cash.v/burn.v:null
 return [
  {filter:has('monthly_revenue','Records with revenue'),k:'rev',label:'Monthly revenue',value:inr(rev?.v),sub:at(rev),ic:'trend',c:'green'},
  {filter:has('monthly_burn','Records with burn'),k:'burn',label:'Monthly burn',value:inr(burn?.v),sub:at(burn),ic:'coins',c:'red'},
  {filter:has('cash_balance','Records with a cash balance'),k:'cash',label:'Cash balance',value:inr(cash?.v),sub:at(cash),ic:'bars',c:'teal'},
  {k:'runway',label:'Cash runway',value:runway!=null?`${runway.toFixed(1)} mo`:'—',sub:!all?'':runway!=null?'Cash ÷ monthly burn':'Needs cash balance and burn above 0',ic:'cal2',c:'blue'},
  {filter:has('new_customers','Records with new customers'),k:'cus',label:'New customers',value:cus?num(cus.v):'—',sub:at(cus),ic:'users',c:'purple'},
  {filter:has('churn_rate','Records with a churn rate'),k:'churn',label:'Churn rate',value:ch?`${num(ch.v)}%`:'—',sub:at(ch),ic:'percent',c:'amber'}]}

const charts=(c:Ctx)=>{const m=latestMonthly(c.items||[],KEYS),v=m.vals,any=(a:(number|null)[])=>a.some(x=>x!=null)
 const none=(t:string)=><Empty msg={c.err?`Chart data could not be loaded: ${c.err}`:t}/>
 return <>
  <Box title="Revenue vs Burn" ic="bars" wide legend={[{name:'Revenue',cls:'b1'},{name:'Burn',cls:'b2'}]}>
   {any(v.monthly_revenue)||any(v.monthly_burn)?<BarGroup labels={m.labels} aria="Monthly revenue versus burn" fmt={compactInr} tip={x=>inr(x)} series={[{name:'Revenue',values:v.monthly_revenue,cls:'b1'},{name:'Burn',values:v.monthly_burn,cls:'b2'}]}/>:none('No monthly revenue or burn entered yet.')}</Box>
  <Box title="Cash Balance Trend" ic="coins">{any(v.cash_balance)?<Line labels={m.labels} values={v.cash_balance} cls="c3" aria="Cash balance by month" fmt={compactInr} tip={x=>inr(x)}/>:none('No cash balance entered yet.')}</Box>
  <Box title="New Customer Growth" ic="users">{any(v.new_customers)?<Line labels={m.labels} values={v.new_customers} cls="c1" aria="New customers by month" fmt={compact} tip={x=>`${num(x)} new customers`}/>:none('No new-customer counts entered yet.')}</Box>
  <Box title="Churn Rate (%)" ic="percent">{any(v.churn_rate)?<Line labels={m.labels} values={v.churn_rate} cls="c2" aria="Churn rate by month" fmt={compact} tip={x=>`${num(x)}% churn`}/>:none('No churn rates entered yet.')}</Box></>}

export const startupCfg:Cfg={module:'startup-metrics',layout:'quad',titleLabel:'Entry title',hide:['amount','due_date'],
 subtitle:'Financial health and growth: revenue, burn, cash runway, customer growth and churn.',formTitle:'Add Monthly Metrics',listTitle:'Monthly Metric Entries',noun:'Startup Metric Record',
 footnote:'Each month shows the latest value entered for it. Runway = latest cash balance ÷ latest monthly burn. Months without an entry stay empty; nothing is estimated.',
 fields:[{key:'period',label:'Reporting period',placeholder:'e.g., Oct 2026'},{key:'monthly_revenue',label:'Monthly revenue (₹)',type:'number',step:'0.01',min:'0',placeholder:'Enter amount'},{key:'monthly_burn',label:'Monthly burn (₹)',type:'number',step:'0.01',min:'0',placeholder:'Enter amount'},{key:'cash_balance',label:'Cash balance (₹)',type:'number',step:'0.01',placeholder:'Enter amount'},{key:'new_customers',label:'New customers',type:'number',step:'1',min:'0',placeholder:'Enter number'},{key:'churn_rate',label:'Churn rate (%)',type:'number',step:'0.01',min:'0',max:'100',placeholder:'Enter percentage'}],
 columns:[{label:'Reporting period',cell:r=>text(r.fields?.period)},{label:'Revenue (₹)',cell:r=>inr(n(r.fields?.monthly_revenue))},{label:'Burn (₹)',cell:r=>inr(n(r.fields?.monthly_burn))},{label:'Cash balance (₹)',cell:r=>inr(n(r.fields?.cash_balance))},{label:'Customers',cell:r=>num(n(r.fields?.new_customers))},{label:'Churn (%)',cell:r=>num(n(r.fields?.churn_rate))}],
 cards,charts}
export default function StartupMetrics({title}:{title:string}){return <RecordsPage title={title} cfg={startupCfg}/>}
