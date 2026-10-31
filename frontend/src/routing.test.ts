import {describe,it,expect} from 'vitest'; import {redirectFor} from './routing'; import {HOME,Role} from './api'
const u=(role:Role)=>({id:'1',name:'x',role}); const roles=Object.keys(HOME) as Role[]
const ceoView=(r:Role,p:Role)=>r==='ceo'&&(p==='coo'||p==='cto')
describe('role routing',()=>{
 it('anonymous users go to login from every portal and subpage',()=>roles.forEach(r=>{expect(redirectFor(null,HOME[r])).toBe('/login');expect(redirectFor(null,HOME[r]+'/anything')).toBe('/login')}))
 it('anonymous users may see login and forgot-password',()=>{expect(redirectFor(null,'/login')).toBeNull();expect(redirectFor(null,'/forgot-password')).toBeNull()})
 it('signed-in users leave login',()=>roles.forEach(r=>{expect(redirectFor(u(r),'/login')).toBe(HOME[r]);expect(redirectFor(u(r),'/forgot-password')).toBe(HOME[r])}))
 roles.forEach(r=>roles.forEach(p=>{it(`${r} on ${HOME[p]}`,()=>expect(redirectFor(u(r),HOME[p])).toBe(r===p||ceoView(r,p)?null:HOME[r]));
  it(`${r} on ${HOME[p]}/subpage`,()=>expect(redirectFor(u(r),HOME[p]+'/leads-and-pipeline')).toBe(r===p||ceoView(r,p)?null:HOME[r]))}))
 it('COO and CTO have no cross access',()=>{expect(redirectFor(u('coo'),'/cto')).toBe('/coo');expect(redirectFor(u('cto'),'/coo')).toBe('/cto')})
 it('unknown paths go home or to login',()=>{expect(redirectFor(u('hr'),'/cco')).toBe('/hr');expect(redirectFor(null,'/cco')).toBe('/login');expect(redirectFor(u('hr'),'/')).toBe('/hr')})})
