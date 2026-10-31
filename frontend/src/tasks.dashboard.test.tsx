// @vitest-environment jsdom
// Tests for the Tasks dashboard additions: real KPI figures, overdue rule, local-only filters, details panel, create flow.
import {describe,it,expect,vi,beforeEach,afterEach} from 'vitest'
import {render,screen,cleanup,waitFor,within} from '@testing-library/react'; import userEvent from '@testing-library/user-event'
import Tasks from './Tasks'
const labels={open:'Open',in_progress:'In progress',pending_approval:'Pending approval',done:'Done',cancelled:'Cancelled'}
const base={statuses:Object.keys(labels),status_labels:labels,page:1,page_size:20,can_write:true,can_archive:false,can_assign:false}
const iso=(off:number)=>{const d=new Date(Date.now()+off*864e5);return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`}
const mk=(id:string,o:any={})=>({id,title:'Task '+id,assignee_name:'Asha',priority:'normal',due_date:null,status:'open',requires_approval:false,can_edit:true,can_change_status:true,can_decide:false,...o})
let calls:{url:string;m:string;body?:any}[],db:any[]
// A tiny fake of GET /tasks: filters by status / q only (like the real server), pages by page_size, returns `total`.
function server(url:string,m:string){const u=new URL(url,'http://x'),st=u.searchParams.get('status'),q=(u.searchParams.get('q')||'').toLowerCase(),ps=+(u.searchParams.get('page_size')||20),pg=+(u.searchParams.get('page')||1)
 if(m!=='GET')return {status:200,body:{id:'N1'}}
 const rows=db.filter(r=>(!st||r.status===st)&&r.title.toLowerCase().includes(q));return {status:200,body:{...base,total:rows.length,page_size:ps,items:rows.slice((pg-1)*ps,pg*ps)}}}
beforeEach(()=>{document.cookie='csrf=tok';calls=[];db=[]
 vi.stubGlobal('fetch',vi.fn(async(url:string,o:any={})=>{const m=o.method||'GET';calls.push({url:String(url),m,body:o.body?JSON.parse(o.body):undefined});const r=server(String(url),m);return{ok:r.status<400,status:r.status,json:async()=>r.body}}))})
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
const kpi=(name:string)=>screen.getByRole('button',{name:new RegExp('^'+name)})
describe('KPI cards',()=>{
 it('show real counts from the API, and overdue only counts open / in-progress tasks past due',async()=>{
  db=[mk('1',{status:'open',due_date:iso(-2)}),mk('2',{status:'in_progress',due_date:iso(-1)}),mk('3',{status:'in_progress',due_date:iso(3)}),mk('4',{status:'done',due_date:iso(-5)}),mk('5',{status:'pending_approval',due_date:iso(-5)}),mk('6',{status:'cancelled',due_date:iso(-9)}),mk('7',{status:'open'})]
  render(<Tasks/>)
  await waitFor(()=>expect(kpi('Total tasks').textContent).toContain('7'));expect(kpi('In progress').textContent).toContain('2');expect(kpi('Completed').textContent).toContain('1')
  expect(kpi('Pending approvals').textContent).toContain('1');await waitFor(()=>expect(kpi('Overdue').textContent).toMatch(/Overdue\s*2/))})
 it('show — (not a made-up number) when the counts cannot be loaded',async()=>{vi.stubGlobal('fetch',vi.fn(async()=>({ok:false,status:500,json:async()=>({detail:'boom'})})));render(<Tasks/>)
  await screen.findByRole('alert');expect(kpi('Total tasks').textContent).toContain('—');expect(kpi('Overdue').textContent).toContain('—')})
 it('filter the table when clicked',async()=>{db=[mk('1',{status:'done'}),mk('2')];render(<Tasks/>);await screen.findByText('Task 2')
  await userEvent.click(kpi('Completed'));await waitFor(()=>expect(calls.some(c=>c.url.includes('page_size=20')&&c.url.includes('status=done'))).toBe(true));await waitFor(()=>expect(screen.queryByText('Task 2')).toBeNull());expect(screen.getByText('Task 1')).toBeTruthy()})})
describe('local-only filters',()=>{
 it('priority filter never sends an unsupported param to the server, and filters across all pages',async()=>{
  db=Array.from({length:45},(_,i)=>mk(String(i+1),{priority:i===42?'high':'low'}));render(<Tasks/>);await screen.findByText('Task 1')
  await userEvent.selectOptions(screen.getByLabelText('Filter by priority'),'high');await screen.findByText('Task 43')   // lives on the 3rd server page
  expect(screen.queryByText('Task 1')).toBeNull();expect(calls.every(c=>!/priority=|assignee=|due=/.test(c.url))).toBe(true);expect(screen.getByText(/Page 1 of 1 · 1 total/)).toBeTruthy()})
 it('due-date "Overdue" filter and assignee filter combine',async()=>{
  db=[mk('1',{due_date:iso(-1),assignee_name:'Asha'}),mk('2',{due_date:iso(-1),assignee_name:'Ravi'}),mk('3',{due_date:iso(4),assignee_name:'Asha'})];render(<Tasks/>);await screen.findByText('Task 1')
  await userEvent.selectOptions(screen.getByLabelText('Filter by due date'),'overdue');await waitFor(()=>expect(screen.queryByText('Task 3')).toBeNull())
  await userEvent.selectOptions(screen.getByLabelText('Filter by assignee'),'Ravi');await waitFor(()=>expect(screen.queryByText('Task 1')).toBeNull());expect(screen.getByText('Task 2')).toBeTruthy()
  await userEvent.click(screen.getByRole('button',{name:'Clear filters'}));expect(await screen.findByText('Task 3')).toBeTruthy()})
 it('says so when nothing matches',async()=>{db=[mk('1')];render(<Tasks/>);await screen.findByText('Task 1');await userEvent.selectOptions(screen.getByLabelText('Filter by priority'),'high');expect(await screen.findByText('No tasks match these filters.')).toBeTruthy()})})
describe('side panel',()=>{
 it('opens task details on title click, shows approval actions from the server flags, and closes with Escape',async()=>{
  db=[mk('1',{status:'pending_approval',can_decide:true,description:'Quarterly numbers',decision_note:'Check totals',requires_approval:true})];render(<Tasks/>)
  await userEvent.click(await screen.findByRole('button',{name:'Task 1'}));const dlg=await screen.findByRole('dialog',{name:'Task details'})
  expect(within(dlg).getByText('Quarterly numbers')).toBeTruthy();expect(within(dlg).getByText('Check totals')).toBeTruthy();expect(within(dlg).getByRole('button',{name:'Approve'})).toBeTruthy()
  await userEvent.keyboard('{Escape}');await waitFor(()=>expect(screen.queryByRole('dialog')).toBeNull())})
 it('creates a task from the panel with the existing POST payload and closes it',async()=>{db=[];render(<Tasks/>)
  await userEvent.click(await screen.findByRole('button',{name:'Add task'}));const dlg=await screen.findByRole('dialog',{name:'New task'})
  await userEvent.type(within(dlg).getByLabelText('Title *'),'Ship it');await userEvent.selectOptions(within(dlg).getByLabelText('Priority'),'high');await userEvent.click(within(dlg).getByRole('button',{name:'Save task'}))
  expect(await screen.findByText('Task saved.')).toBeTruthy();const p=calls.find(c=>c.m==='POST')!;expect(p.url).toMatch(/\/tasks$/);expect(p.body).toMatchObject({title:'Ship it',priority:'high',requires_approval:false});expect(screen.queryByRole('dialog')).toBeNull()})
 it('edits with PATCH and sends due_date null when the date is cleared',async()=>{db=[mk('1',{due_date:iso(2)})];render(<Tasks/>)
  await userEvent.click(await screen.findByRole('button',{name:'Edit'}));const dlg=await screen.findByRole('dialog',{name:'Edit task'});await userEvent.clear(within(dlg).getByLabelText('Due date'));await userEvent.click(within(dlg).getByRole('button',{name:'Save task'}))
  await screen.findByText('Task saved.');const p=calls.find(c=>c.m==='PATCH')!;expect(p.url).toContain('/tasks/1');expect(p.body.due_date).toBeNull()})})
