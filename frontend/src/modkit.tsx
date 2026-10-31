import type {ReactNode} from 'react'

/* Shared building blocks for the four record-based CEO pages (Startup Metrics, KPI Center, Business Overview, Reports & Analytics).
   Pure helpers + SVG charts. No extra dependency. Nothing here fabricates data: every chart receives values from saved records. */
export type Rec={id:string;title:string;status:string;description:string;amount:number|null;due_date:string|null;fields:Record<string,unknown>;created_at:string;updated_at?:string}
export type Summary={total:number;open:number;completed:number;lost:number;amount_total:number;statuses:{status:string;count:number}[]}
export type ExportOut={items:Rec[];count:number;truncated:boolean}

export const MON=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
export const n=(v:unknown):number|null=>typeof v==='number'?(isFinite(v)?v:null):typeof v==='string'&&v.trim()!==''&&isFinite(Number(v))?Number(v):null
const nf=new Intl.NumberFormat('en-IN',{maximumFractionDigits:2})
export const num=(v:number|null|undefined)=>v==null||!isFinite(v)?'—':nf.format(v)
export const inr=(v:number|null|undefined)=>v==null||!isFinite(v)?'—':'₹ '+nf.format(v)
export const pad=(x:number)=>String(x).padStart(2,'0')
export const ymd=(d:Date)=>`${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`
export const dmy=(s:string|null|undefined)=>{if(!s)return '—';if(/^\d{4}-\d{2}-\d{2}$/.test(s))return `${s.slice(8)}-${s.slice(5,7)}-${s.slice(0,4)}`;const d=new Date(s);return isNaN(+d)?'—':`${pad(d.getDate())}-${pad(d.getMonth()+1)}-${d.getFullYear()}`}
export const pill=(s:string)=>/^\d{4}-\d{2}-\d{2}$/.test(s)?`${s.slice(8)} ${MON[+s.slice(5,7)-1]} ${s.slice(0,4)}`:s
export const compact=(v:number)=>{const a=Math.abs(v),s=v<0?'-':'';if(a>=1e7)return `${s}${+(a/1e7).toFixed(2)}Cr`;if(a>=1e5)return `${s}${+(a/1e5).toFixed(2)}L`;if(a>=1e3)return `${s}${+(a/1e3).toFixed(2)}K`;return `${s}${+a.toFixed(1)}`}
export const compactInr=(v:number)=>(v<0?'-':'')+'₹'+compact(Math.abs(v))
export const tone=(s:string)=>({Open:'blue','In Progress':'blue',Scheduled:'blue',Pending:'amber',Approved:'green',Completed:'green',Won:'green',Lost:'red',Blocked:'red',Cancelled:'red'} as Record<string,string>)[s]||'gray'
export const text=(v:unknown)=>{const s=String(v??'').trim();return s||'—'}

/* Which calendar month a month-number belongs to: y*12+m. */
export const dateIdx=(s:unknown):number|null=>{const t=String(s??'').trim();const m=/^(\d{4})-(\d{2})/.exec(t);if(m&&+m[2]>=1&&+m[2]<=12)return +m[1]*12+ +m[2]-1;if(!t)return null;const d=new Date(t);return isNaN(+d)?null:d.getFullYear()*12+d.getMonth()}
/* A record's "Reporting period" if readable (Oct 2026 / October 2026 / 2026-10 / 10/2026), else the day it was created. */
export function monthIdx(r:Rec,key='period'):number|null{
 const p=String(r.fields?.[key]??'').trim()
 const a=/^(\d{4})[-/](\d{1,2})\b/.exec(p);if(a){const mo=+a[2];if(mo>=1&&mo<=12)return +a[1]*12+mo-1}
 const b=/^(\d{1,2})[-/](\d{4})$/.exec(p);if(b){const mo=+b[1];if(mo>=1&&mo<=12)return +b[2]*12+mo-1}
 const c=/^([A-Za-z]{3,})\.?[\s,-]*(\d{4})$/.exec(p);if(c){const k=MON.findIndex(x=>x.toLowerCase()===c[1].slice(0,3).toLowerCase());if(k>=0)return +c[2]*12+k}
 return dateIdx(r.created_at)}
export const createdIdx=(r:Rec)=>dateIdx(r.created_at)
/* Consecutive months from the first to the last month that has data (max 12). Months without data are shown empty, never interpolated. */
export function axis(idxs:number[]){const ok=idxs.filter(i=>i!=null);if(!ok.length)return {months:[] as number[],labels:[] as string[]}
 const hi=Math.max(...ok),lo=Math.max(Math.min(...ok),hi-11),multi=Math.floor(lo/12)!==Math.floor(hi/12),months:number[]=[]
 for(let i=lo;i<=hi;i++)months.push(i);return {months,labels:months.map(i=>MON[i%12]+(multi?` ’${pad(Math.floor(i/12)%100)}`:''))}}
export const newest=(items:Rec[])=>[...items].sort((x,y)=>x.created_at<y.created_at?1:x.created_at>y.created_at?-1:0)
export const oldest=(items:Rec[])=>[...items].sort((x,y)=>x.created_at<y.created_at?-1:x.created_at>y.created_at?1:0)

/* ---------- icons ---------- */
const ICONS:Record<string,ReactNode>={
 bars:<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>,
 clip:<><rect x="6" y="4" width="12" height="17" rx="2"/><path d="M9 4h6v3H9zM9 12h6M9 16h4"/></>,
 check:<><circle cx="12" cy="12" r="9"/><path d="M8 12.5l3 3 5-6"/></>,
 alert:<><circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 16.5v.5"/></>,
 coins:<><ellipse cx="12" cy="7" rx="7" ry="3"/><path d="M5 7v5c0 1.7 3.1 3 7 3s7-1.3 7-3V7M5 12v5c0 1.7 3.1 3 7 3s7-1.3 7-3v-5"/></>,
 trend:<path d="M3 17l6-6 4 4 8-8M15 7h6v6"/>,
 users:<><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6M16 4.5a3.5 3.5 0 010 7M18 14c2.2.6 3.5 2.5 3.5 6"/></>,
 percent:<><path d="M19 5L5 19"/><circle cx="7" cy="7" r="2.5"/><circle cx="17" cy="17" r="2.5"/></>,
 doc:<><path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5M10 13h6M10 17h6"/></>,
 download:<path d="M12 4v11M7 11l5 5 5-5M5 20h14"/>,
 search:<><circle cx="11" cy="11" r="6.5"/><path d="M16 16l5 5"/></>,
 calendar:<><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/></>,
 edit:<><path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13 7l4 4"/></>,
 trash:<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6"/>,
 plus:<path d="M12 5v14M5 12h14"/>,
 chev:<path d="M6 9l6 6 6-6"/>,
 target:<><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.2"/></>,
 pie:<><path d="M12 3v9h9"/><path d="M20.5 15A9 9 0 1112 3"/></>,
 build:<><rect x="5" y="3" width="10" height="18" rx="1"/><path d="M15 9h4v12h-4M8 7h4M8 11h4M8 15h4"/></>,
 cal2:<><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4M8 14h3"/></>}
export const Icon=({n:k}:{n:string})=><svg className="sm-ic" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{ICONS[k]}</svg>

/* ---------- charts (plain SVG) ---------- */
const W=520,H=250,PL=54,PR=14,PT=14,PB=30
function niceMax(v:number){if(v<=0)return 1;const e=Math.pow(10,Math.floor(Math.log10(v))),f=v/e;return (f<=1?1:f<=2?2:f<=5?5:10)*e}
function domain(vals:(number|null)[]){const d=vals.filter((v):v is number=>v!=null);const mx=Math.max(0,...d),mn=Math.min(0,...d);let hi=niceMax(mx);const lo=mn<0?-niceMax(-mn):0;if(hi===lo)hi=lo+1;return {lo,hi,ticks:[0,1,2,3,4].map(i=>lo+(hi-lo)*i/4)}}
function Frame({labels,lo,hi,ticks,fmt,children}:{labels:string[];lo:number;hi:number;ticks:number[];fmt:(v:number)=>string;children:(x:(i:number)=>number,y:(v:number)=>number,gw:number)=>ReactNode}){
 const w=W-PL-PR,h=H-PT-PB,y=(v:number)=>PT+(hi-v)/(hi-lo)*h,gw=w/Math.max(1,labels.length),x=(i:number)=>PL+gw*(i+.5)
 return <>{ticks.map(t=><g key={t}><line x1={PL} x2={W-PR} y1={y(t)} y2={y(t)} className="sm-grid"/><text x={PL-8} y={y(t)+4} textAnchor="end" className="sm-axis">{fmt(t)}</text></g>)}
  {labels.map((l,i)=><text key={i} x={x(i)} y={H-10} textAnchor="middle" className="sm-axis">{l}</text>)}{children(x,y,gw)}</>}
export type Ser={name:string;values:(number|null)[];cls:'b1'|'b2'|'b3'}
export function BarGroup({labels,series,fmt,tip,aria}:{labels:string[];series:Ser[];fmt:(v:number)=>string;tip:(v:number)=>string;aria:string}){
 const {lo,hi,ticks}=domain(series.flatMap(s=>s.values))
 return <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={aria} className="sm-svg"><Frame labels={labels} lo={lo} hi={hi} ticks={ticks} fmt={fmt}>{(x,y,gw)=>{
  const k=series.length,bw=Math.max(4,Math.min(16,gw*.6/k)),tot=k*bw+(k-1)*2,z=y(0)
  return <>{labels.map((_,i)=><g key={i}>{series.map((s,j)=>{const v=s.values[i];return v==null?null:<rect key={j} x={x(i)-tot/2+j*(bw+2)} y={Math.min(y(v),z)} width={bw} height={Math.max(1,Math.abs(y(v)-z))} rx="2" className={`sm-${s.cls}`}><title>{`${labels[i]} · ${s.name}: ${tip(v)}`}</title></rect>})}</g>)}</>}}</Frame></svg>}
export function Line({labels,values,cls,aria,fmt,tip}:{labels:string[];values:(number|null)[];cls:'c1'|'c2'|'c3';aria:string;fmt:(v:number)=>string;tip:(v:number)=>string}){
 const {lo,hi,ticks}=domain(values)
 return <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={aria} className="sm-svg"><Frame labels={labels} lo={lo} hi={hi} ticks={ticks} fmt={fmt}>{(x,y)=>{
  const runs:number[][]=[];let cur:number[]=[];values.forEach((v,i)=>{if(v==null){if(cur.length)runs.push(cur);cur=[]}else cur.push(i)});if(cur.length)runs.push(cur)
  const base=y(Math.max(lo,0))
  return <>{runs.map((r,k)=>r.length<2?null:<g key={k}><polygon className={`sm-area ${cls}`} points={`${x(r[0])},${base} ${r.map(i=>`${x(i)},${y(values[i] as number)}`).join(' ')} ${x(r[r.length-1])},${base}`}/><polyline className={`sm-line ${cls}`} fill="none" points={r.map(i=>`${x(i)},${y(values[i] as number)}`).join(' ')}/></g>)}
   {values.map((v,i)=>v==null?null:<circle key={i} cx={x(i)} cy={y(v)} r="3.6" className={`sm-dot ${cls}`}><title>{`${labels[i]} · ${tip(v)}`}</title></circle>)}</>}}</Frame></svg>}
export const PAL=['#16a36a','#2563eb','#f59e0b','#7c5cf0','#e5484d','#06b6d4','#10b981','#94a3b8']
/* Donut: at most 7 slices + "Others". Returns nothing for an empty / zero-total set (caller shows its own empty state). */
export function Donut({data,caption,aria}:{data:{label:string;value:number}[];caption:string;aria:string}){
 const rows=data.filter(d=>d.value>0).sort((a,b)=>b.value-a.value);const top=rows.slice(0,7),rest=rows.slice(7).reduce((s,d)=>s+d.value,0);const list=rest>0?[...top,{label:'Others',value:rest}]:top
 const tot=list.reduce((s,d)=>s+d.value,0);if(!tot)return null
 const R=60,C=2*Math.PI*R;let off=0
 return <div className="sm-donut"><svg viewBox="0 0 160 160" role="img" aria-label={aria}>{list.map((d,i)=>{const len=d.value/tot*C;const el=<circle key={d.label} cx="80" cy="80" r={R} fill="none" stroke={PAL[i%PAL.length]} strokeWidth="22" strokeDasharray={`${len} ${C-len}`} strokeDashoffset={-off} transform="rotate(-90 80 80)"><title>{`${d.label}: ${num(d.value)} (${Math.round(d.value/tot*100)}%)`}</title></circle>;off+=len;return el})}
  <text x="80" y="82" textAnchor="middle" className="sm-dtot">{num(tot)}</text><text x="80" y="98" textAnchor="middle" className="sm-axis">{caption}</text></svg>
  <ul className="sm-dleg">{list.map((d,i)=><li key={d.label}><i style={{background:PAL[i%PAL.length]}}/><span>{d.label}</span><b>{num(d.value)}</b></li>)}</ul></div>}
export function HBars({rows}:{rows:{label:string;value:number;text:string}[]}){
 const mx=Math.max(...rows.map(r=>Math.abs(r.value)),0)||1
 return <ul className="sm-hbars">{rows.map(r=><li key={r.label}><span className="l" title={r.label}>{r.label}</span><span className="t"><i style={{width:`${Math.max(2,Math.abs(r.value)/mx*100)}%`}}/></span><b>{r.text}</b></li>)}</ul>}
export const Empty=({msg}:{msg:string})=><div className="sm-empty">{msg}</div>

/* One value per month = the most recently entered value for that month (per key). Months with nothing entered stay null. */
export function latestMonthly(items:Rec[],keys:string[],idx:(r:Rec)=>number|null=r=>monthIdx(r)){
 const by=new Map<number,Record<string,number>>()
 for(const r of oldest(items)){const i=idx(r);if(i==null)continue;for(const k of keys){const v=n(r.fields?.[k]);if(v!=null){let c=by.get(i);if(!c){c={};by.set(i,c)}c[k]=v}}}
 const ax=axis([...by.keys()]);return {labels:ax.labels,vals:Object.fromEntries(keys.map(k=>[k,ax.months.map(m=>by.get(m)?.[k]??null)])) as Record<string,(number|null)[]>}}
export const Box=({title,ic,wide,legend,actions,children}:{title:string;ic:string;wide?:boolean;legend?:{name:string;cls:string}[];actions?:ReactNode;children:ReactNode})=>
 <div className={`sm-box${wide?' wide':''}`}><div className="sm-boxhead"><h3><Icon n={ic}/>{title}</h3>{actions}</div>
  {legend&&<div className="sm-legend">{legend.map(l=><span key={l.name}><i className={l.cls}/>{l.name}</span>)}</div>}{children}</div>
