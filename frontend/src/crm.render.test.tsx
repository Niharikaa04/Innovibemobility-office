// @vitest-environment jsdom
import {describe,it,expect,vi,beforeEach,afterEach} from 'vitest'
import {render,screen,cleanup,waitFor} from '@testing-library/react'; import userEvent from '@testing-library/user-event'
import Crm from './Crm'
const list={items:[{id:'1',full_name:'Asha Rao',email:'asha@abc.test',phone:'',organization:'ABC Logistics'}],total:1,page:1,page_size:20,can_write:true,can_archive:true,stages:[]}
let calls:any[]; let post:{status:number,body:any}
beforeEach(()=>{document.cookie='csrf=tok123';calls=[];post={status:201,body:{id:'2'}}
 vi.stubGlobal('fetch',vi.fn(async(url:string,o:any={})=>{calls.push({url,o});const m=o.method||'GET';const r=m==='GET'?{status:200,body:list}:post;return {ok:r.status<400,status:r.status,json:async()=>r.body}}))})
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
describe('CRM contacts page',()=>{
 it('lists real API data and searches via the server',async()=>{render(<Crm kind="contacts"/>);expect(await screen.findByText('Asha Rao')).toBeTruthy()
  await userEvent.type(screen.getByLabelText('Search contacts'),'abc');await waitFor(()=>expect(calls.some(c=>String(c.url).includes('q=abc'))).toBe(true))})
 it('shows the server error and NO success message when the save fails',async()=>{post={status:409,body:{detail:'A contact with this email already exists.'}}
  render(<Crm kind="contacts"/>);await userEvent.click(await screen.findByRole('button',{name:'Add contact'}));await userEvent.type(screen.getByLabelText('Name *'),'Dup');await userEvent.click(screen.getByRole('button',{name:'Save'}))
  expect(await screen.findByText('A contact with this email already exists.')).toBeTruthy();expect(screen.queryByText('Contact saved.')).toBeNull()})
 it('sends the CSRF token on save, and reports success only after the server confirms',async()=>{render(<Crm kind="contacts"/>)
  await userEvent.click(await screen.findByRole('button',{name:'Add contact'}));await userEvent.type(screen.getByLabelText('Name *'),'New Person');await userEvent.click(screen.getByRole('button',{name:'Save'}))
  expect(await screen.findByText('Contact saved.')).toBeTruthy();const p=calls.find(c=>c.o.method==='POST');expect(p.o.headers['X-CSRF-Token']).toBe('tok123');expect(JSON.parse(p.o.body).full_name).toBe('New Person')})
 it('hides write controls for read-only users',async()=>{vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,status:200,json:async()=>({...list,can_write:false,can_archive:false})})));render(<Crm kind="contacts"/>);await screen.findByText('Asha Rao')
  expect(screen.queryByRole('button',{name:'Add contact'})).toBeNull();expect(screen.queryByRole('button',{name:'Delete'})).toBeNull()})
 it('delete asks for confirmation first',async()=>{const c=vi.spyOn(window,'confirm').mockReturnValue(false);render(<Crm kind="contacts"/>);await userEvent.click(await screen.findByRole('button',{name:'Delete'}))
  expect(c).toHaveBeenCalled();expect(calls.some(x=>x.o.method==='DELETE')).toBe(false)})})
describe('CRM leads page (regressions)',()=>{
 const leads={items:[{id:'L1',title:'10 e-vans',contact_name:'Asha Rao',contact_id:'C1',source:'web',value:'100',next_follow_up:null,stage:'qualified'},{id:'L2',title:'Won deal',stage:'won'}],total:2,page:1,page_size:20,can_write:true,stages:['new','contacted','proposal','negotiation','won','lost'],stage_labels:{new:'New Lead',contacted:'Contacted',proposal:'Proposal Sent',negotiation:'Negotiation',won:'Won',lost:'Lost'}}
 beforeEach(()=>{vi.stubGlobal('fetch',vi.fn(async(url:string,o:any={})=>{calls.push({url,o});const m=o.method||'GET';return {ok:true,status:200,json:async()=>m==='GET'?(String(url).includes('/crm/leads')?leads:list):{id:'L1'}}}))})
 it('shows the decided stage names and keeps a legacy stage visible instead of blanking it',async()=>{render(<Crm kind="leads"/>);await screen.findByText('10 e-vans')
  expect(screen.getAllByRole('option',{name:'Proposal Sent'}).length).toBeGreaterThan(0);expect(screen.queryByRole('option',{name:'Qualified'})).toBeNull()
  expect((screen.getByLabelText('Stage of 10 e-vans') as HTMLSelectElement).value).toBe('qualified');expect(screen.getByRole('option',{name:'Qualified (legacy)'})).toBeTruthy()})
 it('does not fetch a fixed first-100 contact list; the picker searches on the server',async()=>{render(<Crm kind="leads"/>);await screen.findByText('10 e-vans')
  expect(calls.some(c=>String(c.url).includes('page_size=100'))).toBe(false)
  await userEvent.click(screen.getAllByRole('button',{name:'Edit'})[0]);await userEvent.type(screen.getByLabelText('Find contact'),'abc')
  await waitFor(()=>expect(calls.some(c=>String(c.url).includes('/crm/contacts?page_size=50&q=abc'))).toBe(true))})
 it('sends contact_id null when the contact is cleared on edit',async()=>{render(<Crm kind="leads"/>);await screen.findByText('10 e-vans')
  await userEvent.click(screen.getAllByRole('button',{name:'Edit'})[0]);await userEvent.selectOptions(screen.getByLabelText('Contact'),'');await userEvent.click(screen.getByRole('button',{name:'Save'}))
  await waitFor(()=>expect(calls.some(c=>c.o.method==='PATCH')).toBe(true));expect(JSON.parse(calls.find(c=>c.o.method==='PATCH').o.body).contact_id).toBeNull()})})

describe('Delete (archive) in the UI',()=>{
 const mk2=(over:any)=>vi.stubGlobal('fetch',vi.fn(async(url:string,o:any={})=>{calls.push({url,o});const m=o.method||'GET';return {ok:true,status:200,json:async()=>m==='GET'?(String(url).includes('/crm/leads')?{items:[{id:'L1',title:'Deal',stage:'new'}],total:1,stages:['new'],stage_labels:{},can_write:true,can_archive:true,...over}:{...list,...over}):{ok:true}}}))
 it('confirmed delete sends DELETE with the CSRF token and says archived',async()=>{mk2({});vi.spyOn(window,'confirm').mockReturnValue(true);render(<Crm kind="contacts"/>)
  await userEvent.click(await screen.findByRole('button',{name:'Delete'}));expect(await screen.findByText('Contact deleted (archived).')).toBeTruthy()
  const d=calls.find(c=>c.o.method==='DELETE');expect(d.url).toContain('/crm/contacts/1');expect(d.o.headers['X-CSRF-Token']).toBe('tok123')})
 it('the confirmation text says it is an archive, not a permanent delete',async()=>{mk2({});const c=vi.spyOn(window,'confirm').mockReturnValue(false);render(<Crm kind="leads"/>)
  await userEvent.click(await screen.findByRole('button',{name:'Delete'}));expect(String(c.mock.calls[0][0])).toMatch(/archived/i);expect(calls.some(x=>x.o.method==='DELETE')).toBe(false)})
 it('Delete is hidden when the server says the user cannot archive, even if they can edit',async()=>{mk2({can_archive:false});render(<Crm kind="leads"/>)
  await screen.findByText('Deal');expect(screen.queryByRole('button',{name:'Delete'})).toBeNull();expect(screen.getByRole('button',{name:'Edit'})).toBeTruthy()})
 it('shows the server error when delete is refused (409 open leads)',async()=>{vi.stubGlobal('fetch',vi.fn(async(url:string,o:any={})=>{const m=o.method||'GET';return m==='GET'?{ok:true,status:200,json:async()=>list}:{ok:false,status:409,json:async()=>({detail:'This contact has open leads. Close or archive them first.'})}}))
  vi.spyOn(window,'confirm').mockReturnValue(true);render(<Crm kind="contacts"/>);await userEvent.click(await screen.findByRole('button',{name:'Delete'}))
  expect(await screen.findByText('This contact has open leads. Close or archive them first.')).toBeTruthy();expect(screen.queryByText('Contact deleted (archived).')).toBeNull()})})
