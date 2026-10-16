import json
import platform
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.models.redundancy import PartnerSyncState, ReplicatedConfigState, ReplicatedConfigVersionRecord
from app.schemas.config import AppConfig, SiteConfig
from app.schemas.replicated_config import PartnerAckRequest, ReplicatedConfigStatus
from app.services.config_service import load_bundle


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _local_node_name() -> str:
    return platform.node() or "local-node"


def _get_or_create_partner_state(session: Session) -> PartnerSyncState:
    partner_state = session.get(PartnerSyncState, "partner")
    if partner_state is None:
        partner_state = PartnerSyncState()
        session.add(partner_state)
        session.commit()
        session.refresh(partner_state)
    return partner_state


def _snapshot_state(app_config: AppConfig, site_config: SiteConfig) -> tuple[str, str]:
    return json.dumps(app_config.model_dump()), json.dumps(site_config.model_dump())


def ensure_replicated_config_state(session: Session) -> ReplicatedConfigState:
    state = session.get(ReplicatedConfigState, "default")
    if state is not None:
        _get_or_create_partner_state(session)
        return state

    bundle = load_bundle()
    node_name = _local_node_name()
    now = _utcnow()
    app_payload, site_payload = _snapshot_state(bundle.app, bundle.site)
    state = ReplicatedConfigState(
        authority_node_id=node_name,
        authority_node_label=node_name,
        current_version=1,
        last_change_summary="Initialized from local config",
        last_changed_at=now,
        updated_at=now,
    )
    version_record = ReplicatedConfigVersionRecord(
        version=1,
        app_payload=app_payload,
        site_payload=site_payload,
        change_summary=state.last_change_summary,
        origin_node_id=node_name,
        origin_node_label=node_name,
        created_at=now,
    )
    session.add(state)
    session.add(version_record)
    _get_or_create_partner_state(session)
    session.commit()
    session.refresh(state)
    return state


def record_replicated_config_change(
    session: Session,
    *,
    app_config: AppConfig,
    site_config: SiteConfig,
    changed_by_user_id: str | None,
    change_summary: str,
) -> ReplicatedConfigState:
    state = ensure_replicated_config_state(session)
    partner_state = _get_or_create_partner_state(session)
    now = _utcnow()
    next_version = state.current_version + 1
    app_payload, site_payload = _snapshot_state(app_config, site_config)

    version_record = ReplicatedConfigVersionRecord(
        version=next_version,
        app_payload=app_payload,
        site_payload=site_payload,
        changed_by_user_id=changed_by_user_id,
        change_summary=change_summary,
        origin_node_id=state.authority_node_id,
        origin_node_label=state.authority_node_label,
        created_at=now,
    )
    state.current_version = next_version
    state.last_change_summary = change_summary
    state.last_changed_by_user_id = changed_by_user_id
    state.last_changed_at = now
    state.updated_at = now

    if partner_state.partner_node_id:
        partner_state.sync_state = "awaiting_ack"
        partner_state.takeover_eligibility = "ineligible_config_behind"
        partner_state.last_sync_attempt_at = now
        partner_state.updated_at = now

    session.add(version_record)
    session.add(state)
    session.add(partner_state)
    session.commit()
    session.refresh(state)
    return state


def acknowledge_partner_version(session: Session, payload: PartnerAckRequest) -> ReplicatedConfigStatus:
    state = ensure_replicated_config_state(session)
    partner_state = _get_or_create_partner_state(session)
    now = _utcnow()

    partner_state.partner_node_id = payload.partner_node_id
    partner_state.partner_node_label = payload.partner_node_label
    partner_state.last_acked_version = payload.acked_version
    partner_state.runtime_validation_state = payload.runtime_validation_state
    partner_state.last_error = payload.error
    partner_state.updated_at = now

    if payload.error:
        partner_state.sync_state = "sync_failed"
        partner_state.takeover_eligibility = "unknown"
    elif payload.acked_version < state.current_version:
        partner_state.sync_state = "behind"
        partner_state.takeover_eligibility = "ineligible_config_behind"
    elif payload.runtime_validation_state != "valid":
        partner_state.sync_state = "up_to_date"
        partner_state.takeover_eligibility = "ineligible_runtime_invalid"
        partner_state.last_sync_success_at = now
    else:
        partner_state.sync_state = "up_to_date"
        partner_state.takeover_eligibility = "eligible"
        partner_state.last_sync_success_at = now

    session.add(partner_state)
    session.commit()
    return get_replicated_config_status(session)


def get_replicated_config_status(session: Session) -> ReplicatedConfigStatus:
    state = ensure_replicated_config_state(session)
    partner_state = _get_or_create_partner_state(session)
    return ReplicatedConfigStatus(
        authority_node_id=state.authority_node_id,
        authority_node_label=state.authority_node_label,
        current_version=state.current_version,
        last_change_summary=state.last_change_summary,
        last_changed_at=state.last_changed_at,
        last_changed_by_user_id=state.last_changed_by_user_id,
        partner_node_id=partner_state.partner_node_id,
        partner_node_label=partner_state.partner_node_label,
        last_acked_version=partner_state.last_acked_version,
        partner_sync_state=partner_state.sync_state,
        runtime_validation_state=partner_state.runtime_validation_state,
        takeover_eligibility=partner_state.takeover_eligibility,
        last_sync_attempt_at=partner_state.last_sync_attempt_at,
        last_sync_success_at=partner_state.last_sync_success_at,
        last_error=partner_state.last_error,
    )
