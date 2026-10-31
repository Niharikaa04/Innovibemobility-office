import {useEffect,useRef,useState,useSyncExternalStore} from 'react'
import type {KeyboardEvent,ReactNode} from 'react'
import {createPortal} from 'react-dom'
import './ops.css'

export const pretty=(s?:string|null)=>s?s.toLowerCase().replace(/_/g,' ').replace(/^\w/,c=>c.toUpperCase()):'—'
export const fmtDate=(d?:string|null)=>d?(d.length===10?new Date(+d.slice(0,4),+d.slice(5,7)-1,+d.slice(8,10)):new Date(d)).toLocaleDateString():'—'   // date-only values are local dates, not UTC instants
export const fmtTime=(d?:string|null)=>d?new Date(d).toLocaleString():'—'
/** Current LOCAL date and date-time (for <input max>): toISOString() is UTC and wrongly blocks or allows values in non-UTC time zones. */
export const localNow=()=>{const d=new Date(),p=(n:number)=>String(n).padStart(2,'0'),day=`${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}`;return {date:day,dateTime:`${day}T${p(d.getHours())}:${p(d.getMinutes())}`}}
export const Badge=({v}:{v:string})=><span className={'badge '+v}>{pretty(v)}</span>
export function Stat({name,value,on,alert,onClick}:{name:string;value:number|string;on?:boolean;alert?:boolean;onClick?:()=>void}):ReactNode{
 return <button type="button" className={'stat'+(on?' on':'')+(alert&&Number(value)>0?' alert':'')} data-static={onClick?undefined:'true'} aria-pressed={!!on} onClick={onClick}><span>{name}</span><strong>{value}</strong></button>}
export function Pager({page,total,limit,set}:{page:number;total:number;limit:number;set:(n:number)=>void}){
 const pages=Math.max(1,Math.ceil(total/limit))
 return <div className="ops-pager"><span className="note">Page {page} of {pages}</span><div><button className="ghost" disabled={page<=1} onClick={()=>set(page-1)}>Previous</button> <button className="ghost" disabled={page>=pages} onClick={()=>set(page+1)}>Next</button></div></div>}

/* ---- Shared Operations layout pieces (used by all six Operations pages; styles live in ops.css, scoped under .ops) ---- */

/** Page description + primary actions. The title stays in the DOM for screen readers; Dashboard's banner already shows it visually. */
export function PageHead({title,subtitle,children}:{title:string;subtitle:string;children?:ReactNode}){
 return <header className="ops-head"><div><h2 className="ops-title">{title}</h2><p className="note">{subtitle}</p></div>{children&&<div className="ops-actions">{children}</div>}</header>}

/* Messages follow the user: while a drawer is open they render inside the topmost drawer (so they are never hidden behind its backdrop);
   otherwise they render in the page. Only one copy is ever in the DOM. */
let slots:HTMLElement[]=[];const subs=new Set<()=>void>()
const emit=()=>subs.forEach(f=>f())
const subscribe=(f:()=>void)=>{subs.add(f);return()=>{subs.delete(f)}}
const topSlot=()=>slots.length?slots[slots.length-1]:null

/** Error (with Retry) and success messages. */
export function Notices({error,notice,onRetry}:{error:string;notice:string;onRetry?:()=>void}){
 const slot=useSyncExternalStore(subscribe,topSlot,()=>null)
 const body=<>{error&&<div className="err" role="alert"><span>{error}</span>{onRetry&&<button type="button" className="ghost" onClick={onRetry}>Retry</button>}</div>}{notice&&<div className="ok" role="status">{notice}</div>}</>
 return slot?createPortal(body,slot):body}

export const Loading=({label='Loading…'}:{label?:string})=><div className="ops-loading" role="status" aria-busy="true"><span className="ops-spin" aria-hidden="true"/>{label}</div>

let locks=0
/** Accessible slide-in panel for record details and add/edit forms. Esc or the backdrop closes it; Tab stays inside; focus returns to the opener. */
export function Drawer({label,onClose,wide,children}:{label:string;onClose:()=>void;wide?:boolean;children:ReactNode}){
 const ref=useRef<HTMLElement>(null),[slot,setSlot]=useState<HTMLElement|null>(null)
 useEffect(()=>{if(!slot)return;slots=[...slots,slot];emit();return()=>{slots=slots.filter(x=>x!==slot);emit()}},[slot])
 useEffect(()=>{const prev=document.activeElement as HTMLElement|null;ref.current?.focus();if(locks++===0)document.body.style.overflow='hidden'
  return()=>{if(--locks===0)document.body.style.overflow='';prev?.focus?.()}},[])
 const key=(e:KeyboardEvent<HTMLElement>)=>{
  if(e.key==='Escape'){e.stopPropagation();onClose();return}
  if(e.key!=='Tab'||!ref.current)return
  const f=Array.from(ref.current.querySelectorAll<HTMLElement>('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),summary,[tabindex]:not([tabindex="-1"])'))
  if(!f.length)return
  const first=f[0],last=f[f.length-1]
  if(e.shiftKey&&(document.activeElement===first||document.activeElement===ref.current)){e.preventDefault();last.focus()}
  else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}}
 return createPortal(<div className="ops ops-layer"><div className="ops-scrim" onClick={onClose} aria-hidden="true"/><section ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label={label} className={'ops-drawer'+(wide?' wide':'')} onKeyDown={key}><div ref={setSlot} className="ops-slot"/>{children}</section></div>,document.body)}
