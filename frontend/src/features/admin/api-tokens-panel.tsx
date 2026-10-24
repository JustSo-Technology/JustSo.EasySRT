import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { tokenApi, type IntegrationToken, type ScopeGrant, type TokenCatalogue, type TokenAudit, type User } from '@/lib/api';

const selectClass = 'w-full rounded-xl border border-white/20 bg-slate-950 px-3 py-2 text-sm text-white';
const rank = { operator: 0, engineer: 1, owner: 2 };
const label = (v: string) => v.replaceAll('-', ' ').replaceAll(':', ' · ');
const localDate = (v: Date) => new Date(v.getTime() - v.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
const when = (v: string | null) => v ? new Date(v).toLocaleString() : 'Never';
const expiryIn = (days: number) => localDate(new Date(Date.now() + days * 86400000));

function GroupCheckbox({ checked, partial, onChange, name }: { checked: boolean; partial: boolean; onChange: () => void; name: string }) {
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { if (input.current) input.current.indeterminate = partial; }, [partial]);
  return <label className="flex items-center gap-3 font-semibold"><input ref={input} type="checkbox" checked={checked} onChange={onChange} />{name}</label>;
}

export function ApiTokensPanel({ users, currentUser, onClose }: { users: User[]; currentUser: User; onClose: () => void }) {
  const [catalogue, setCatalogue] = useState<TokenCatalogue | null>(null);
  const [tokens, setTokens] = useState<IntegrationToken[]>([]);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [scopeSearch, setScopeSearch] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<IntegrationToken | null>(null);
  const [name, setName] = useState('');
  const [integration, setIntegration] = useState('');
  const [ownerId, setOwnerId] = useState(currentUser.id);
  const [preset, setPreset] = useState('monitor');
  const [additionalPreset, setAdditionalPreset] = useState('monitor');
  const [observedAt] = useState(Date.now);
  const [grants, setGrants] = useState<ScopeGrant[]>([]);
  const [expiry, setExpiry] = useState(() => expiryIn(90));
  const [password, setPassword] = useState('');
  const [review, setReview] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);
  const [action, setAction] = useState<{ type: 'rotate' | 'revoke'; token?: IntegrationToken; ids: string[] } | null>(null);
  const [overlap, setOverlap] = useState('0');
  const [audit, setAudit] = useState<{ name: string; rows: TokenAudit[] } | null>(null);

  async function reload(page = offset) {
    const result = await tokenApi.list(page);
    setTokens(result.items); setHasMore(result.items.length === 100); setOffset(page); setSelected([]);
  }
  useEffect(() => {
    let active = true;
    Promise.all([tokenApi.catalogue(), tokenApi.list()]).then(([c, result]) => {
      if (active) { setCatalogue(c); setTokens(result.items); setHasMore(result.items.length === 100); }
    }).catch(e => { if (active) setError(e instanceof Error ? e.message : 'Unable to load API tokens'); });
    return () => { active = false; };
  }, []);
  async function perform(work: () => Promise<void>) {
    setBusy(true); setError(null);
    try { await work(); } catch (e) { setError(e instanceof Error ? e.message : 'Request failed'); }
    finally { setBusy(false); setPassword(''); }
  }
  function closeEditor() { setFormOpen(false); setPassword(''); setReview(false); }
  function openEditor(token: IntegrationToken | null) {
    setEditing(token); setName(token?.name ?? ''); setIntegration(token?.integration ?? ''); setOwnerId(token?.owner_id ?? currentUser.id);
    setPreset(token?.preset ?? 'monitor'); setGrants(token?.grants ?? catalogue?.presets.find(p => p.id === 'monitor')?.grants ?? []);
    setExpiry(token ? localDate(new Date(token.expires_at)) : expiryIn(90));
    setSecret(null); setReview(false); setPassword(''); setFormOpen(true); setError(null); setScopeSearch('');
  }
  function grantFor(scope: TokenCatalogue['scopes'][number]): ScopeGrant {
    const kind = scope.kind === 'any' ? 'preset' : scope.kind;
    return { scope: scope.id, kind, resource_id: kind === 'path' ? 'default' : kind === 'instance' ? catalogue!.instance_id : '*', target: scope.id === 'presets:apply' ? 'default' : null };
  }
  function changeGrant(index: number, change: Partial<ScopeGrant>) { setGrants(grants.map((g, i) => i === index ? { ...g, ...change } : g)); }
  const owner = users.find(u => u.id === ownerId);
  const role = owner?.role ?? 'operator';
  const unsupported = grants.some(g => rank[role] < rank[catalogue?.scopes.find(s => s.id === g.scope)?.minimum_role ?? 'owner']);
  const template = catalogue?.presets.find(p => p.id === preset);
  const customised = template && JSON.stringify(template.grants) !== JSON.stringify(grants);
  const groups = Array.from(new Set(catalogue?.scopes.map(s => s.group) ?? []));
  const visible = tokens.filter(t => `${t.name} ${t.integration} ${t.preset} ${t.status} ${users.find(u => u.id === t.owner_id)?.username ?? ''}`.toLowerCase().includes(search.toLowerCase()));
  const dangerous = grants.filter(g => /secrets:|:delete$|:apply$|service:(stop|restart|start)$/.test(g.scope));
  const validExpiry = Number.isFinite(Date.parse(expiry));

  async function save() {
    if (!review) { setReview(true); return; }
    await perform(async () => {
      const expires_at = new Date(expiry).toISOString();
      if (editing) await tokenApi.update(editing.id, { name, grants, expires_at, expected_revision: editing.revision, current_password: password });
      else {
        const result = await tokenApi.create({ name, integration, owner_id: ownerId, grants, expires_at, preset, current_password: password });
        setSecret(result.secret);
      }
      closeEditor(); await reload();
    });
  }

  return <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-950/95 p-4 text-white backdrop-blur-xl sm:p-8" role="dialog" aria-modal="true" aria-label="API tokens">
    <div className="mx-auto max-w-6xl space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4"><div><p className="section-label">Administration</p><h2 className="mt-2 text-3xl font-semibold">API tokens</h2><p className="mt-2 max-w-2xl text-sm text-slate-300">Give each integration its own named token. Start with a preset, then choose every action and resource it can access.</p></div><Button onClick={() => { setSecret(null); setPassword(''); onClose(); }}>Back to user management</Button></header>
      <p className="rounded-xl border border-cyan-300/20 bg-cyan-300/5 p-4 text-sm text-slate-300">HTTPS is required. Tokens apply only to this EasySRT instance. Notification-service credentials are managed separately.</p>
      {error && <p role="alert" className="rounded-xl border border-rose-300/30 p-4 text-rose-100">{error}</p>}
      {secret !== null && <Card className="space-y-4 border-amber-200/40"><h3 className="text-lg font-semibold">Copy your token now</h3><p className="text-sm text-slate-300">The secret is shown once. Keep it in your integration’s secret store; rotate the token if you lose it.</p><Input aria-label="Token secret" readOnly value={secret} autoComplete="off" /><div className="flex gap-3"><Button onClick={() => void navigator.clipboard.writeText(secret).catch(() => setError('Clipboard unavailable; select and copy the token field.'))}>Copy token</Button><Button onClick={() => setSecret(null)}>I’ve saved it — dismiss secret</Button></div></Card>}
      {!formOpen && <>
        <div className="flex flex-wrap gap-3"><Input className="max-w-lg" aria-label="Filter tokens" placeholder="Filter by name, integration, owner, preset or status" value={search} onChange={e => setSearch(e.target.value)} /><Button disabled={!catalogue || busy} onClick={() => openEditor(null)}>Create token</Button><Button disabled={!selected.length || busy} onClick={() => setAction({ type: 'revoke', ids: selected })}>Revoke selected ({selected.length})</Button><Button disabled={busy} onClick={() => void perform(() => reload())}>Refresh</Button></div>
        {!catalogue && !error && <p>Loading token catalogue…</p>}
        {catalogue && tokens.length === 0 && <Card><h3 className="text-lg">No API tokens yet</h3><p className="mt-2 text-slate-300">Create a Monitor token for a dashboard, or choose Custom for a specific integration.</p></Card>}
        {visible.map(token => <Card key={token.id} className="space-y-4">
          <div className="flex flex-wrap items-start justify-between gap-4"><div className="flex gap-3"><input type="checkbox" aria-label={`Select ${token.name}`} checked={selected.includes(token.id)} onChange={e => setSelected(e.target.checked ? [...selected, token.id] : selected.filter(id => id !== token.id))} /><div><h3 className="text-xl font-semibold">{token.name} <span className="ml-2 text-sm font-normal text-cyan-100">{label(token.status)}</span></h3><p className="mt-1 text-sm text-slate-300">{token.integration} · {users.find(u => u.id === token.owner_id)?.username ?? token.owner_id} · {token.preset_customized && token.preset !== 'custom' ? `customised from ${label(token.preset)}` : label(token.preset)} · {token.effective_grants.length}/{token.grants.length} effective grants</p></div></div>
            <div className="flex flex-wrap gap-2"><Button disabled={busy || token.status !== 'active'} onClick={() => openEditor(token)}>Edit permissions</Button><Button disabled={busy || token.status !== 'active'} onClick={() => { setAction({ type: 'rotate', token, ids: [token.id] }); setPassword(''); setOverlap('0'); }}>Rotate</Button><Button disabled={busy || token.status === 'revoked'} onClick={() => setAction({ type: 'revoke', ids: [token.id] })}>Revoke</Button><Button disabled={busy} onClick={() => void perform(async () => setAudit({ name: token.name, rows: (await tokenApi.audit(token.id)).items }))}>Audit history</Button></div></div>
          <dl className="grid gap-3 text-sm text-slate-300 sm:grid-cols-3"><div><dt className="text-slate-500">Created</dt><dd>{when(token.created_at)}</dd></div><div><dt className="text-slate-500">Expires</dt><dd>{when(token.expires_at)}</dd>{token.status === 'active' && Date.parse(token.expires_at) - observedAt < 7 * 86400000 && <p className="text-amber-200">Expires within seven days</p>}</div><div><dt className="text-slate-500">Last authenticated use</dt><dd>{when(token.last_used_at)}</dd></div></dl>
          <details><summary className="cursor-pointer text-sm">Permissions and credential metadata</summary><ul className="mt-3 space-y-1 text-sm text-slate-300">{token.grants.map((g, i) => <li key={i}>{g.scope} · {g.kind}: {g.resource_id === '*' ? 'all current and future resources' : g.resource_id}{g.target ? ` → ${g.target}` : ''}</li>)}</ul><ul className="mt-3 space-y-1 text-xs text-slate-400">{token.credentials.map(c => <li key={c.id}>{c.prefix} · used {when(c.last_used_at)}{c.retire_at ? ` · retires ${when(c.retire_at)}` : ''}{c.revoked_at ? ' · revoked' : ''}</li>)}</ul><p className="mt-2 text-xs text-slate-500">Token ID {token.id} · revision {token.revision}</p></details>
        </Card>)}
        <div className="flex gap-3"><Button disabled={offset === 0 || busy} onClick={() => void perform(() => reload(Math.max(0, offset - 100)))}>Previous page</Button><Button disabled={!hasMore || busy} onClick={() => void perform(() => reload(offset + 100))}>Next page</Button></div>
      </>}
      {formOpen && catalogue && <Card className="space-y-6">
        <div className="flex justify-between gap-3"><h3 className="text-2xl font-semibold">{review ? 'Review token access' : editing ? 'Edit token' : 'Create token'}</h3><Button disabled={busy} onClick={closeEditor}>Cancel</Button></div>
        {!review ? <>
          <div className="grid gap-4 sm:grid-cols-2"><label>Token name<Input value={name} maxLength={120} onChange={e => setName(e.target.value)} placeholder="Studio monitoring" /></label><label>Integration<Input value={integration} disabled={!!editing} maxLength={120} onChange={e => setIntegration(e.target.value)} placeholder="monitoring-dashboard" /></label><label>Owning account<select className={selectClass} value={ownerId} disabled={!!editing} onChange={e => setOwnerId(e.target.value)}>{users.filter(u => !u.disabled).map(u => <option key={u.id} value={u.id}>{u.username} · {u.role}</option>)}</select></label><label>Permission preset<select className={selectClass} value={preset} onChange={e => { setPreset(e.target.value); setGrants(catalogue.presets.find(p => p.id === e.target.value)?.grants ?? []); }}>{catalogue.presets.map(p => <option key={p.id} value={p.id}>{label(p.id)}</option>)}</select></label></div>
          <p className="text-sm text-slate-400">{customised ? `Customised from ${label(preset)}.` : `Preset: ${label(preset)}.`} Future preset changes never expand this token. The owning account’s role remains its permission ceiling.</p>
          <div className="flex flex-wrap items-end gap-3"><label>Add another preset<select className={selectClass} value={additionalPreset} onChange={e => setAdditionalPreset(e.target.value)}>{catalogue.presets.map(p => <option key={p.id} value={p.id}>{label(p.id)}</option>)}</select></label><Button onClick={() => {
            const extra = catalogue.presets.find(p => p.id === additionalPreset)?.grants ?? [];
            setGrants([...grants, ...extra.filter(g => !grants.some(existing => JSON.stringify(existing) === JSON.stringify(g)))]);
          }}>Add preset permissions</Button></div>
          <Input aria-label="Find permission" placeholder="Find an action, group or endpoint" value={scopeSearch} onChange={e => setScopeSearch(e.target.value)} />
          {groups.map(group => {
            const items = catalogue.scopes.filter(s => s.group === group && `${s.id} ${s.group} ${(catalogue.endpoints[s.id] ?? []).join(' ')}`.toLowerCase().includes(scopeSearch.toLowerCase()));
            if (!items.length) return null;
            const count = items.filter(s => grants.some(g => g.scope === s.id)).length;
            return <fieldset key={group} className="space-y-3 rounded-xl border border-white/15 p-4"><legend className="px-2"><GroupCheckbox name={group} checked={count === items.length} partial={count > 0 && count < items.length} onChange={() => setGrants(count === items.length ? grants.filter(g => !items.some(s => s.id === g.scope)) : [...grants, ...items.filter(s => !grants.some(g => g.scope === s.id) && rank[role] >= rank[s.minimum_role]).map(grantFor)])} /></legend>
              {items.map(scope => {
                const matching = grants.map((g, i) => ({ g, i })).filter(({ g }) => g.scope === scope.id);
                const allowed = rank[role] >= rank[scope.minimum_role];
                return <div key={scope.id} className="space-y-2 border-t border-white/5 pt-3"><label className="flex gap-3"><input type="checkbox" aria-label={scope.id} checked={matching.length > 0} disabled={!allowed && matching.length === 0} onChange={e => setGrants(e.target.checked ? [...grants, grantFor(scope)] : grants.filter(g => g.scope !== scope.id))} /><span>{label(scope.id)}{!allowed && <span className="ml-2 text-sm text-amber-200">Requires {scope.minimum_role}</span>}</span></label>{scope.description && <p className="pl-6 text-xs text-slate-300">{scope.description}</p>}<p className="pl-6 text-xs text-slate-500">{(catalogue.endpoints[scope.id] ?? ['Additional field access on authorised resource operations']).join(' · ')}</p>
                  {matching.map(({ g, i }) => <div key={i} className="ml-6 flex flex-wrap items-center gap-2">
                    {scope.kind === 'any' && <select aria-label={`${scope.id} resource type ${i}`} className={selectClass + ' max-w-40'} value={g.kind} onChange={e => changeGrant(i, { kind: e.target.value, resource_id: e.target.value === 'instance' ? catalogue.instance_id : '*' })}>{['preset', 'input', 'destination', 'instance'].map(kind => <option key={kind}>{kind}</option>)}</select>}
                    <select aria-label={`${scope.id} resource ${i}`} className={selectClass + ' max-w-lg'} value={g.resource_id} onChange={e => changeGrant(i, { resource_id: e.target.value })}>{!['instance', 'path'].includes(g.kind) && <option value="*">All current and future {g.kind}s</option>}{(catalogue.resources[g.kind] ?? []).map(r => <option key={r.id} value={r.id}>{r.name}</option>)}{g.resource_id !== '*' && !(catalogue.resources[g.kind] ?? []).some(r => r.id === g.resource_id) && <option value={g.resource_id}>{g.resource_id} (unavailable)</option>}</select>{g.target && <span className="text-xs text-slate-400">Target: default sender</span>}
                    {!scope.id.endsWith(':create') && !['path', 'instance'].includes(g.kind) && <Button onClick={() => setGrants([...grants, { ...g }])}>Add resource</Button>}<Button onClick={() => setGrants(grants.filter((_, index) => index !== i))}>Remove</Button>
                  </div>)}
                </div>;
              })}
            </fieldset>;
          })}
          <div className="grid gap-4 sm:grid-cols-2"><label>Expiry preset<select className={selectClass} defaultValue="custom" onChange={e => { if (e.target.value !== 'custom') setExpiry(expiryIn(Number(e.target.value))); }}><option value="custom">Custom date/time</option>{[7, 30, 90, 365].map(days => <option key={days} value={days}>{days} days</option>)}</select></label><label>Expires at (your local time)<Input type="datetime-local" value={expiry} onChange={e => setExpiry(e.target.value)} /></label></div>
        </> : <>
          <p><strong>{name}</strong> · {integration} · owned by {owner?.username ?? ownerId}</p><p>Expires {when(new Date(expiry).toISOString())}. {grants.length} explicit grants.</p><ul className="space-y-1 text-sm text-slate-300">{grants.map((g, i) => <li key={i}>{g.scope} · {g.kind} · {g.resource_id === '*' ? 'all current and future resources' : catalogue.resources[g.kind]?.find(r => r.id === g.resource_id)?.name ?? g.resource_id}{g.target ? ' → default sender' : ''}</li>)}</ul>
          {dangerous.length > 0 && <p className="rounded-xl border border-amber-300/30 p-4 text-amber-100">This token can perform: {dangerous.map(g => g.scope).join(', ')}. Apply selects configuration; Start/Restart permissions are separate. Secret access is limited to the listed resources.</p>}
          <label>Confirm your current Owner password<Input type="password" value={password} autoComplete="current-password" onChange={e => setPassword(e.target.value)} /></label><Button disabled={busy} onClick={() => { setReview(false); setPassword(''); }}>Back to permissions</Button>
        </>}
        {unsupported && <p role="alert" className="text-amber-200">Remove grants that exceed the owning account’s role.</p>}
        <Button disabled={busy || !name.trim() || !integration.trim() || !grants.length || unsupported || !validExpiry || (review && !password)} onClick={() => void save()}>{busy ? 'Saving…' : review ? editing ? 'Save token changes' : 'Create and reveal token' : 'Review permissions'}</Button>
      </Card>}
      {action && <Card className="space-y-4"><h3 className="text-xl font-semibold">{action.type === 'rotate' ? `Rotate ${action.token?.name}` : `Revoke ${action.ids.length} token(s)`}</h3>
        {action.type === 'rotate' ? <><p className="text-sm text-slate-300">The new credential keeps the same permissions and expiry. A second rotation retires the oldest credential.</p><label>Old credential overlap<select className={selectClass} value={overlap} onChange={e => setOverlap(e.target.value)}><option value="0">Retire immediately</option><option value="3600">One hour</option><option value="86400">24 hours</option></select></label><label>Current Owner password<Input type="password" value={password} autoComplete="current-password" onChange={e => setPassword(e.target.value)} /></label></> : <p>Every credential for these tokens will be rejected immediately. Create a new token if access is needed again.</p>}
        <div className="flex gap-3"><Button disabled={busy || (action.type === 'rotate' && !password)} onClick={() => void perform(async () => { if (action.type === 'rotate' && action.token) { const result = await tokenApi.rotate(action.token.id, { expected_revision: action.token.revision, overlap_seconds: Number(overlap), current_password: password }); setSecret(result.secret); } else await tokenApi.revoke(action.ids); setAction(null); await reload(); })}>{action.type === 'rotate' ? 'Rotate and reveal new token' : 'Confirm revoke'}</Button><Button disabled={busy} onClick={() => { setAction(null); setPassword(''); }}>Cancel</Button></div>
      </Card>}
      {audit && <Card className="space-y-4"><div className="flex justify-between"><h3 className="text-xl">Audit history · {audit.name}</h3><Button onClick={() => setAudit(null)}>Close history</Button></div><p className="text-sm text-slate-400">Most recent 50 events. Successful reads are summarised by last use.</p>{audit.rows.map(row => <p key={row.id} className="text-sm text-slate-300">{when(row.created_at)} · {row.action} · {row.outcome} · request {row.request_id}</p>)}</Card>}
    </div>
  </div>;
}
