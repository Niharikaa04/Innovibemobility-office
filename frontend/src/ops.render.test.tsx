// @vitest-environment jsdom
// Render tests for the Service Tickets and Fleet Management pages (API mocked at fetch level).
import {describe,it,expect,vi,beforeEach,afterEach} from 'vitest'
import {render,screen,cleanup,waitFor,within} from '@testing-library/react'; import userEvent from '@testing-library/user-event'
import Tickets from './Tickets'; import Fleet from './Fleet'
const ticket={id:'T1',ticket_number:'IVT-ABC',title:'Battery not charging',description:'LED off',customer_name:'Acme',vehicle_reference:'KA01AB1234',priority:'HIGH',category:'BATTERY',status:'NEW',assigned_to:null,assigned_name:null,due_date:'2020-01-01',created_at:'2026-10-01T00:00:00Z',updated_at:'2026-10-01T00:00:00Z',resolved_at:null,next_states:['TRIAGED'],can_edit:true,overdue:true}
const tList={items:[ticket],total:1,statuses:['NEW','TRIAGED'],priorities:[],categories:[],can_write:true,can_assign:true,can_export:true}
const tSum={total:1,unassigned:1,overdue:1,urgent_open:0,groups:{open:1,in_progress:0,waiting:0,completed:0}}
const vehicle={id:'V1',registration_number:'KA 01 AB 1234',vehicle_type:'THREE_WHEELER',make:'Mahindra',model:'Treo',battery_capacity_kwh:'7.37',status:'ACTIVE',vin:null,manufacture_year:null,customer_name:'Acme Logistics',odometer_km:null,notes:'',last_service:'2026-02-10',created_at:'2026-10-01T00:00:00Z',updated_at:'2026-10-01T00:00:00Z'}
const fList={items:[vehicle],total:1,vehicle_types:[],statuses:[],can_write:true,can_export:true,can_archive:true}
const fSum={total:1,total_kwh:7.37,by_status:{ACTIVE:1},by_type:{THREE_WHEELER:1}}
const fDet={vehicle,service_history:[{id:1,service_date:'2026-02-10',service_type:'Brake pads',description:'',cost:'500.00',odometer_km:null,technician_name:'Ravi',ticket_id:null}],tickets:[],total_service_cost:500,can_write:true,can_archive:true}
let calls:any[],reply:(url:string,m:string)=>{status:number,body:any}
beforeEach(()=>{document.cookie='csrf=tok123';calls=[]
 vi.stubGlobal('fetch',vi.fn(async(url:string,o:any={})=>{calls.push({url:String(url),o});const r=reply(String(url),o.method||'GET');return {ok:r.status<400,status:r.status,json:async()=>r.body,blob:async()=>new Blob(['x'])}}))})
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
const ticketReply=(u:string,m:string)=>u.includes('/summary')?{status:200,body:tSum}:u.includes('/technicians')?{status:200,body:{items:[{id:'U1',name:'Ravi'}]}}:/service-tickets\/T1$/.test(u)?{status:200,body:{ticket,history:[{id:1,event_type:'created',actor_name:'Sam',actor_id:'1',detail:{priority:'HIGH',category:'BATTERY'},created_at:'2026-10-01T00:00:00Z'}],comments:[]}}:m==='GET'?{status:200,body:tList}:{status:200,body:{}}
describe('Service tickets',()=>{
 beforeEach(()=>{reply=ticketReply})
 it('shows summary cards, rows with category/priority/status and flags overdue',async()=>{render(<Tickets/>)
  expect(await screen.findByText('Battery not charging')).toBeTruthy();expect(screen.getByText('IVT-ABC')).toBeTruthy();expect(screen.getByRole('cell',{name:'Battery'})).toBeTruthy();expect(screen.getByText(/\(overdue\)/)).toBeTruthy()
  const cards=within(screen.getByLabelText('Ticket summary'));expect(cards.getByRole('button',{name:/Overdue/})).toBeTruthy()})
 it('sends search and filters to the server and a summary card applies its filter',async()=>{render(<Tickets/>);await screen.findByText('Battery not charging')
  await userEvent.selectOptions(screen.getByLabelText('Filter by priority'),'HIGH');await waitFor(()=>expect(calls.some(c=>c.url.includes('priority=HIGH'))).toBe(true))
  await userEvent.selectOptions(screen.getByLabelText('Filter by category'),'BATTERY');await waitFor(()=>expect(calls.some(c=>c.url.includes('category=BATTERY'))).toBe(true))
  await userEvent.click(within(screen.getByLabelText('Ticket summary')).getByRole('button',{name:/Overdue/}));await waitFor(()=>expect(calls.some(c=>c.url.includes('overdue=true'))).toBe(true))
  await userEvent.type(screen.getByLabelText('Search tickets'),'acme{enter}');await waitFor(()=>expect(calls.some(c=>c.url.includes('q=acme'))).toBe(true))})
 it('creates a ticket with CSRF token and category/due date',async()=>{render(<Tickets/>);await userEvent.click(await screen.findByRole('button',{name:'New ticket'}))
  const form=within(screen.getByRole('form',{name:'New ticket'}));await userEvent.type(form.getByLabelText(/Title/),'Noise from motor');await userEvent.selectOptions(form.getByLabelText('Category'),'MOTOR');await userEvent.click(form.getByRole('button',{name:'Create ticket'}))
  expect(await screen.findByText('Ticket created.')).toBeTruthy();const p=calls.find(c=>c.o.method==='POST');expect(p.url).toContain('/service-tickets');expect(p.o.headers['X-CSRF-Token']).toBe('tok123');const b=JSON.parse(p.o.body);expect(b.title).toBe('Noise from motor');expect(b.category).toBe('MOTOR')})
 it('edits through PATCH',async()=>{render(<Tickets/>);await userEvent.click(await screen.findByRole('button',{name:'Edit IVT-ABC'}))
  const t=screen.getByLabelText(/Title/) as HTMLInputElement;expect(t.value).toBe('Battery not charging');await userEvent.clear(t);await userEvent.type(t,'Charger fault');await userEvent.click(screen.getByRole('button',{name:'Save changes'}))
  expect(await screen.findByText('Ticket updated.')).toBeTruthy();const p=calls.find(c=>c.o.method==='PATCH');expect(p.url).toContain('/service-tickets/T1');expect(JSON.parse(p.o.body).title).toBe('Charger fault')})
 it('opens detail with history, only offers server-approved next statuses, and assigns a technician',async()=>{render(<Tickets/>);await userEvent.click(await screen.findByRole('button',{name:'Open IVT-ABC'}))
  expect(await screen.findByText(/Ticket created \(High, Battery\)/)).toBeTruthy()
  const move=screen.getByLabelText('Update status');expect(within(move).getAllByRole('option').map(o=>o.textContent)).toEqual(['Move to…','Triaged'])
  await userEvent.selectOptions(screen.getByLabelText('Assign technician'),'U1');await waitFor(()=>expect(calls.some(c=>c.url.endsWith('/T1/assign')&&JSON.parse(c.o.body).assigned_to==='U1')).toBe(true))
  await userEvent.selectOptions(move,'TRIAGED');await waitFor(()=>expect(calls.some(c=>c.url.endsWith('/T1/transition')&&JSON.parse(c.o.body).status==='TRIAGED')).toBe(true))})
 it('hides create/edit/assign/export for read-only roles',async()=>{reply=(u,m)=>u.includes('/summary')?{status:200,body:tSum}:{status:200,body:{...tList,items:[{...ticket,can_edit:false,next_states:[]}],can_write:false,can_assign:false,can_export:false}};render(<Tickets/>)
  await screen.findByText('Battery not charging');expect(screen.queryByRole('button',{name:'New ticket'})).toBeNull();expect(screen.queryByRole('button',{name:'Export CSV'})).toBeNull();expect(screen.queryByRole('button',{name:'Edit IVT-ABC'})).toBeNull()})
 it('shows the server refusal for an invalid transition',async()=>{const base=ticketReply;reply=(u,m)=>m==='POST'?{status:409,body:{detail:'Transition NEW → CLOSED is not allowed for your role.'}}:base(u,m);render(<Tickets/>)
  await userEvent.click(await screen.findByRole('button',{name:'Open IVT-ABC'}));await userEvent.selectOptions(await screen.findByLabelText('Update status'),'TRIAGED');expect(await screen.findByText(/is not allowed for your role/)).toBeTruthy()})
 it('exports CSV through the filtered export endpoint',async()=>{const create=vi.fn(()=>'blob:x');(URL as any).createObjectURL=create;(URL as any).revokeObjectURL=vi.fn();render(<Tickets/>)
  await userEvent.click(await screen.findByRole('button',{name:'Export CSV'}));await waitFor(()=>expect(calls.some(c=>c.url.includes('/service-tickets/export'))).toBe(true))})
 it('shows the server 403 when the role has no access',async()=>{reply=()=>({status:403,body:{detail:'You do not have permission to view service tickets.'}});render(<Tickets/>);expect(await screen.findByText(/do not have permission to view service tickets/)).toBeTruthy()})
})
describe('Fleet management',()=>{
 beforeEach(()=>{reply=(u,m)=>u.includes('/fleet/summary')?{status:200,body:fSum}:/fleet\/vehicles\/V1$/.test(u)&&m==='GET'?{status:200,body:fDet}:m==='GET'?{status:200,body:fList}:{status:200,body:{}}})
 it('lists vehicles with type, battery and status plus summary cards',async()=>{render(<Fleet/>)
  expect(await screen.findByRole('button',{name:'Open KA 01 AB 1234'})).toBeTruthy();expect(screen.getByText('Mahindra Treo')).toBeTruthy();expect(screen.getByText('7.37')).toBeTruthy();expect(within(screen.getByLabelText('Fleet summary')).getByRole('button',{name:/Active/})).toBeTruthy()})
 it('adds a vehicle with numeric battery capacity and CSRF',async()=>{render(<Fleet/>);await userEvent.click(await screen.findByRole('button',{name:'Add vehicle'}))
  await userEvent.type(screen.getByLabelText(/Registration number/),'MH12XY9999');await userEvent.type(screen.getByLabelText(/Make/),'Tata');await userEvent.type(screen.getByLabelText(/Model/),'Ace EV');await userEvent.type(screen.getByLabelText(/Battery capacity/),'21.3')
  await userEvent.click(within(screen.getByRole('form',{name:'Add vehicle'})).getByRole('button',{name:'Add vehicle'}))
  expect(await screen.findByText('Vehicle added.')).toBeTruthy();const p=calls.find(c=>c.o.method==='POST');expect(p.url).toContain('/fleet/vehicles');expect(p.o.headers['X-CSRF-Token']).toBe('tok123');const b=JSON.parse(p.o.body);expect(b.battery_capacity_kwh).toBe(21.3);expect(b.registration_number).toBe('MH12XY9999')})
 it('shows the duplicate-registration error from the server',async()=>{const base=reply;reply=(u,m)=>m==='POST'?{status:409,body:{detail:'A vehicle with this registration number already exists.'}}:base(u,m);render(<Fleet/>)
  await userEvent.click(await screen.findByRole('button',{name:'Add vehicle'}));await userEvent.type(screen.getByLabelText(/Registration number/),'MH12XY9999');await userEvent.type(screen.getByLabelText(/Make/),'Tata');await userEvent.type(screen.getByLabelText(/Model/),'Ace')
  await userEvent.click(within(screen.getByRole('form',{name:'Add vehicle'})).getByRole('button',{name:'Add vehicle'}));expect(await screen.findByText(/already exists/)).toBeTruthy()})
 it('opens vehicle details with service history and changes status',async()=>{render(<Fleet/>);await userEvent.click(await screen.findByRole('button',{name:'Open KA 01 AB 1234'}))
  expect(await screen.findByText('Brake pads')).toBeTruthy();expect(screen.getByText('Service history (1)')).toBeTruthy()
  await userEvent.selectOptions(screen.getByLabelText('Change vehicle status'),'IDLE');await waitFor(()=>expect(calls.some(c=>c.o.method==='PATCH'&&JSON.parse(c.o.body).status==='IDLE')).toBe(true))})
 it('passes search and filters to the server',async()=>{render(<Fleet/>);await screen.findByRole('button',{name:'Open KA 01 AB 1234'})
  await userEvent.selectOptions(screen.getByLabelText('Filter by vehicle type'),'BUS');await waitFor(()=>expect(calls.some(c=>c.url.includes('vehicle_type=BUS'))).toBe(true))
  await userEvent.selectOptions(screen.getByLabelText('Filter by status'),'IDLE');await waitFor(()=>expect(calls.some(c=>c.url.includes('status=IDLE'))).toBe(true))
  await userEvent.type(screen.getByLabelText('Search vehicles'),'treo{enter}');await waitFor(()=>expect(calls.some(c=>c.url.includes('q=treo'))).toBe(true))})
 it('hides write, archive and export controls for read-only roles',async()=>{reply=(u,m)=>u.includes('/summary')?{status:200,body:fSum}:{status:200,body:{...fList,can_write:false,can_export:false,can_archive:false}};render(<Fleet/>)
  await screen.findByRole('button',{name:'Open KA 01 AB 1234'});for(const n of ['Add vehicle','Export CSV','Edit KA 01 AB 1234','Archive KA 01 AB 1234'])expect(screen.queryByRole('button',{name:n})).toBeNull()})
})
