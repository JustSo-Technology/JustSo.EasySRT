// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiTokensPanel } from './api-tokens-panel';
import { tokenApi, type IntegrationToken, type ScopeGrant, type TokenCatalogue } from '@/lib/api';

const user = { id: 'owner', username: 'Owner', role: 'owner' as const, disabled: false };
const health: ScopeGrant = { scope: 'health:read', kind: 'path', resource_id: 'default', target: null };
const read: ScopeGrant = { scope: 'presets:read', kind: 'preset', resource_id: '*', target: null };
const update: ScopeGrant = { scope: 'presets:update', kind: 'preset', resource_id: '*', target: null };
const cat: TokenCatalogue = {
  instance_id: 'local', endpoints: {}, resources: { path: [{ id: 'default', name: 'Sender' }], preset: [{ id: 'a', name: 'Studio A' }, { id: 'b', name: 'Studio B' }] },
  scopes: [{ id: health.scope, group: 'Monitoring', kind: 'path', minimum_role: 'operator' },
    { id: read.scope, group: 'Preset library', kind: 'preset', minimum_role: 'operator' },
    { id: update.scope, group: 'Preset library', kind: 'preset', minimum_role: 'engineer' }],
  presets: [{ id: 'monitor', version: 1, grants: [health] }, { id: 'preset-librarian', version: 1, grants: [read, update] }, { id: 'custom', version: 1, grants: [] }],
};
const token: IntegrationToken = { id: 'token1', name: 'Studio monitor', integration: 'dashboard', owner_id: user.id, creator_id: user.id,
  instance_id: 'local', preset: 'monitor', preset_version: 1, revision: 1, grants: [health], effective_grants: [health], status: 'active',
  created_at: '2026-10-24T00:00:00Z', expires_at: '2027-01-01T00:00:00Z', revoked_at: null, last_used_at: null,
  credentials: [{ id: 'c1', prefix: 'esrt_123…', created_at: '2026-10-24T00:00:00Z', last_used_at: null, retire_at: null, revoked_at: null }] };
beforeEach(() => {
  vi.spyOn(tokenApi, 'catalogue').mockResolvedValue(cat);
  vi.spyOn(tokenApi, 'list').mockResolvedValue({ items: [] });
  vi.spyOn(tokenApi, 'create').mockResolvedValue({ token, secret: 'test-secret-only-once' });
  vi.spyOn(tokenApi, 'update').mockResolvedValue(token);
  vi.spyOn(tokenApi, 'rotate').mockResolvedValue({ token, secret: 'replacement-secret' });
  vi.spyOn(tokenApi, 'revoke').mockResolvedValue({ revoked_ids: ['token1'] });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
async function createForm() {
  render(<ApiTokensPanel users={[user]} currentUser={user} onClose={vi.fn()} />);
  await screen.findByText('No API tokens yet');
  fireEvent.click(screen.getByRole('button', { name: 'Create token' }));
  fireEvent.change(screen.getByLabelText('Token name'), { target: { value: 'Monitor' } });
  fireEvent.change(screen.getByLabelText('Integration'), { target: { value: 'My dashboard' } });
}

it('reviews explicit permissions before issuing and dismisses the only secret reveal', async () => {
  await createForm();
  fireEvent.click(screen.getByRole('button', { name: 'Review permissions' }));
  expect(tokenApi.create).not.toHaveBeenCalled();
  expect(screen.getByText('Review token access')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Confirm your current Owner password'), { target: { value: 'password' } });
  fireEvent.click(screen.getByRole('button', { name: 'Create and reveal token' }));
  await screen.findByText('Copy your token now');
  expect(tokenApi.create).toHaveBeenCalledWith(expect.objectContaining({ grants: [health], name: 'Monitor', integration: 'My dashboard' }));
  fireEvent.click(screen.getByRole('button', { name: 'I’ve saved it — dismiss secret' }));
  expect(screen.queryByDisplayValue('test-secret-only-once')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
  await waitFor(() => expect(tokenApi.list).toHaveBeenCalledTimes(3));
  expect(screen.queryByDisplayValue('test-secret-only-once')).toBeNull();
});

it('supports individual resources and leaves group selection indeterminate', async () => {
  await createForm();
  fireEvent.change(screen.getByLabelText('Permission preset'), { target: { value: 'preset-librarian' } });
  fireEvent.change(screen.getByLabelText('presets:read resource 0'), { target: { value: 'a' } });
  fireEvent.click(screen.getByLabelText('presets:update'));
  expect((screen.getByLabelText('Preset library') as HTMLInputElement).indeterminate).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Review permissions' }));
  fireEvent.change(screen.getByLabelText('Confirm your current Owner password'), { target: { value: 'password' } });
  fireEvent.click(screen.getByRole('button', { name: 'Create and reveal token' }));
  await waitFor(() => expect(tokenApi.create).toHaveBeenCalledWith(expect.objectContaining({ grants: [{ ...read, resource_id: 'a' }] })));
});

it('adds a second preset without restoring a removed permission automatically', async () => {
  await createForm();
  fireEvent.change(screen.getByLabelText('Add another preset'), { target: { value: 'preset-librarian' } });
  fireEvent.click(screen.getByRole('button', { name: 'Add preset permissions' }));
  expect((screen.getByLabelText('health:read') as HTMLInputElement).checked).toBe(true);
  fireEvent.click(screen.getByLabelText('presets:update'));
  fireEvent.change(screen.getByLabelText('Find permission'), { target: { value: 'preset' } });
  expect((screen.getByLabelText('presets:update') as HTMLInputElement).checked).toBe(false);
});

it('checks rotation overlap and owner password separately from ordinary token metadata', async () => {
  vi.mocked(tokenApi.list).mockResolvedValue({ items: [token] });
  render(<ApiTokensPanel users={[user]} currentUser={user} onClose={vi.fn()} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Rotate' }));
  expect(tokenApi.rotate).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText('Old credential overlap'), { target: { value: '3600' } });
  fireEvent.change(screen.getByLabelText('Current Owner password'), { target: { value: 'password' } });
  fireEvent.click(screen.getByRole('button', { name: 'Rotate and reveal new token' }));
  await screen.findByDisplayValue('replacement-secret');
  expect(tokenApi.rotate).toHaveBeenCalledWith('token1', { expected_revision: 1, overlap_seconds: 3600, current_password: 'password' });
});

it('requires an explicit confirmation to revoke selected tokens', async () => {
  vi.mocked(tokenApi.list).mockResolvedValue({ items: [token] });
  render(<ApiTokensPanel users={[user]} currentUser={user} onClose={vi.fn()} />);
  fireEvent.click(await screen.findByLabelText('Select Studio monitor'));
  fireEvent.click(screen.getByRole('button', { name: 'Revoke selected (1)' }));
  expect(tokenApi.revoke).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Confirm revoke' }));
  await waitFor(() => expect(tokenApi.revoke).toHaveBeenCalledWith(['token1']));
});

it('keeps a stale edit visible and does not silently retry it', async () => {
  vi.mocked(tokenApi.list).mockResolvedValue({ items: [token] });
  vi.mocked(tokenApi.update).mockRejectedValue(new Error('Token changed; refresh before editing'));
  render(<ApiTokensPanel users={[user]} currentUser={user} onClose={vi.fn()} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Edit permissions' }));
  fireEvent.change(screen.getByLabelText('Token name'), { target: { value: 'Updated monitor' } });
  fireEvent.click(screen.getByRole('button', { name: 'Review permissions' }));
  fireEvent.change(screen.getByLabelText('Confirm your current Owner password'), { target: { value: 'password' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save token changes' }));
  await screen.findByText('Token changed; refresh before editing');
  expect(tokenApi.update).toHaveBeenCalledTimes(1);
  expect(screen.getByText('Updated monitor')).toBeTruthy();
  expect((screen.getByLabelText('Confirm your current Owner password') as HTMLInputElement).value).toBe('');
});
