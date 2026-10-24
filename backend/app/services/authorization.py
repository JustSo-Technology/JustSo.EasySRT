"""Session policy and resource-bound grants shared with future API credentials."""
from dataclasses import dataclass

from fastapi import Depends, HTTPException

from app.api.deps import require_user
from app.models.auth import User, UserRole


LIBRARY = frozenset({"presets:read", "presets:create", "presets:update", "presets:delete", "presets:apply",
                     "inputs:create", "destinations:create", "config-app:update"})
SERVICE = frozenset({"service:read", "service:start", "service:stop", "service:restart"})


@dataclass(frozen=True)
class Grant:
    action: str
    preset_id: str | None = None  # None explicitly means the whole local collection.
    target: str | None = None


@dataclass(frozen=True)
class Principal:
    user: User
    grants: tuple[Grant, ...]

    def allows(self, action: str, *, preset_id: str | None = None, target: str | None = None) -> bool:
        # One grant must satisfy BOTH source and target; never cross-product grants.
        return any(g.action == action and (g.preset_id is None or g.preset_id == preset_id)
                   and (g.target is None or g.target == target) for g in self.grants)

    def require(self, action: str, *, preset_id: str | None = None, target: str | None = None) -> None:
        if not self.allows(action, preset_id=preset_id, target=target):
            raise HTTPException(403, "Permission denied")

    @property
    def capabilities(self) -> list[str]:
        return sorted({g.action for g in self.grants})


def require_principal(user: User = Depends(require_user)) -> Principal:
    actions = SERVICE | (LIBRARY if user.role in {UserRole.OWNER, UserRole.ENGINEER} else {"presets:read"})
    return Principal(user, tuple(Grant(action) for action in actions))
