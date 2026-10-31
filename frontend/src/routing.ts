import {HOME,Role,User} from './api'
const PORTALS=Object.keys(HOME) as Role[]
/** Redirect target for `path`, or null if the user may stay. CEO has read-only access to the COO and CTO portals. */
export function redirectFor(user:User|null,path:string):string|null{
 const raw=path.split('/').filter(Boolean)[0]??'',seg=raw.replace(/-/g,'_')
 if(raw==='login'||raw==='forgot-password')return user?HOME[user.role]:null
 if(!(PORTALS as string[]).includes(seg))return user?HOME[user.role]:'/login'
 if(!user)return '/login'
 return user.role===seg||(user.role==='ceo'&&(seg==='coo'||seg==='cto'))?null:HOME[user.role]}
