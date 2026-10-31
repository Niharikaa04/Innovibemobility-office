export type Role='ceo'|'coo'|'cto'|'service_manager'|'hr'|'technician'|'employee'
export interface User{id:string;name:string;role:Role}
export const HOME:Record<Role,string>={ceo:'/ceo',coo:'/coo',cto:'/cto',service_manager:'/service-manager',hr:'/hr',technician:'/technician',employee:'/employee'}
export interface DashData{kpis:Record<string,{value:string;trend?:string;note?:string}>;panels:Record<string,any[]>;not_configured?:string[]}
export interface Notices{configured:boolean;items:{id:string;title:string;time?:string}[]}
const csrf=()=>decodeURIComponent((document.cookie.split('; ').find(c=>c.startsWith('csrf='))||'').slice(5))
async function req<T>(p:string,o:RequestInit={}):Promise<T>{
 const unsafe=o.method&&o.method!=='GET'
 const r=await fetch('/api'+p,{credentials:'include',...o,headers:{'Content-Type':'application/json',...(unsafe?{'X-CSRF-Token':csrf()}:{})}})
 if(!r.ok){const e=await r.json().catch(()=>({}));throw new Error(typeof e.detail==='string'?e.detail:r.status===422?'Check the details you entered.':'Request failed ('+r.status+')')}
 return r.json()}
/** Download a CSV (or other file) from an authenticated GET endpoint. Throws the server's message on failure. */
export async function download(path:string,filename:string){
 const r=await fetch('/api'+path,{credentials:'include'})
 if(!r.ok){const e=await r.json().catch(()=>({}));throw new Error(typeof e.detail==='string'?e.detail:'Export failed ('+r.status+')')}
 const url=URL.createObjectURL(await r.blob()),a=document.createElement('a');a.href=url;a.download=filename;document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url)}
export const api={login:(username:string,password:string,remember:boolean)=>req<User>('/auth/login',{method:'POST',body:JSON.stringify({username,password,remember})}),
 call:<T=any>(path:string,method:'GET'|'POST'|'PUT'|'PATCH'|'DELETE',body?:unknown)=>req<T>(path,{method,...(body!==undefined?{body:JSON.stringify(body)}:{})}),
 me:()=>req<User>('/auth/me'),logout:()=>req<{ok:boolean}>('/auth/logout',{method:'POST'}),
 forgot:(identifier:string)=>req<{configured:boolean;message:string}>('/auth/forgot',{method:'POST',body:JSON.stringify({identifier})}),
 notifications:()=>req<Notices>('/notifications'),dashboard:(p:string,from?:string,to?:string)=>{const q=new URLSearchParams();if(from)q.set('date_from',from);if(to)q.set('date_to',to);return req<DashData>('/dashboard/'+p+(q.toString()?'?'+q.toString():''))}}
