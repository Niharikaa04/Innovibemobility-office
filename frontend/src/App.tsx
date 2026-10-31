import {useEffect,useState} from 'react'; import {Routes,Route,Navigate,useNavigate,useLocation,useParams} from 'react-router-dom'
import {api,HOME,User} from './api'; import {redirectFor} from './routing'; import Login from './Login'; import Dashboard from './Dashboard'; import Forgot from './Forgot'
export default function App(){
 const [user,setUser]=useState<User|null>(null),[ready,setReady]=useState(false),nav=useNavigate(),loc=useLocation()
 useEffect(()=>{api.me().then(setUser).catch(()=>{}).finally(()=>setReady(true))},[])
 const out=async()=>{await api.logout().catch(()=>{});setUser(null);nav('/login')}
 const Portal=()=>{const {portal}=useParams();return <Dashboard key={portal} user={user!} portal={portal!.replace(/-/g,'_')} onLogout={out}/>}
 if(!ready)return <p style={{padding:24}}>Loading…</p>
 const r=redirectFor(user,loc.pathname)
 if(r&&r!==loc.pathname)return <Navigate to={r} replace/>
 return <Routes><Route path="/login" element={<Login onUser={setUser}/>}/><Route path="/forgot-password" element={<Forgot/>}/>
  <Route path="/:portal" element={<Portal/>}/><Route path="/:portal/:slug" element={<Portal/>}/><Route path="*" element={<Navigate to={user?HOME[user.role]:'/login'} replace/>}/></Routes>}
