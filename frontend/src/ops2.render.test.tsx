// @vitest-environment jsdom
// Render tests for Garages, Technicians, EVcare.AI Diagnostics and IoT & Telemetry (API mocked at fetch level, same harness as ops.render.test.tsx).
import {describe,it,expect,vi,beforeEach,afterEach} from 'vitest'
import {render,screen,cleanup,waitFor,within} from '@testing-library/react'; import userEvent from '@testing-library/user-event'
import Garages from './Garages'; import Technicians from './Technicians'; import Diagnostics from './Diagnostics'; import Iot from './Iot'
let calls:any[],reply:(url:string,m:string)=>{status:number,body:any}
beforeEach(()=>{document.cookie='csrf=tok123';calls=[]
 vi.stubGlobal('fetch',vi.fn(async(url:string,o:any={})=>{calls.push({url:String(url),o});const r=reply(String(url),o.method||'GET');return {ok:r.status<400,status:r.status,json:async()=>r.body,blob:async()=>new Blob(['x'])}}))})
afterEach(()=>{cleanup();vi.unstubAllGlobals()})

const center={id:'C1',center_code:'SC-00001',name:'Hyderabad Hub',address:'1 Main Rd',city:'Hyderabad',state:null,contact_person:'Asha',phone:'+91 99999 00000',email:null,supported_services:['BATTERY','MOTOR'],status:'ACTIVE',notes:'',technician_count:2,open_tickets:3,created_at:'2026-10-01T00:00:00Z',updated_at:'2026-10-01T00:00:00Z'}
const gList={items:[center],total:1,statuses:[],services:[],can_write:true,can_export:true,can_archive:true}
const gSum={total:1,cities:1,by_status:{ACTIVE:1},assigned_technicians:2,open_tickets:3}
const gDet={center,technicians:[{id:'T1',name:'Ravi',specialization:'Battery',skills:[],availability:'BUSY',is_active:true,open_tickets:2}],tickets:[{id:'K1',ticket_number:'IVT-1',title:'Charger dead',status:'NEW',priority:'HIGH',assigned_name:null,created_at:'2026-10-02T00:00:00Z'}],service_history:[{id:'K0',ticket_number:'IVT-0',title:'Old brake job',status:'CLOSED',priority:'LOW',assigned_name:'Ravi',vehicle_reference:'KA01AB1234',created_at:'2026-09-01T00:00:00Z',resolved_at:'2026-09-03T00:00:00Z'}],can_write:true,can_archive:true,can_assign_technicians:true}
describe('Garages',()=>{
 beforeEach(()=>{reply=(u,m)=>u.includes('/garages/summary')?{status:200,body:gSum}:/\/garages\/C1$/.test(u)&&m==='GET'?{status:200,body:gDet}:u.includes('/technicians')||u.includes('/service-tickets')?{status:200,body:{items:[]}}:m==='GET'?{status:200,body:gList}:{status:200,body:{}}})
 it('lists centers with services, technician and ticket counts',async()=>{render(<Garages/>)
  expect(await screen.findByRole('button',{name:'Open Hyderabad Hub'})).toBeTruthy();expect(screen.getByText('Battery, Motor')).toBeTruthy();expect(within(screen.getByLabelText('Service center summary')).getByRole('button',{name:/Assigned technicians/})).toBeTruthy()})
 it('adds a center with chosen services and CSRF',async()=>{render(<Garages/>);await userEvent.click(await screen.findByRole('button',{name:'Add service center'}))
  const f=within(screen.getByRole('form',{name:'Add service center'}));await userEvent.type(f.getByLabelText(/Name/),'Pune Point');await userEvent.click(f.getByLabelText('Brakes'));await userEvent.click(f.getByRole('button',{name:'Add service center'}))
  expect(await screen.findByText('Service center added.')).toBeTruthy();const p=calls.find(c=>c.o.method==='POST');expect(p.o.headers['X-CSRF-Token']).toBe('tok123');const b=JSON.parse(p.o.body);expect(b.name).toBe('Pune Point');expect(b.supported_services).toEqual(['BRAKES'])})
 it('sends filters to the server',async()=>{render(<Garages/>);await screen.findByRole('button',{name:'Open Hyderabad Hub'})
  await userEvent.selectOptions(screen.getByLabelText('Filter by service'),'BATTERY');await waitFor(()=>expect(calls.some(c=>c.url.includes('service=BATTERY'))).toBe(true))
  await userEvent.type(screen.getByLabelText('Filter by city'),'pune');await waitFor(()=>expect(calls.some(c=>c.url.includes('city=pune'))).toBe(true))})
 it('shows technicians and related tickets in the detail view',async()=>{render(<Garages/>);await userEvent.click(await screen.findByRole('button',{name:'Open Hyderabad Hub'}))
  expect(await screen.findByText('Ravi')).toBeTruthy();expect(screen.getByText('Charger dead')).toBeTruthy();expect(screen.getByText('Technicians (1)')).toBeTruthy()
  expect(screen.getByText('Service history (1)')).toBeTruthy();expect(screen.getByText('Old brake job')).toBeTruthy();expect(screen.getAllByText('SC-00001').length).toBeGreaterThan(1)})   // ID shown in list and detail
 it('hides write/export/archive controls for read-only roles',async()=>{reply=(u)=>u.includes('/summary')?{status:200,body:gSum}:{status:200,body:{...gList,can_write:false,can_export:false,can_archive:false}};render(<Garages/>)
  await screen.findByRole('button',{name:'Open Hyderabad Hub'});for(const n of ['Add service center','Export CSV','Edit Hyderabad Hub','Archive Hyderabad Hub'])expect(screen.queryByRole('button',{name:n})).toBeNull()})
})

const tech={id:'T1',employee_id:'E1',employee_code:'EMP7',name:'Ravi Kumar',email:'r@x.test',phone:null,designation:null,skills:['Battery','Motor'],specialization:'EV drivetrain',availability:'AVAILABLE',is_active:true,notes:'',service_center_id:'C1',service_center:'Hyderabad Hub',user_id:'U1',assigned_tickets:9,pending_tickets:1,in_progress_tickets:1,completed_tickets:7,open_tickets:2,created_at:null,updated_at:'2026-10-01T00:00:00Z'}
const tList={items:[tech],total:1,availability:[],centers:[{id:'C1',name:'Hyderabad Hub'}],can_write:true,can_export:true,can_assign:true,can_see_contact:true}
const tWl={items:[{id:'T1',name:'Ravi Kumar',service_center:'Hyderabad Hub',availability:'AVAILABLE',has_login:true,pending:1,in_progress:1,completed:7,open:2}],unassigned_open_tickets:4,total_open:2}
const tSum={total:1,active:1,without_center:0,by_availability:{AVAILABLE:1},open_assigned_tickets:2,unassigned_open_tickets:4}
describe('Technicians',()=>{
 beforeEach(()=>{reply=(u,m)=>u.includes('/technicians/summary')?{status:200,body:tSum}:u.includes('/technicians/workload')?{status:200,body:tWl}:u.includes('/candidates')?{status:200,body:{items:[{id:'E9',employee_code:'EMP9',name:'New Hire',designation:null}]}}:u.includes('assigned=unassigned')?{status:200,body:{items:[{id:'K9',ticket_number:'IVT-9',title:'Brake noise',status:'NEW'}]}}:/technicians\/T1$/.test(u)&&m==='GET'?{status:200,body:{technician:tech,tickets:[],can_write:true,can_assign:true}}:m==='GET'?{status:200,body:tList}:{status:200,body:{}}})
 it('shows workload, skills and service center',async()=>{render(<Technicians/>);expect(await screen.findByRole('button',{name:'Open Ravi Kumar'})).toBeTruthy();expect(screen.getByText('Battery, Motor')).toBeTruthy();expect(screen.getByText('EMP7')).toBeTruthy();expect(screen.getByRole('img',{name:'Ravi Kumar: 1 pending, 1 in progress'})).toBeTruthy();expect(screen.getByText(/4 open ticket\(s\) are not assigned/)).toBeTruthy();expect(screen.getAllByText('Hyderabad Hub').length).toBeGreaterThan(0)})
 it('adds a technician from an existing employee, splitting skills',async()=>{render(<Technicians/>);await userEvent.click(await screen.findByRole('button',{name:'Add technician'}))
  const f=within(screen.getByRole('form',{name:'Add technician'}));await userEvent.selectOptions(await f.findByLabelText('Employee'),'E9');await userEvent.type(f.getByLabelText(/Skills/),'Battery, , Charger ');await userEvent.click(f.getByRole('button',{name:'Add technician'}))
  expect(await screen.findByText('Technician added.')).toBeTruthy();const b=JSON.parse(calls.find(c=>c.o.method==='POST').o.body);expect(b.employee_id).toBe('E9');expect(b.skills).toEqual(['Battery','Charger'])})
 it('assigns an unassigned ticket through the existing ticket assign endpoint',async()=>{render(<Technicians/>);await userEvent.click(await screen.findByRole('button',{name:'Open Ravi Kumar'}))
  await screen.findByRole('option',{name:/IVT-9/});await userEvent.selectOptions(screen.getByLabelText('Assign ticket to this technician'),'K9');await waitFor(()=>expect(calls.some(c=>c.url.endsWith('/service-tickets/K9/assign')&&JSON.parse(c.o.body).assigned_to==='U1')).toBe(true))})
 it('explains why a technician without a login account cannot receive tickets',async()=>{const base=reply;reply=(u,m)=>/technicians\/T1$/.test(u)&&m==='GET'?{status:200,body:{technician:{...tech,user_id:null},tickets:[],can_write:true,can_assign:true}}:base(u,m);render(<Technicians/>)
  await userEvent.click(await screen.findByRole('button',{name:'Open Ravi Kumar'}));expect(await screen.findByText(/no active login account/)).toBeTruthy()})
 it('filters by availability and skill on the server',async()=>{render(<Technicians/>);await screen.findByRole('button',{name:'Open Ravi Kumar'})
  await userEvent.selectOptions(screen.getByLabelText('Filter by availability'),'BUSY');await waitFor(()=>expect(calls.some(c=>c.url.includes('availability=BUSY'))).toBe(true))
  await userEvent.type(screen.getByLabelText('Filter by skill'),'motor');await waitFor(()=>expect(calls.some(c=>c.url.includes('skill=motor'))).toBe(true))})
 it('shows the server 403 when the role has no access',async()=>{reply=()=>({status:403,body:{detail:'You do not have permission to read technicians.'}});render(<Technicians/>);expect(await screen.findByText(/do not have permission/)).toBeTruthy()})
})

const dStatus=(ai:boolean)=>({ai_configured:ai,message:ai?null:'Set EVCARE_AI_URL and EVCARE_AI_API_KEY on the server.',can_write:true,can_export:true,can_create_ticket:true})
const dVeh={items:[{id:'V1',registration_number:'KA01AB1234',make:'Tata',model:'Ace EV',vehicle_type:'VAN',status:'ACTIVE',customer_name:'Acme',active_faults:1,last_fault_at:'2026-10-01T10:00:00Z'}],total:1}
const dHist=(faults:any[],ai=false)=>({vehicle:{id:'V1',registration_number:'KA01AB1234',make:'Tata',model:'Ace EV'},faults,runs:[],ai_configured:ai,can_write:true,can_create_ticket:true})
const fault={id:5,fault_code:'P0A80',description:'Weak cell',severity:'HIGH',detected_at:'2026-10-01T10:00:00Z',source:'MANUAL',status:'ACTIVE',resolved_at:null,ticket_id:null,ticket_number:null}
describe('EVcare.AI Diagnostics',()=>{
 const mk=(ai:boolean,faults:any[])=>{reply=(u,m)=>u.includes('/diagnostics/status')?{status:200,body:dStatus(ai)}:/diagnostics\/vehicles\/V1/.test(u)&&m==='GET'?{status:200,body:dHist(faults,ai)}:/diagnostics\/vehicles/.test(u)&&m==='GET'?{status:200,body:dVeh}:{status:200,body:{ticket_number:'IVT-77'}}}
 it('says "Not configured" when the AI service is unavailable and disables the run button',async()=>{mk(false,[]);render(<Diagnostics/>)
  expect(await screen.findByText(/EVcare.AI: Not configured/)).toBeTruthy();await userEvent.click(await screen.findByRole('button',{name:'Select KA01AB1234'}))
  expect((await screen.findByRole('button',{name:'Run EVcare.AI diagnostic'}) as HTMLButtonElement).disabled).toBe(true);expect(screen.getByText('No diagnostic data has been recorded for this vehicle.')).toBeTruthy()})
 it('shows real fault codes with severity and timestamp, and creates a ticket from one',async()=>{mk(true,[fault]);render(<Diagnostics/>);await userEvent.click(await screen.findByRole('button',{name:'Select KA01AB1234'}))
  expect(await screen.findByText('P0A80')).toBeTruthy();expect(screen.getByText('Weak cell')).toBeTruthy();expect(screen.getAllByText('High').length).toBeGreaterThan(0)
  await userEvent.click(screen.getByRole('button',{name:'Create ticket for P0A80'}));expect(await screen.findByText(/IVT-77 created/)).toBeTruthy();expect(calls.some(c=>c.url.endsWith('/diagnostics/faults/5/ticket')&&c.o.method==='POST')).toBe(true)})
 it('runs EVcare.AI only when configured and shows the server message',async()=>{mk(true,[]);const base=reply;reply=(u,m)=>u.endsWith('/run')?{status:200,body:{message:'1 new fault(s), 0 already recorded'}}:base(u,m);render(<Diagnostics/>)
  await userEvent.click(await screen.findByRole('button',{name:'Select KA01AB1234'}));await userEvent.click(await screen.findByRole('button',{name:'Run EVcare.AI diagnostic'}));expect(await screen.findByText(/1 new fault/)).toBeTruthy()})
 it('shows the server refusal when the AI call fails',async()=>{mk(true,[]);const base=reply;reply=(u,m)=>u.endsWith('/run')?{status:502,body:{detail:'Could not reach the AI service.'}}:base(u,m);render(<Diagnostics/>)
  await userEvent.click(await screen.findByRole('button',{name:'Select KA01AB1234'}));await userEvent.click(await screen.findByRole('button',{name:'Run EVcare.AI diagnostic'}));expect(await screen.findByText(/Could not reach the AI service/)).toBeTruthy()})
})

const dev={id:'D1',device_identifier:'BMS-001',name:'Pack A',device_type:'BMS',vehicle_id:'V1',registration_number:'KA01AB1234',status:'ACTIVE',offline_after_minutes:30,token_hint:'ab12',last_seen_at:'2026-10-27T09:00:00Z',notes:'',connection:'ONLINE'}
const devList=(items:any[])=>({items,total:items.length,device_types:[],statuses:[],vehicles:[{id:'V1',registration_number:'KA01AB1234'}],can_write:true,can_export:true,can_archive:true})
const iSum=(n:number,acc:string='full',scoped=false)=>({devices:n,by_status:{},by_connection:n?{ONLINE:1}:{},readings_24h:0,threshold_alerts:0,offline_devices:0,location_access:acc,scoped_to_assigned_vehicles:scoped})
describe('IoT & Telemetry',()=>{
 const mk=(devices:any[],latest:any[],metrics:any[]=[])=>{reply=(u,m)=>u.includes('/iot/summary')?{status:200,body:iSum(devices.length)}:u.includes('/iot/metrics')?{status:200,body:{items:metrics}}:u.includes('/iot/latest')?{status:200,body:{items:latest}}:u.includes('/iot/alerts')?{status:200,body:{threshold_alerts:[],offline_devices:[],limits_configured:false}}:u.includes('/iot/thresholds')?{status:200,body:{items:[],can_write:true}}:u.includes('/iot/devices')&&m==='GET'?{status:200,body:devList(devices)}:u.includes('/iot/devices')&&m==='POST'?{status:201,body:{...dev,device_token:'SECRET-TOKEN-123'}}:{status:200,body:{}}}
 it('never invents data: no devices and no readings give honest empty states',async()=>{mk([],[]);render(<Iot/>)
  expect(await screen.findByText(/No IoT devices are registered yet/)).toBeTruthy();expect(screen.getByText(/No alert limits are set/)).toBeTruthy()})
 it('shows the latest real reading with unit, vehicle and timestamp',async()=>{mk([dev],[{device_id:'D1',metric:'battery_voltage',value:51.3,unit:'V',recorded_at:'2026-10-27T09:00:00Z',device_identifier:'BMS-001',device_name:'Pack A',registration_number:'KA01AB1234'}],[{metric:'battery_voltage',unit:'V',readings:5,last_at:'2026-10-27T09:00:00Z'}]);render(<Iot/>)
  expect(await screen.findByText('51.3 V')).toBeTruthy();expect(screen.getByText('battery_voltage')).toBeTruthy();expect(screen.getAllByText('KA01AB1234').length).toBeGreaterThan(0)})
 it('applies device/metric filters when loading latest readings',async()=>{mk([dev],[],[{metric:'temperature',unit:'C',readings:1,last_at:'2026-10-27T09:00:00Z'}]);render(<Iot/>)
  await userEvent.selectOptions(await screen.findByLabelText('Filter by metric'),'temperature');await waitFor(()=>expect(calls.some(c=>c.url.includes('/iot/latest')&&c.url.includes('metric=temperature'))).toBe(true))})
 it('registers a device and shows its token once',async()=>{mk([dev],[]);render(<Iot/>);await userEvent.click(await screen.findByRole('tab',{name:'Devices'}));await userEvent.click(await screen.findByRole('button',{name:'Register device'}))
  const f=within(screen.getByRole('form',{name:'Register device'}));await userEvent.type(f.getByLabelText(/Device ID/),'BMS-002');await userEvent.click(f.getByRole('button',{name:'Register device'}))
  expect(await screen.findByText('SECRET-TOKEN-123')).toBeTruthy();const p=calls.find(c=>c.o.method==='POST');expect(p.o.headers['X-CSRF-Token']).toBe('tok123');expect(JSON.parse(p.o.body).device_identifier).toBe('BMS-002')
  await userEvent.click(screen.getByRole('button',{name:'I have saved it'}));expect(screen.queryByText('SECRET-TOKEN-123')).toBeNull()})
 it('requires a metric for the history chart and exports through the filtered endpoint',async()=>{(URL as any).createObjectURL=vi.fn(()=>'blob:x');(URL as any).revokeObjectURL=vi.fn();mk([dev],[],[{metric:'temperature',unit:'C',readings:1,last_at:'2026-10-27T09:00:00Z'}]);render(<Iot/>)
  await userEvent.click(await screen.findByRole('tab',{name:'History chart'}));await userEvent.click(screen.getByRole('button',{name:'Show chart'}));expect(await screen.findByText('Choose a metric to chart.')).toBeTruthy()
  await userEvent.selectOptions(screen.getByLabelText('Filter by metric'),'temperature');await userEvent.click(screen.getByRole('button',{name:'Export readings CSV'}));await waitFor(()=>expect(calls.some(c=>c.url.includes('/iot/export')&&c.url.includes('metric=temperature'))).toBe(true))})
 it('hides device management and export for read-only roles',async()=>{reply=(u)=>u.includes('/iot/summary')?{status:200,body:iSum(1)}:u.includes('/iot/devices')?{status:200,body:{...devList([dev]),can_write:false,can_export:false,can_archive:false}}:{status:200,body:{items:[],threshold_alerts:[],offline_devices:[],limits_configured:false}};render(<Iot/>)
  await userEvent.click(await screen.findByRole('tab',{name:'Devices'}));await screen.findByText('BMS-001');for(const n of ['Register device','Export readings CSV','Edit BMS-001','Rotate token BMS-001','Retire BMS-001'])expect(screen.queryByRole('button',{name:n})).toBeNull()})
})


// ======================= follow-up features =======================
describe('Technicians: honesty and privacy',()=>{
 it('shows "Not set" for availability nobody entered and withholds contact details the role may not see',async()=>{
  const hidden={...tech,availability:null,email:null,phone:null,contact_hidden:true}
  reply=(u,m)=>u.includes('/technicians/summary')?{status:200,body:{...tSum,by_availability:{NOT_SET:1}}}:u.includes('/workload')?{status:200,body:tWl}:/technicians\/T1$/.test(u)&&m==='GET'?{status:200,body:{technician:hidden,tickets:[],can_write:false,can_assign:false}}:{status:200,body:{...tList,items:[hidden],can_see_contact:false,can_write:false}}
  render(<Technicians/>);await userEvent.click(await screen.findByRole('button',{name:'Open Ravi Kumar'}))
  expect((await screen.findAllByText('Withheld (not permitted)')).length).toBe(2);expect(screen.queryByText('r@x.test')).toBeNull();expect(screen.getAllByText(/not set/i).length).toBeGreaterThan(0)})
 it('sends NOT_SET as an availability filter and null (not "AVAILABLE") when none is chosen',async()=>{
  reply=(u,m)=>u.includes('/technicians/summary')?{status:200,body:tSum}:u.includes('/workload')?{status:200,body:tWl}:u.includes('/candidates')?{status:200,body:{items:[{id:'E9',employee_code:'EMP9',name:'New Hire',designation:null}]}}:m==='GET'?{status:200,body:tList}:{status:200,body:{}}
  render(<Technicians/>);await screen.findByRole('button',{name:'Open Ravi Kumar'})
  await userEvent.selectOptions(screen.getByLabelText('Filter by availability'),'NOT_SET');await waitFor(()=>expect(calls.some(c=>c.url.includes('availability=NOT_SET'))).toBe(true))
  await userEvent.click(screen.getByRole('button',{name:'Add technician'}));const f=within(screen.getByRole('form',{name:'Add technician'}));await userEvent.selectOptions(await f.findByLabelText('Employee'),'E9');await userEvent.click(f.getByRole('button',{name:'Add technician'}))
  await waitFor(()=>expect(calls.some(c=>c.o.method==='POST')).toBe(true));expect(JSON.parse(calls.find(c=>c.o.method==='POST').o.body).availability).toBeNull()})
})

describe('Diagnostics: history and telemetry',()=>{
 const base=(ai=true)=>(u:string,m:string)=>u.includes('/diagnostics/status')?{status:200,body:dStatus(ai)}:u.includes('/diagnostics/faults?')?{status:200,body:{items:[{...fault,vehicle_id:'V1',registration_number:'KA01AB1234'}],total:1}}:/diagnostics\/vehicles\/V1/.test(u)&&m==='GET'?{status:200,body:dHist([],ai)}:/diagnostics\/vehicles/.test(u)&&m==='GET'?{status:200,body:dVeh}:{status:200,body:{message:'ok'}}
 it('filters the all-vehicle history by severity, status and date range on the server',async()=>{reply=base();render(<Diagnostics/>)
  await userEvent.click(await screen.findByRole('tab',{name:'Diagnostic history'}));expect(await screen.findByText('P0A80')).toBeTruthy()
  await userEvent.selectOptions(screen.getByLabelText('History severity'),'HIGH');await userEvent.selectOptions(screen.getByLabelText('History status'),'ACTIVE')
  await userEvent.type(screen.getByLabelText('History from date'),'2026-10-01');await userEvent.type(screen.getByLabelText('History to date'),'2026-10-31')
  await waitFor(()=>expect(calls.some(c=>/severity=HIGH/.test(c.url)&&/status=ACTIVE/.test(c.url)&&/date_from=2026-10-01/.test(c.url)&&/date_to=2026-10-31/.test(c.url))).toBe(true))})
 it('filters a vehicle’s history by date',async()=>{reply=base();render(<Diagnostics/>);await userEvent.click(await screen.findByRole('button',{name:'Select KA01AB1234'}))
  await userEvent.type(await screen.findByLabelText('Vehicle history from date'),'2026-09-01');await waitFor(()=>expect(calls.some(c=>/diagnostics\/vehicles\/V1\?.*date_from=2026-09-01/.test(c.url))).toBe(true))})
 it('submits real telemetry only when the box is ticked',async()=>{reply=base();render(<Diagnostics/>);await userEvent.click(await screen.findByRole('button',{name:'Select KA01AB1234'}))
  await userEvent.click(await screen.findByRole('button',{name:'Run EVcare.AI diagnostic'}));await waitFor(()=>expect(calls.some(c=>c.url.endsWith('/run'))).toBe(true));expect(JSON.parse(calls.find(c=>c.url.endsWith('/run')).o.body||'{}').include_telemetry).toBeFalsy()
  calls.length=0;await userEvent.click(screen.getByLabelText('Include recent telemetry'));await userEvent.click(screen.getByRole('button',{name:'Run EVcare.AI diagnostic'}));await waitFor(()=>expect(calls.some(c=>c.url.endsWith('/run'))).toBe(true));expect(JSON.parse(calls.find(c=>c.url.endsWith('/run')).o.body).include_telemetry).toBe(true)})
 it('offers no telemetry option when the AI service is not configured',async()=>{reply=base(false);render(<Diagnostics/>);await userEvent.click(await screen.findByRole('button',{name:'Select KA01AB1234'}));await screen.findByText('AI diagnostics: Not configured.');expect(screen.queryByLabelText('Include recent telemetry')).toBeNull()})
})

describe('IoT: location access, stale readings, details, records',()=>{
 const latestRow=(o:any={})=>({device_id:'D1',metric:'battery_voltage',value:51.3,unit:'V',recorded_at:'2026-10-27T09:00:00Z',device_identifier:'BMS-001',device_name:null,registration_number:'KA01AB1234',stale:false,age_seconds:120,...o})
 const mk=(acc:string,scoped=false,latest:any[]=[latestRow()])=>{reply=(u,m)=>u.includes('/iot/summary')?{status:200,body:iSum(1,acc,scoped)}:u.includes('/iot/metrics')?{status:200,body:{items:[]}}:u.includes('/iot/latest')?{status:200,body:{items:latest,location_access:acc}}:u.includes('/iot/alerts')?{status:200,body:{threshold_alerts:[],offline_devices:[],limits_configured:true}}:u.includes('/iot/records')?{status:200,body:{items:[{id:1,metric:'temperature',value:33,unit:'C',recorded_at:'2026-10-27T09:00:00Z',received_at:'2026-10-27T09:00:05Z',device_identifier:'BMS-001',registration_number:'KA01AB1234'}],total:1}}:/iot\/devices\/D1$/.test(u)?{status:200,body:{device:dev,latest:[latestRow()],recent:[{metric:'temperature',value:33,unit:'C',recorded_at:'2026-10-27T09:00:00Z',received_at:'2026-10-27T09:00:05Z'}],can_write:true}}:u.includes('/iot/devices')?{status:200,body:devList([dev])}:{status:200,body:{items:[]}}}
 it('tells a role without location access that location data is hidden',async()=>{mk('none');render(<Iot/>);expect(await screen.findByText(/Location data \(GPS\) is hidden/)).toBeTruthy()})
 it('tells a technician the view is limited to their assigned vehicles',async()=>{mk('assigned_only',true);render(<Iot/>);expect(await screen.findByText(/only vehicles that have an open ticket assigned to you/)).toBeTruthy();expect(screen.getByText(/Location data is limited to your assigned vehicles/)).toBeTruthy()})
 it('shows no location notice to authorised roles',async()=>{mk('full');render(<Iot/>);await screen.findByText('51.3 V');expect(screen.queryByText(/Location data/)).toBeNull()})
 it('marks old readings as Stale and never calls them live',async()=>{mk('full',false,[latestRow({stale:true,age_seconds:7200})]);render(<Iot/>)
  expect(await screen.findByText('Stale')).toBeTruthy();expect(screen.getByText('2 h ago')).toBeTruthy();expect(screen.getByText(/not live unless the time is recent/)).toBeTruthy();expect(screen.queryByText(/real-time|live reading/i)).toBeNull()})
 it('opens a device details view with settings, latest values and recent records',async()=>{mk('full');render(<Iot/>);await userEvent.click(await screen.findByRole('tab',{name:'Devices'}));await userEvent.click(await screen.findByRole('button',{name:'Open device BMS-001'}))
  const d=within(await screen.findByLabelText('Device BMS-001'));expect(d.getByText('30 min without contact')).toBeTruthy();expect(d.getByText('Recent records')).toBeTruthy();expect(d.getByText('33 C')).toBeTruthy()})
 it('lists raw telemetry records with recorded and received times and honours filters',async()=>{mk('full');render(<Iot/>);await userEvent.click(await screen.findByRole('tab',{name:'Records'}))
  expect(await screen.findByText('33 C')).toBeTruthy();await userEvent.type(screen.getByLabelText('Records from date'),'2026-10-01');await waitFor(()=>expect(calls.some(c=>/iot\/records\?.*date_from=2026-10-01/.test(c.url))).toBe(true))})
})
