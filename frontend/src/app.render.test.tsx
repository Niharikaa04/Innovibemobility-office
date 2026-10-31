// @vitest-environment jsdom
import {describe,it,expect,vi,beforeEach,afterEach} from 'vitest'
import {render,screen,cleanup,within,waitFor} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {MemoryRouter} from 'react-router-dom'
import App from './App'; import {HOME,Role} from './api'; import {NAV,LAYOUT,slug,PORTAL_NAMES} from './nav'
const ROLES=Object.keys(HOME) as Role[]
function mock(role:Role|null,panels:any={},nc:string[]=[]){
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>{const j=(b:any,ok=true,status=200)=>({ok,status,json:async()=>b})
  if(url.endsWith('/auth/me'))return role?j({id:'1',name:'Test User',role}):j({detail:'Not signed in.'},false,401)
  if(url.includes('/dashboard/'))return j({kpis:{},panels,not_configured:nc})
  if(url.endsWith('/notifications'))return j({configured:false,items:[]})
  return j({},false,404)}))}
const open=(path:string)=>render(<MemoryRouter initialEntries={[path]}><App/></MemoryRouter>)
beforeEach(()=>{document.cookie='csrf=abc'}); afterEach(()=>{cleanup();vi.unstubAllGlobals()})
describe('every portal renders for its own role',()=>{ROLES.forEach(r=>it(PORTAL_NAMES[r],async()=>{mock(r);open(HOME[r])
 await screen.findByRole('heading',{level:1});const nav=screen.getByRole('navigation',{name:'Main navigation'})
 const expected=NAV[r].reduce((n,[,i])=>n+i.length,0)+(r==='ceo'?2:0);expect(within(nav).getAllByRole('link')).toHaveLength(expected)}))})
describe('executive dashboards',()=>{
 (['ceo','coo','cto'] as Role[]).forEach(r=>{
  it(`${r}: six KPI cards in the specified order`,async()=>{mock(r);const {container}=open(HOME[r]);await screen.findByRole('heading',{level:1})
   expect([...container.querySelectorAll(r==='ceo'?'.kpi-card .kpi-name':'.kpi span')].map(e=>e.textContent)).toEqual(LAYOUT[r].kpis);expect(LAYOUT[r].kpis).toHaveLength(6)})
  it(`${r}: tab count and every tab shows content`,async()=>{mock(r);const {container}=open(HOME[r]);await screen.findByRole('heading',{level:1})
   const tabs=screen.getAllByRole('tab');expect(tabs).toHaveLength(LAYOUT[r].tabs.length)
   for(const t of tabs){await userEvent.click(t);await waitFor(()=>expect(container.querySelectorAll(r==='ceo'?'.ch-card, .panel':'.panel').length).toBeGreaterThan(0))}})      // waitFor: the AI Insights panel is lazy-loaded
  it(`${r}: Overview shows every specified panel`,async()=>{mock(r);open(HOME[r]);await screen.findByRole('heading',{level:1})
   LAYOUT[r].rows.flat().forEach(p=>expect(screen.getByRole('heading',{name:p.t})).toBeTruthy())})})
 it('CTO marks monitoring-backed KPIs as Not configured',async()=>{mock('cto',{},['monitoring','billing']);open('/cto')
  await waitFor(()=>expect(screen.getAllByText('Not configured').length).toBeGreaterThanOrEqual(3))})
 it('CEO funnel has five stages (New Lead, Contacted, Proposal Sent, Negotiation, Won) and startup grid has nine metrics',async()=>{mock('ceo');const {container}=open('/ceo');await screen.findByRole('heading',{level:1})
  expect(container.querySelectorAll('.funnel .fr')).toHaveLength(5);expect(container.querySelectorAll('.mgrid > div')).toHaveLength(9);expect(container.querySelectorAll('.mapw svg path').length).toBeGreaterThan(30)})
 it('funnel and map show supplied values (no invented data when absent)',async()=>{mock('ceo',{pipeline:[{name:'New Lead',value:40},{name:'Won',value:5}],cities:[{name:'Vizag',state:'Andhra Pradesh',value:9}],startup:[{name:'NPS',value:'72'}]});const {container}=open('/ceo')
  await screen.findByText('Vizag');expect(within(container).getByText('72')).toBeTruthy();expect(container.querySelector('.funnel')!.textContent).toContain('40')})})
describe('navigation and shell',()=>{
 it('sidebar item routes to a module page',async()=>{mock('ceo');open('/ceo');await screen.findByRole('heading',{level:1});const item=NAV.ceo[1][1][1]
  await userEvent.click(screen.getByRole('link',{name:item}));expect((await screen.findByRole('heading',{level:1})).textContent).toBe(item);expect(slug(item).length).toBeGreaterThan(0)})
 it('unknown module shows not-found state',async()=>{mock('ceo');open('/ceo/nope');expect(await screen.findByText('That page does not exist in this portal.')).toBeTruthy()})
 it('page search finds a sidebar page',async()=>{mock('coo');open('/coo');await screen.findByRole('heading',{level:1});await userEvent.type(screen.getByLabelText('Search pages'),'procure')
  expect(within(screen.getByRole('navigation',{name:'Main navigation'})).getAllByRole('link',{name:/Procurement/}).length).toBeGreaterThan(0);expect((await screen.findAllByText('Procurement')).length).toBeGreaterThan(1)})
 it('notifications panel says not configured',async()=>{mock('hr');open('/hr');await screen.findByRole('heading',{level:1});await userEvent.click(screen.getAllByRole('button',{name:/^Notifications/})[0]);expect(await screen.findByText('Notifications are not configured yet.')).toBeTruthy()})
 it('CEO sees read-only COO view; COO is bounced from CTO',async()=>{mock('ceo');open('/coo');expect(await screen.findByText(/Read-only view of the COO portal/)).toBeTruthy();cleanup();mock('coo');open('/cto');expect(await screen.findByRole('heading',{level:1,name:'COO Dashboard'})).toBeTruthy()})
 it('anonymous visitor lands on login; employee cannot open CEO',async()=>{mock(null);open('/ceo');expect(await screen.findByText('Welcome back')).toBeTruthy();cleanup();mock('employee');open('/ceo');await waitFor(()=>expect(screen.getByRole('heading',{level:1}).textContent).toContain('Employee'))})
 it('non-executive portal pages render the generic records workspace (no hardcoded rows)',async()=>{mock('technician');open('/technician/my-jobs');expect(await screen.findByText(/No records found/)).toBeTruthy()})})
describe('login page',()=>{it('remember off by default, forgot link; role comes from the server so there is no portal picker',async()=>{mock(null);open('/login');await screen.findByText('Welcome back')
 expect((screen.getByLabelText(/Remember me/) as HTMLInputElement).checked).toBe(false);expect(screen.getByRole('link',{name:'Forgot password?'}).getAttribute('href')).toBe('/forgot-password')
 expect(screen.queryByRole('combobox')).toBeNull();expect(screen.queryAllByRole('radio')).toHaveLength(0)})
 it('forgot-password never claims a reset happened',async()=>{vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,status:200,json:async()=>({configured:false,message:'Password reset by email is not configured yet.'})})));open('/forgot-password')
  await userEvent.type(await screen.findByLabelText(/Username/),'x');await userEvent.click(screen.getByRole('button',{name:'Request reset'}));expect(await screen.findByText(/not configured yet/)).toBeTruthy()})})
