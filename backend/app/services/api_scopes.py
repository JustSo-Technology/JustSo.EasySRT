"""The supported operation catalogue. Presets expand once; no runtime wildcards."""
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.models.auth import UserRole

# group, resource kind, minimum role. Operator cannot Apply under #16's policy.
SCOPES: dict[str, tuple[str, str, str]] = {}

def add(group, kind, role, *actions):
    for action in actions:
        SCOPES[action] = (group, kind, role)

add('Monitoring', 'path', 'operator', 'service:read', 'health:read', 'metrics:read', 'health-events:read')
add('Monitoring', 'instance', 'operator', 'system:read', 'redundancy:read', 'config-sync:read')
add('Troubleshooting', 'path', 'engineer', 'diagnostics:read', 'diagnostics:run', 'logs:read')
add('Stream control', 'path', 'operator', 'service:start', 'service:stop', 'service:restart')
add('Active configuration', 'instance', 'engineer', 'config:read', 'config-app:update', 'config:validate')
add('Preset library', 'preset', 'operator', 'presets:read')
add('Preset library', 'preset', 'engineer', 'presets:create', 'presets:update', 'presets:delete', 'presets:apply')
for kind, prefix in [('input', 'inputs'), ('destination', 'destinations')]:
    add('Sources and destinations', kind, 'engineer', *(f'{prefix}:{a}' for a in ('read', 'create', 'update', 'delete')))
add('Transfer', 'instance', 'engineer', 'config:export', 'config-import:preview', 'config:import')
add('Secrets', 'any', 'engineer', 'secrets:read', 'secrets:update')
add('Audit', 'instance', 'owner', 'audit:read')
add('Updates', 'instance', 'owner', 'updates:read', 'updates:check')

DESCRIPTIONS = {'secrets:read': 'Reveal complete source URLs, including private path segments, credentials and query values.',
                'secrets:update': 'Write or replace sensitive source URLs without revealing their stored values.',
                'presets:apply': 'Select a reviewed preset for the next Start/Restart; does not restart the sender.',
                'service:restart': 'Interrupt and restart the selected sender.',
                'diagnostics:run': 'Run active reachability checks against configured endpoints.'}

RANK = {'operator': 0, 'engineer': 1, 'owner': 2}

def role_allows(role: UserRole, scope: str):
    return scope in SCOPES and RANK[role.value if isinstance(role, UserRole) else role] >= RANK[SCOPES[scope][2]]


class ScopeGrant(BaseModel):
    model_config = ConfigDict(extra='forbid')
    scope: str
    kind: str
    resource_id: str = Field(min_length=1, max_length=120)
    target: str | None = None

    @model_validator(mode='after')
    def supported(self):
        if self.scope not in SCOPES:
            raise ValueError('Unsupported scope')
        expected = SCOPES[self.scope][1]
        if self.kind not in ({'instance', 'preset', 'input', 'destination'} if expected == 'any' else {expected}):
            raise ValueError('Incorrect resource kind')
        if self.kind == 'path' and self.resource_id != 'default':
            raise ValueError('Only path default is supported')
        if self.scope.endswith(':create') and self.resource_id != '*':
            raise ValueError('Create requires explicit collection access')
        if self.scope == 'presets:apply':
            if self.target != 'default':
                raise ValueError('Apply requires target default')
        elif self.target is not None:
            raise ValueError('Target is only valid for Apply')
        return self

MONITOR = ['service:read', 'health:read', 'metrics:read', 'system:read', 'redundancy:read']
LIBRARIAN = ['presets:read', 'presets:create', 'presets:update', 'inputs:read', 'inputs:create', 'inputs:update',
             'destinations:read', 'destinations:create', 'destinations:update', 'config:validate']
BACKUP = ['config:read', 'presets:read', 'inputs:read', 'destinations:read', 'config:export']
PRESETS = {
    'monitor': MONITOR,
    'troubleshooting': MONITOR + ['health-events:read', 'diagnostics:read', 'diagnostics:run', 'logs:read', 'config-sync:read'],
    'stream-operator': ['service:read', 'health:read', 'presets:read', 'presets:apply', 'service:start', 'service:stop', 'service:restart'],
    'preset-librarian': LIBRARIAN,
    'configuration-engineer': LIBRARIAN + ['config:read', 'config-app:update', 'presets:apply'],
    'configuration-backup': BACKUP,
    'configuration-transfer': BACKUP + ['config-import:preview', 'config:import', 'presets:create', 'presets:update',
                                    'inputs:create', 'inputs:update', 'destinations:create', 'destinations:update'],
    'custom': [],
}


def template_grants(name, instance_id):
    return [ScopeGrant(scope=scope, kind=SCOPES[scope][1],
                       resource_id='default' if SCOPES[scope][1] == 'path' else instance_id if SCOPES[scope][1] == 'instance' else '*',
                       target='default' if scope == 'presets:apply' else None).model_dump() for scope in PRESETS[name]]
