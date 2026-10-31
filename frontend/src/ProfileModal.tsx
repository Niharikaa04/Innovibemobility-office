import { useRef, useState } from 'react';
import { User } from './api';
import { Profile, saveProfile } from './useProfile';

export function Avatar({
  p,
  size,
  border = '2px solid #e1eaf7',
}: {
  p: Profile;
  size: number;
  border?: string;
}) {
  const [bad, setBad] = useState(false);
  const initials = p.name
    .replace(/^dr\.?\s+/i, '')
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();

  const box: React.CSSProperties = {
    width: size,
    height: size,
    minWidth: size,
    borderRadius: '50%',
    border,
    flexShrink: 0,
  };

  return p.photo && !bad ? (
    <img
      src={p.photo}
      alt={p.name}
      onError={() => setBad(true)}
      style={{ ...box, objectFit: 'cover', objectPosition: 'center 25%' }}
    />
  ) : (
    <div
      aria-label={p.name}
      style={{
        ...box,
        display: 'grid',
        placeItems: 'center',
        background: '#2563eb',
        color: '#fff',
        fontWeight: 700,
        fontSize: size * 0.38,
      }}
    >
      {initials || '?'}
    </div>
  );
}

// Crop to a square and shrink to 256px so it stays small in storage
function toDataUrl(file: File): Promise<string> {
  return new Promise((res, rej) => {
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      const s = 256;
      const side = Math.min(img.width, img.height);
      const c = document.createElement('canvas');
      c.width = c.height = s;
      c.getContext('2d')!.drawImage(
        img,
        (img.width - side) / 2,
        (img.height - side) / 4,
        side,
        side,
        0,
        0,
        s,
        s
      );
      URL.revokeObjectURL(url);
      res(c.toDataURL('image/jpeg', 0.85));
    };
    img.onerror = () => rej(new Error('Invalid image'));
    img.src = url;
  });
}

export default function ProfileModal({
  user,
  profile,
  onClose,
}: {
  user: User;
  profile: Profile;
  onClose: () => void;
}) {
  const [f, setF] = useState<Profile>(profile);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const file = useRef<HTMLInputElement>(null);

  const set =
    (k: keyof Profile) => (e: React.ChangeEvent<HTMLInputElement>) =>
      setF({ ...f, [k]: e.target.value });

  const pick = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const x = e.target.files?.[0];
    if (!x) return;
    if (!x.type.startsWith('image/'))
      return setErr('Please choose an image file.');
    try {
      setF({ ...f, photo: await toDataUrl(x) });
      setErr('');
    } catch {
      setErr('Could not read that image.');
    }
  };

  const submit = async () => {
    if (!f.name.trim()) return setErr('Name is required.');
    if (f.email && !/^\S+@\S+\.\S+$/.test(f.email))
      return setErr('Enter a valid email.');
    setBusy(true);
    await saveProfile(user, { ...f, name: f.name.trim() });
    setBusy(false);
    onClose();
  };

  const field: React.CSSProperties = {
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
    fontSize: 12,
    fontWeight: 600,
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Edit profile"
      onClick={onClose}
      onKeyDown={(e) => e.key === 'Escape' && onClose()}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(10,20,40,.45)',
        display: 'grid',
        placeItems: 'center',
        zIndex: 1000,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 400,
          maxWidth: '92vw',
          background: 'var(--card, #fff)',
          borderRadius: 16,
          padding: 22,
          display: 'flex',
          flexDirection: 'column',
          gap: 14,
        }}
      >
        <h3 style={{ margin: 0 }}>Edit profile</h3>

        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <Avatar p={f} size={72} />
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn" onClick={() => file.current?.click()}>
              Change photo
            </button>
            {f.photo && (
              <button className="ghost" onClick={() => setF({ ...f, photo: '' })}>
                Remove
              </button>
            )}
          </div>
          <input ref={file} type="file" accept="image/*" hidden onChange={pick} />
        </div>

        <label style={field}>
          Full name
          <input value={f.name} onChange={set('name')} />
        </label>
        <label style={field}>
          Designation
          <input value={f.title} onChange={set('title')} />
        </label>
        <label style={field}>
          Email
          <input type="email" value={f.email} onChange={set('email')} />
        </label>
        <label style={field}>
          Phone
          <input type="tel" value={f.phone} onChange={set('phone')} />
        </label>

        {err && (
          <div className="err" role="alert">
            {err}
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button className="ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn" onClick={submit} disabled={busy}>
            {busy ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}
