import { useEffect, useState } from 'react';
import { User } from './api';
import { PORTAL_NAMES } from './nav';

export type Profile = {
  name: string;
  title: string;
  email: string;
  phone: string;
  photo: string; // URL or data URL, '' = initials
};

const EVT = 'profile-changed';
const keyOf = (u: User) =>
  `profile:${(u as any).id ?? (u as any).email ?? u.role}`;

function read(u: User): Profile {
  const base: Profile = {
    name: u.name,
    title: PORTAL_NAMES[u.role],
    email: (u as any).email ?? '',
    phone: '',
    photo: u.role === 'ceo' ? '/assets/ceo-profile.png' : '',
  };
  try {
    const s = localStorage.getItem(keyOf(u));
    if (s) return { ...base, ...JSON.parse(s) };
  } catch {}
  return base;
}

export async function saveProfile(u: User, p: Profile) {
  // TODO: replace with your backend call, e.g. await api.updateProfile(p);
  try {
    localStorage.setItem(keyOf(u), JSON.stringify(p));
  } catch {}
  window.dispatchEvent(new Event(EVT));
}

export function useProfile(u: User): Profile {
  const [p, setP] = useState(() => read(u));

  useEffect(() => {
    const f = () => setP(read(u));
    f();
    window.addEventListener(EVT, f);
    return () => window.removeEventListener(EVT, f);
  }, [u.name, u.role]);

  return p;
}
