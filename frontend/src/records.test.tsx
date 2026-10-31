// @vitest-environment jsdom
import {describe,it,expect,vi,beforeEach} from 'vitest'
import {render,screen,waitFor,within,cleanup} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {api} from './api'
import StartupMetrics from './StartupMetrics'
import ReportsAnalytics from './ReportsAnalytics'
import KpiCenter from './KpiCenter'
import BusinessOverview from './BusinessOverview'
vi.mock('./api')
const rec={id:'1',title:'Oct metrics',status:'Open',description:'d',amount:null,due_date:null,fields:{monthly_burn:100,monthly_revenue:300},created_at:'2026-10-01T00:00:00Z'}
let calls:{p:string;m:string;b?:any}[]=[]
let fail:string|null=null
beforeEach(()=>{cleanup();calls=[];fail=null;vi.spyOn(window,'confirm').mockReturnValue(true)
 ;(api as any).call=vi.fn(async(p:string,m:string,b?:any)=>{calls.push({p,m,b});if(fail&&m!=='GET')throw new Error(fail)
  if(p.includes('/export'))return {items:[rec],count:1,truncated:false}
  if(p.includes('/summary'))return {total:1,open:1,completed:0,lost:0,amount_total:0,statuses:[{status:'Open',count:1}]}
  if(m==='GET')return {items:[rec],total:1}
  return {}})
 ;(URL as any).createObjectURL=vi.fn(()=>'blob:x');(URL as any).revokeObjectURL=vi.fn()})
describe('shared engine',()=>{
 it('has no inner h2 heading (page title comes from the shell)',async()=>{render(<StartupMetrics title="Startup Metrics"/>);await screen.findByText('Oct metrics');expect(document.querySelector('.sm-head h2')).toBeNull();expect(screen.getByText(/Financial health and growth/)).toBeTruthy()})
 it('create posts to the right module and shows success',async()=>{const u=userEvent.setup();render(<StartupMetrics title="Startup Metrics"/>);await screen.findByText('Oct metrics')
  await u.type(screen.getByPlaceholderText('Enter title'),'New one');await u.click(screen.getByRole('button',{name:/create record/i}))
  await waitFor(()=>expect(calls.some(c=>c.m==='POST'&&c.p==='/workspaces/startup-metrics/records'&&c.b.title==='New one')).toBe(true));expect(await screen.findByRole('status')).toHaveProperty('textContent','Startup Metric Record created.')})
 it('API failure on create is shown, not a fake success',async()=>{const u=userEvent.setup();fail='Forbidden';render(<StartupMetrics title="Startup Metrics"/>);await screen.findByText('Oct metrics')
  await u.type(screen.getByPlaceholderText('Enter title'),'X');await u.click(screen.getByRole('button',{name:/create record/i}))
  expect((await screen.findAllByRole('alert')).some(a=>a.textContent==='Forbidden')).toBe(true);expect(screen.queryByRole('status')).toBeNull()})
 it('rejects churn > 100 client side',async()=>{const u=userEvent.setup();render(<StartupMetrics title="Startup Metrics"/>);await screen.findByText('Oct metrics')
  await u.type(screen.getByPlaceholderText('Enter title'),'X');await u.type(screen.getByPlaceholderText('Enter percentage'),'150');await u.click(screen.getByRole('button',{name:/create record/i}))
  expect(calls.some(c=>c.m==='POST')).toBe(false)})
 it('edit populates form and PATCHes',async()=>{const u=userEvent.setup();Element.prototype.scrollIntoView=vi.fn();render(<StartupMetrics title="Startup Metrics"/>);await screen.findByText('Oct metrics')
  await u.click(screen.getByLabelText('Edit Oct metrics'));expect((screen.getByPlaceholderText('Enter title') as HTMLInputElement).value).toBe('Oct metrics')
  await u.click(screen.getByRole('button',{name:/save changes/i}));await waitFor(()=>expect(calls.some(c=>c.m==='PATCH'&&c.p.endsWith('/records/1'))).toBe(true))})
 it('archive confirms then DELETEs and refreshes',async()=>{const u=userEvent.setup();render(<StartupMetrics title="Startup Metrics"/>);await screen.findByText('Oct metrics')
  await u.click(screen.getByLabelText('Archive Oct metrics'));await waitFor(()=>expect(calls.some(c=>c.m==='DELETE')).toBe(true));expect(window.confirm).toHaveBeenCalled()})
 it('archive cancelled does nothing',async()=>{const u=userEvent.setup();(window.confirm as any).mockReturnValue(false);render(<StartupMetrics title="Startup Metrics"/>);await screen.findByText('Oct metrics')
  await u.click(screen.getByLabelText('Archive Oct metrics'));expect(calls.some(c=>c.m==='DELETE')).toBe(false)})
 it('search + status filter + clear reach the API with the right params',async()=>{const u=userEvent.setup();render(<StartupMetrics title="Startup Metrics"/>);await screen.findByText('Oct metrics')
  await u.type(screen.getByLabelText('Search records'),'abc{Enter}');await waitFor(()=>expect(calls.some(c=>c.p.includes('q=abc'))).toBe(true))
  await u.click(within(screen.getByLabelText('Status breakdown')).getByRole('button'));await waitFor(()=>expect(calls.some(c=>c.p.includes('status=Open'))).toBe(true))
  calls=[];await u.click(screen.getByRole('button',{name:'Clear filters'}));await waitFor(()=>expect(calls.some(c=>/\/workspaces\/startup-metrics\?q=&page=1&limit=25$/.test(c.p))).toBe(true))})
 it('date range preset filters table, summary and export',async()=>{const u=userEvent.setup();render(<StartupMetrics title="Startup Metrics"/>);await screen.findByText('Oct metrics')
  await u.click(screen.getByRole('button',{name:/all time/i}));await u.click(screen.getByRole('button',{name:'This year'}))
  await waitFor(()=>expect(calls.some(c=>c.p.includes('/summary?date_from=')&&c.p.includes('date_to='))).toBe(true));expect(calls.some(c=>c.p.includes('/export?date_from='))).toBe(true)})
 it('CSV export uses active filters and downloads',async()=>{const u=userEvent.setup();render(<StartupMetrics title="Startup Metrics"/>);await screen.findByText('Oct metrics')
  await u.type(screen.getByLabelText('Search records'),'abc{Enter}');calls=[];await u.click(screen.getByRole('button',{name:/export all matching csv/i}))
  await waitFor(()=>expect(calls.some(c=>c.p.startsWith('/workspaces/startup-metrics/export?q=abc'))).toBe(true));expect(URL.createObjectURL).toHaveBeenCalled()})
 it('reports: period end before start is blocked',async()=>{const u=userEvent.setup();render(<ReportsAnalytics title="Reports & Analytics"/>);await screen.findByText('Oct metrics')
  await u.type(screen.getByPlaceholderText('Enter title'),'R');const d=document.querySelectorAll('.sm-grid input[type=date]');await u.type(d[1] as HTMLElement,'2026-10-10');await u.type(d[2] as HTMLElement,'2026-10-01')
  await u.click(screen.getByRole('button',{name:/^\s*create record/i}));expect(await screen.findByText('Period end cannot be before period start.')).toBeTruthy();expect(calls.some(c=>c.m==='POST')).toBe(false)})
 it('load failure shows error + Retry, not a fake empty list',async()=>{;(api as any).call=vi.fn(async()=>{throw new Error('Server down')});render(<StartupMetrics title="Startup Metrics"/>)
  expect(await screen.findByText(/Records could not be loaded/)).toBeTruthy();expect(screen.getAllByText(/Server down/).length).toBeGreaterThan(0);expect(screen.getAllByRole('button',{name:'Retry'}).length).toBe(1)})
})

describe('clickable cards + per-module design',()=>{
 it('reports: status cards filter, Overdue/Completed show none, Total restores',async()=>{const u=userEvent.setup();Element.prototype.scrollIntoView=vi.fn();render(<ReportsAnalytics title="Reports & Analytics"/>);await screen.findByText('Oct metrics')
  await u.click(screen.getByTitle('Show: Completed'));expect(await screen.findByText(/No records found/)).toBeTruthy()
  await u.click(screen.getByTitle('Show: Open / Pending'));expect(await screen.findByText('Oct metrics')).toBeTruthy()
  await u.click(screen.getByTitle('Show: Overdue reports'));expect(await screen.findByText(/No records found/)).toBeTruthy()
  await u.click(screen.getByTitle('Show all records'));expect(await screen.findByText('Oct metrics')).toBeTruthy();expect(document.querySelector('.sm-bucket')).toBeNull()})
 it('card filter + CSV export exports only the filtered set (client-side)',async()=>{const u=userEvent.setup();render(<ReportsAnalytics title="Reports & Analytics"/>);await screen.findByText('Oct metrics')
  await u.click(screen.getByTitle('Show: Completed'));calls=[];await u.click(screen.getByRole('button',{name:/export all matching csv/i}));expect(await screen.findByText(/nothing to export/)).toBeTruthy();expect(calls.some(c=>c.p.includes('/export'))).toBe(false)})
 it('each module has its own cards (labels differ) and no generic Total amount card',async()=>{const labels:string[][]=[]
  for(const [C,t] of [[StartupMetrics,'Startup Metrics'],[KpiCenter,'KPI Center'],[BusinessOverview,'Business Overview'],[ReportsAnalytics,'Reports & Analytics']] as const){cleanup();render(<C title={t}/>);await screen.findByText('Oct metrics')
   labels.push(Array.from(document.querySelectorAll('.sm-cards .sm-lbl')).map(x=>x.textContent||''));expect(document.body.textContent).not.toContain('Total amount')}
  expect(labels[0]).toContain('Cash balance');expect(labels[1]).toContain('At risk');expect(labels[2]).toContain('Departments');expect(labels[3]).toContain('Scheduled')
  expect(new Set(labels.map(l=>l.join('|'))).size).toBe(4)})
 it('every card that is a button filters; the runway card is a plain box',async()=>{cleanup();render(<StartupMetrics title="Startup Metrics"/>);await screen.findByText('Oct metrics')
  expect(document.querySelectorAll('.sm-cards button.sm-click').length).toBe(5);expect(document.querySelectorAll('.sm-cards div.sm-card').length).toBe(1)})
 it('startup form has finance fields and no generic Amount / Due date',async()=>{render(<StartupMetrics title="Startup Metrics"/>);await screen.findByText('Oct metrics')
  const f=document.querySelector('form')!.textContent||'';expect(f).toContain('Monthly revenue');expect(f).toContain('Cash balance');expect(f).not.toContain('Amount (₹)');expect(f).not.toContain('Due date')})
 it('KPI: achievement rule 100/80 and unmeasurable records',async()=>{const mk=(id:string,t:number|null,a:number|null,dep='Ops')=>({...rec,id,title:'K'+id,fields:{target:t,actual:a,unit:'%',department:dep,period:'2026-10'}})
  const data=[mk('1',100,120),mk('2',100,85),mk('3',100,40),mk('4',0,5),mk('5',null,null)]
  ;(api as any).call=vi.fn(async(p:string,m:string)=>{if(p.includes('/summary'))return {total:5,open:5,completed:0,lost:0,amount_total:0,statuses:[]};if(p.includes('/export'))return {items:data,count:5,truncated:false};return {items:data,total:5}})
  render(<KpiCenter title="KPI Center"/>);await screen.findAllByText('K1')
  const val=(l:string)=>Array.from(document.querySelectorAll('.sm-cards .sm-card')).find(c=>c.querySelector('.sm-lbl')?.textContent===l)!.querySelector('strong')!.textContent
  expect(val('Achieved')).toBe('1');expect(val('On track')).toBe('1');expect(val('At risk')).toBe('1');expect(val('Total KPIs')).toBe('5');expect(screen.getByText(/2 not measurable/)).toBeTruthy()
  expect(document.querySelectorAll('.sm-badge.gray').length).toBeGreaterThanOrEqual(2);expect(screen.getByText('Department Performance (avg achievement %)')).toBeTruthy()})
})
