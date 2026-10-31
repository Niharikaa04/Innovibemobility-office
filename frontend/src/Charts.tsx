import {ResponsiveContainer,PieChart,Pie,Cell,LineChart,Line,BarChart,Bar,XAxis,YAxis,Tooltip,Legend,ComposedChart,CartesianGrid} from 'recharts'
import India from '@svg-maps/india'
import {Panel,COLS,METRICS,FUNNEL} from './nav'
const COL=['#16a34a','#2563eb','#f59e0b','#dc2626','#7c3aed']
/* ticket status colours like the design; any other name falls back to COL */
const STATUS:Record<string,string>={open:'#ef4444','in progress':'#f59e0b',resolved:'#16a34a','on hold':'#2563eb'}
const colorOf=(name:string,i:number)=>STATUS[String(name).toLowerCase()]||COL[i%5]
export const Empty=({msg}:{msg:string})=><div className="empty">{msg}</div>
export function Chart({p,d,nc}:{p:Panel;d:any[];nc?:boolean}){
 const none=nc?'Not configured. Connect a monitoring source in Integrations.':'No data yet.'
 const keys=d[0]?Object.keys(d[0]).filter(k=>k!=='name'):[]
 const lbl=METRICS[p.k]
 if(p.type==='metrics'&&lbl)return <div className="mgrid">{lbl.map(l=>{const r=d.find(x=>x.name===l);return <div key={l}><small>{l}</small><b>{r?r.value:'—'}</b></div>})}{!d.length&&<p className="note">{none}</p>}</div>
 if(p.type==='funnel'){const max=Math.max(1,...d.map(r=>Number(r.value)||0));return <div className="funnel">{FUNNEL.map((s,i)=>{const r=d.find(x=>x.name===s);const w=d.length?Math.max(18,(Number(r?.value)||0)/max*100):100-i*13;return <div key={s} className="fr"><div className="fb" style={{width:w+'%',background:d.length?COL[i%5]:'var(--line)'}}/><span>{s}</span><b>{r?r.value:'—'}</b></div>})}{!d.length&&<p className="note">{none}</p>}</div>}
 if(p.type==='map'){const by:Record<string,number>={};d.forEach(r=>{if(r.state)by[String(r.state).toLowerCase()]=(by[String(r.state).toLowerCase()]||0)+Number(r.value||0)});const mx=Math.max(1,...Object.values(by))
  const top=Math.max(1,...d.map(r=>Number(r.value)||0))
  return <div className="mapw"><svg viewBox={India.viewBox} role="img" aria-label="India service tickets by state">{India.locations.map((l:any)=>{const v=by[l.name.toLowerCase()]||0;return <path key={l.id} d={l.path} fill={v?`rgba(37,99,235,${.25+.75*v/mx})`:'var(--line)'} stroke="var(--card)" strokeWidth=".6"><title>{l.name}{v?`: ${v}`:''}</title></path>})}</svg>
   <ol>{d.slice(0,5).map((r,i)=><li key={i}><span>{r.name}</span><i className="trk"><i style={{width:(Number(r.value)||0)/top*100+'%'}}/></i><b>{r.value}</b></li>)}{!d.length&&<li className="note">{none}</li>}</ol></div>}
 if(p.type==='table'){const c=COLS[p.k]||(d[0]?Object.keys(d[0]):[]);return <div className="tw"><table><thead><tr>{c.map(x=><th key={x}>{x}</th>)}</tr></thead><tbody>{d.map((r,i)=><tr key={i}>{c.map(x=><td key={x}>{String(r[x]??'')}</td>)}</tr>)}</tbody></table>{!d.length&&<p className="note">{none}</p>}</div>}
 if(p.type==='list'){return d.length?<div className="lst">{d.map((r,i)=><div key={i} className="li"><span>{r.title??r.name}{r.sub&&<small style={{display:'block',color:'var(--mute)'}}>{r.sub}</small>}</span><b>{r.value??r.time??''}</b></div>)}</div>:<Empty msg={none}/>}
 if(!d.length)return <Empty msg={none}/>
 const H=190
 if(p.type==='donut'){const total=d.reduce((a,r)=>a+(Number(r.value)||0),0)
  return <div className="donut-wrap"><div className="donut"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={d} dataKey="value" nameKey="name" innerRadius="62%" outerRadius="100%" stroke="none">{d.map((r,i)=><Cell key={i} fill={colorOf(r.name,i)}/>)}</Pie><Tooltip/></PieChart></ResponsiveContainer><div className="donut-mid"><b>{total}</b><small>Total</small></div></div>
   <ul className="dlegend">{d.map((r,i)=><li key={i}><i style={{background:colorOf(r.name,i)}}/><span>{r.name}</span><b>{r.value}</b><em>{total?(Number(r.value)/total*100).toFixed(1)+'%':''}</em></li>)}</ul></div>}
 if(p.type==='line')return <ResponsiveContainer height={H}><LineChart data={d}><CartesianGrid strokeDasharray="3 3"/><XAxis dataKey="name"/><YAxis/><Tooltip/><Legend/>{keys.map((k,i)=><Line key={k} dataKey={k} stroke={COL[i%5]}/>)}</LineChart></ResponsiveContainer>
 if(p.type==='bar')return <ResponsiveContainer height={H}><BarChart data={d}><CartesianGrid strokeDasharray="3 3" vertical={false}/><XAxis dataKey="name"/><YAxis/><Tooltip/><Legend/>{keys.map((k,i)=><Bar key={k} dataKey={k} fill={i?COL[i%5]:'#2563eb'} radius={[4,4,0,0]}/>)}</BarChart></ResponsiveContainer>
 return <ResponsiveContainer height={H}><ComposedChart data={d}><CartesianGrid strokeDasharray="3 3"/><XAxis dataKey="name"/><YAxis/><Tooltip/><Legend/><Bar dataKey="revenue" fill="#2563eb"/><Bar dataKey="expenses" fill="#f59e0b"/><Line dataKey="profit" stroke="#16a34a"/></ComposedChart></ResponsiveContainer>}
