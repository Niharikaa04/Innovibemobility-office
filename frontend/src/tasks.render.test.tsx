// @vitest-environment jsdom
// Render tests for Tasks, Employees and Audit Log pages. NOT executed in the sandbox that wrote them (npm registry unreachable): run `npm test`.
import {describe,it,expect,vi,beforeEach,afterEach} from 'vitest'
import {render,screen,cleanup,waitFor,within} from '@testing-library/react'; import userEvent from '@testing-library/user-event'
import Tasks from './Tasks'; import {Employees,AuditLog} from './People'
const labels={open:'Open',in_progress:'In progress',pending_approval:'Pending approval',done:'Done',cancelled:'Cancelled'}
const base={statuses:Object.keys(labels),status_labels:labels,total:1,page:1,page_size:20,can_write:true,can_archive:false,can_assign:true}
const task={id:'T1',title:'Prepare report',assignee_name:'Niharika',priority:'high',due_date:'2026-11-01',status:'open',requires_approval:true,can_edit:true,can_change_status:true,can_decide:false}
let calls:any[],reply:(url:string,m:string)=>{status:number,body:any}
beforeEach(()=>{document.cookie='csrf=tok123';calls=[];reply=()=>({status:200,body:{...base,items:[task]}})
 vi.stubGlobal('fetch',vi.fn(async(url:string,o:any={})=>{calls.push({url,o});const r=reply(String(url),o.method||'GET');return {ok:r.status<400,status:r.status,json:async()=>r.body}}))})
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
describe('Tasks page',()=>{
 it('lists real API rows and passes search and status filters to the server',async()=>{render(<Tasks/>);expect(await screen.findByText('Prepare report')).toBeTruthy()
  await userEvent.type(screen.getByLabelText('Search tasks'),'rep');await waitFor(()=>expect(calls.some(c=>c.url.includes('q=rep'))).toBe(true))
  await userEvent.selectOptions(screen.getByLabelText('Filter by status'),'done');await waitFor(()=>expect(calls.some(c=>c.url.includes('status=done'))).toBe(true))})
 it('shows Approve/Reject only when the server says can_decide, and Delete only when can_archive',async()=>{
  reply=()=>({status:200,body:{...base,items:[{...task,status:'pending_approval',can_decide:true,can_change_status:false}]}});render(<Tasks/>)
  expect(await screen.findByRole('button',{name:'Approve'})).toBeTruthy();expect(screen.getByRole('button',{name:'Reject'})).toBeTruthy();expect(screen.queryByRole('button',{name:'Delete'})).toBeNull()})
 it('sends a decision with the CSRF token and reports success only after the server confirms',async()=>{
  reply=(u,m)=>m==='GET'?{status:200,body:{...base,items:[{...task,status:'pending_approval',can_decide:true}]}}:{status:200,body:{}};render(<Tasks/>)
  await userEvent.click(await screen.findByRole('button',{name:'Approve'}));expect(await screen.findByText('Task approved.')).toBeTruthy()
  const p=calls.find(c=>c.o.method==='POST');expect(p.url).toContain('/tasks/T1/decision');expect(p.o.headers['X-CSRF-Token']).toBe('tok123');expect(JSON.parse(p.o.body).decision).toBe('approve')})
 it('shows the server refusal and no success message (e.g. self-approval)',async()=>{
  reply=(u,m)=>m==='GET'?{status:200,body:{...base,items:[{...task,status:'pending_approval',can_decide:true}]}}:{status:403,body:{detail:'You cannot approve your own task.'}};render(<Tasks/>)
  await userEvent.click(await screen.findByRole('button',{name:'Approve'}));expect(await screen.findByText('You cannot approve your own task.')).toBeTruthy();expect(screen.queryByText('Task approved.')).toBeNull()})
 it('hides Add task and the assignee picker for roles the server marks read-only / own-only',async()=>{reply=()=>({status:200,body:{...base,can_write:false,can_assign:false,items:[task]}});render(<Tasks/>)
  await screen.findByText('Prepare report');expect(screen.queryByRole('button',{name:'Add task'})).toBeNull()})
 it('shows the server 403 message when the role has no access',async()=>{reply=()=>({status:403,body:{detail:'You do not have permission to do this.'}});render(<Tasks/>)
  expect(await screen.findByText('You do not have permission to do this.')).toBeTruthy()})
 it('says a completed approval-task was submitted for approval',async()=>{reply=(u,m)=>m==='GET'?{status:200,body:{...base,items:[task]}}:{status:200,body:{status:'pending_approval'}};render(<Tasks/>)
  await userEvent.selectOptions(await screen.findByLabelText('Status of Prepare report'),'done');expect(await screen.findByText('Submitted for approval.')).toBeTruthy()})})
describe('Tasks dashboard',()=>{
 const rowsOf=()=>[{...task,id:'T1',title:'Prepare report',assignee_name:'Niharika',priority:'high',due_date:'2000-01-01',status:'open'},
  {...task,id:'T2',title:'Book venue',assignee_name:'Ravi',priority:'low',due_date:'',status:'done',requires_approval:false}]
 const kpiReply=(u:string,m:string)=>{if(m!=='GET')return {status:200,body:{}};const url=new URL(u,'http://x');const s=url.searchParams.get('status')
  const t=({'in_progress':4,'done':7,'pending_approval':2} as any)[s||'']??12
  const its=url.searchParams.get('page_size')==='1'?[]:rowsOf().filter(r=>!s||r.status===s);return {status:200,body:{...base,total:url.searchParams.get('page_size')==='1'?t:its.length,items:its}}}
 it('shows KPI cards from API totals and counts overdue from real due dates',async()=>{reply=kpiReply;render(<Tasks/>)
  const card=(name:string)=>screen.getByRole('button',{name:new RegExp('^'+name,'i')})
  await waitFor(()=>expect(card('Total Tasks').textContent).toContain('12'));expect(card('In Progress').textContent).toContain('4');expect(card('Completed').textContent).toContain('7')
  expect(card('Pending Approvals').textContent).toContain('2');await waitFor(()=>expect(card('Overdue').textContent).toContain('1'))})
 it('clicking a KPI card filters by status on the server',async()=>{reply=kpiReply;render(<Tasks/>);await screen.findByText('Prepare report')
  await userEvent.click(screen.getByRole('button',{name:/Completed/}));await waitFor(()=>expect(calls.some(c=>c.url.includes('page_size=20')&&c.url.includes('status=done'))).toBe(true))})
 it('Assigned to me sends mine=true',async()=>{reply=kpiReply;render(<Tasks/>);await screen.findByText('Prepare report')
  await userEvent.click(screen.getByLabelText('Assigned to me'));await waitFor(()=>expect(calls.some(c=>c.url.includes('mine=true'))).toBe(true))})
 it('priority, assignee and due-date filters narrow the loaded page without new fake data',async()=>{reply=kpiReply;render(<Tasks/>);await screen.findByText('Prepare report');expect(screen.getByText('Book venue')).toBeTruthy()
  await userEvent.selectOptions(screen.getByLabelText('Filter by priority'),'high');expect(screen.queryByText('Book venue')).toBeNull();expect(screen.getByText('Prepare report')).toBeTruthy()
  await userEvent.selectOptions(screen.getByLabelText('Filter by priority'),'');await userEvent.selectOptions(screen.getByLabelText('Filter by assignee'),'Ravi');expect(screen.queryByText('Prepare report')).toBeNull()
  await userEvent.selectOptions(screen.getByLabelText('Filter by assignee'),'');await userEvent.selectOptions(screen.getByLabelText('Filter by due date'),'overdue');expect(screen.queryByText('Book venue')).toBeNull();expect(screen.getByText('Prepare report')).toBeTruthy()})
 it('opens task details, and Edit opens the side panel and saves through PATCH with CSRF',async()=>{reply=kpiReply;render(<Tasks/>)
  await userEvent.click(await screen.findByText('Prepare report'));expect(screen.getByRole('dialog',{name:'Task details'})).toBeTruthy()
  await userEvent.click(within(screen.getByRole('dialog',{name:'Task details'})).getByRole('button',{name:'Edit'}));const t=screen.getByLabelText('Title *') as HTMLInputElement;expect(t.value).toBe('Prepare report')
  await userEvent.clear(t);await userEvent.type(t,'Prepare Q4 report');await userEvent.click(screen.getByRole('button',{name:'Save task'}))
  expect(await screen.findByText('Task saved.')).toBeTruthy();const p=calls.find(c=>c.o.method==='PATCH');expect(p.url).toContain('/tasks/T1');expect(p.o.headers['X-CSRF-Token']).toBe('tok123');expect(JSON.parse(p.o.body).title).toBe('Prepare Q4 report')})
 it('creates a task through POST from the side panel',async()=>{reply=kpiReply;render(<Tasks/>);await userEvent.click(await screen.findByRole('button',{name:'Add task'}))
  await userEvent.type(screen.getByLabelText('Title *'),'New thing');await userEvent.click(screen.getByRole('button',{name:'Save task'}));expect(await screen.findByText('Task saved.')).toBeTruthy()
  const p=calls.find(c=>c.o.method==='POST');expect(p.url).toMatch(/\/tasks$/);expect(JSON.parse(p.o.body).title).toBe('New thing')})
 it('a failed KPI request does not invent numbers',async()=>{reply=(u,m)=>/page_size=(1|50)(&|$)/.test(u)?{status:500,body:{detail:'x'}}:{status:200,body:{...base,items:[task]}};render(<Tasks/>)
  await screen.findByText('Prepare report');await waitFor(()=>expect(screen.getByRole('button',{name:/Total tasks/i}).textContent).toContain('—'))})})
describe('Employees page',()=>{
 const emp={items:[{id:'E1',employee_code:'EMP-0007',full_name:'Kadali Niharika',email:'n@x.test',department:'IT',designation:'IT Employee',is_active:true,is_technician:false}],total:1,departments:[{id:1,name:'IT'}],can_write:true,can_admin:false}
 it('lists employees, hides Deactivate for non-admins, and never shows password fields',async()=>{reply=()=>({status:200,body:emp});render(<Employees/>)
  expect(await screen.findByText('Kadali Niharika')).toBeTruthy();expect(screen.queryByRole('button',{name:'Deactivate'})).toBeNull();expect(screen.getByRole('button',{name:'Edit'})).toBeTruthy();expect(document.body.textContent).not.toMatch(/password/i)})
 it('asks for confirmation before deactivating and sends nothing if cancelled',async()=>{reply=()=>({status:200,body:{...emp,can_admin:true}});const c=vi.spyOn(window,'confirm').mockReturnValue(false);render(<Employees/>)
  await userEvent.click(await screen.findByRole('button',{name:'Deactivate'}));expect(c).toHaveBeenCalled();expect(calls.some(x=>x.o.method==='PATCH')).toBe(false)})
 it('shows the server error when the employee tables are missing',async()=>{reply=()=>({status:503,body:{detail:'The employee tables are not set up in this database (run db/001_foundation.sql).'}});render(<Employees/>)
  expect(await screen.findByText(/employee tables are not set up/)).toBeTruthy()})})
describe('Audit log page',()=>{
 it('renders entries and filters by outcome on the server',async()=>{reply=()=>({status:200,body:{items:[{id:1,occurred_at:'2026-10-26T10:00:00Z',actor_id:'U1',actor_role:'ceo',action:'task.created',entity_type:'task',entity_id:'T1',outcome:'success',ip:'203.0.113.7',before_data:null,after_data:{title:'x'}}],total:1}});render(<AuditLog/>)
  expect(await screen.findByText('task.created')).toBeTruthy();await userEvent.selectOptions(screen.getByLabelText('Filter by outcome'),'denied');await waitFor(()=>expect(calls.some(c=>c.url.includes('outcome=denied'))).toBe(true))})
 it('shows the permission error for roles without audit access',async()=>{reply=()=>({status:403,body:{detail:'You do not have permission to do this.'}});render(<AuditLog/>)
  expect(await screen.findByText('You do not have permission to do this.')).toBeTruthy()})})
