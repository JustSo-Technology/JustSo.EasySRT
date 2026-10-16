"""Portable settings only. Import never writes runtime files or controls a service."""
import copy
from datetime import datetime, timezone
import hashlib
import json
from typing import Literal
from urllib.parse import urlsplit

from fastapi import HTTPException
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlmodel import Session, select

from app.core.settings import settings
from app.models.auth import User
from app.models.site_config import SavedDestinationRecord, SavedInputRecord, SavedSiteConfigRecord, SiteConfigState
from app.schemas.config import AppConfig, Destination, InputSource, StreamProfile
from app.services.config_service import load_bundle
from app.version import APP_VERSION, installed_commit

FORMAT = "justso.easysrt.configuration"
SCHEMA_VERSION = 1
MAX_BYTES = 1_048_576
MAX_ITEMS = 500
PREVIEW_TTL = 15 * 60
MODELS = {"preset": SavedSiteConfigRecord, "input": SavedInputRecord, "destination": SavedDestinationRecord}
PAYLOADS = {"preset": "site_payload", "input": "input_payload", "destination": "destination_payload"}


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(max_length=100)
    action: Literal["add", "skip", "replace"]
    name: str | None = Field(default=None, min_length=1, max_length=120)
    latency_ms: int | None = Field(default=None, gt=0, strict=True)


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document: dict
    decisions: list[Decision] = Field(default_factory=list, max_length=MAX_ITEMS)
    preview_token: str | None = Field(default=None, max_length=4000)


def invalid(message: str, code: int = 422):
    raise HTTPException(code, message)


def _strict_json(raw: bytes | str):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                invalid("Duplicate JSON fields are unsupported")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique_object, parse_constant=lambda _: invalid("Invalid JSON number"))


def parse_request(raw: bytes) -> ImportRequest:
    if len(raw) > MAX_BYTES:
        invalid("Configuration request exceeds 1 MiB", 413)
    try:
        return ImportRequest.model_validate(_strict_json(raw))
    except (ValueError, TypeError, RecursionError):
        # Do not echo validation input: documents can contain URL credentials.
        invalid("Invalid configuration import request")


def _keys(value, allowed: set[str], required: set[str], label: str):
    if not isinstance(value, dict) or set(value) - allowed or required - set(value):
        invalid(f"Unsupported or missing fields in {label}")


def _model(model, value, label):
    fields = set(model.model_fields)
    _keys(value, fields, fields, label)
    if model is Destination and isinstance(value.get("host"), str) and "://" in value["host"]:
        invalid("Use a plain destination host with separate protocol and port; embedded URL options cannot be imported")
    try:
        return model.model_validate(value).model_dump(mode="json")
    except (ValidationError, ValueError, TypeError):
        invalid(f"Invalid {label}; check supported values and units")


def _site(value):
    _keys(value, {"input", "destination", "profile"}, {"input", "destination", "profile"}, "site")
    return {
        "input": _model(InputSource, value["input"], "input"),
        "destination": _model(Destination, value["destination"], "destination"),
        "profile": _model(StreamProfile, value["profile"], "profile"),
    }


def _name(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 120:
        invalid("Names must contain 1–120 characters")
    return value.strip()


def _legacy_payload(value):
    if isinstance(value, str):
        try:
            return _strict_json(value)
        except (ValueError, RecursionError):
            invalid("Invalid legacy saved payload")
    return value


def normalize(document: dict):
    """Explicit adapters: portable v1, April extraction, bare site and old bundle."""
    try:
        doc = copy.deepcopy(document)
    except RecursionError:
        invalid("Configuration document nesting is too deep")
    legacy = False
    warnings = []
    if doc.get("format") == FORMAT:
        if type(doc.get("schema_version")) is not int or doc["schema_version"] != SCHEMA_VERSION:
            invalid("Unsupported configuration schema version; update EasySRT or use a supported export")
        _keys(doc, {"format", "schema_version", "source", "exported_at", "station", "presets", "inputs", "destinations", "current"},
              {"format", "schema_version", "presets", "inputs", "destinations"}, "configuration document")
        if "source" in doc:
            _keys(doc["source"], {"app_version", "commit"}, set(), "source metadata")
    elif doc.get("format") == "justso.easysrt.legacy-extraction":
        if type(doc.get("extraction_version")) is not int or doc["extraction_version"] != 1:
            invalid("Unsupported legacy extraction version")
        _keys(doc, {"format", "extraction_version", "note", "source", "app", "active_site", "runtime_observation", "saved_configs", "saved_inputs", "saved_destinations", "selection_state"},
              {"format", "extraction_version", "saved_configs", "saved_inputs", "saved_destinations", "active_site"}, "legacy extraction")
        legacy = True
        for collection, payload in [("saved_configs", "site_payload"), ("saved_inputs", "input_payload"), ("saved_destinations", "destination_payload")]:
            if not isinstance(doc[collection], list) or len(doc[collection]) > MAX_ITEMS:
                invalid("Invalid legacy collection or too many entries")
            for row in doc[collection]:
                allowed = {"id", "name", payload, "created_at", "updated_at", "created_by_user_id", "last_loaded_at"}
                _keys(row, allowed, {"name", payload}, "legacy record")
        presets = [{"name": r["name"], "site": _legacy_payload(r["site_payload"])} for r in doc["saved_configs"]]
        inputs = [_legacy_payload(r["input_payload"]) for r in doc["saved_inputs"]]
        destinations = [_legacy_payload(r["destination_payload"]) for r in doc["saved_destinations"]]
        doc = {"presets": presets, "inputs": inputs, "destinations": destinations,
               "current": {"name": "Imported current configuration", "site": doc["active_site"]}, "station": doc.get("app")}
        warnings.append("Historical IDs, attribution, selection state and runtime observations are excluded. The current snapshot is a separate inactive preset.")
    elif set(doc) == {"input", "destination", "profile"}:
        legacy = True
        doc = {"presets": [{"name": "Imported configuration", "site": doc}], "inputs": [], "destinations": []}
    elif set(doc) == {"app", "site", "runtime"}:
        legacy = True
        doc = {"presets": [], "inputs": [], "destinations": [], "station": doc["app"],
               "current": {"name": "Imported current configuration", "site": doc["site"]}}
        warnings.append("The old runtime command is excluded and will never be executed.")
    else:
        invalid("Unrecognized format. Flat legacy-controller configurations are unsupported; export EasySRT settings instead")
    items = []
    if doc.get("station") is not None:
        _model(AppConfig, doc["station"], "station metadata")
        warnings.append("Station metadata is for reference; importing does not change this installation's station settings.")
    for collection, kind in [("presets", "preset"), ("inputs", "input"), ("destinations", "destination")]:
        rows = doc.get(collection)
        if not isinstance(rows, list) or len(rows) > MAX_ITEMS:
            invalid("Invalid collection or too many entries")
        for i, value in enumerate(rows):
            if kind == "preset":
                _keys(value, {"name", "site"}, {"name", "site"}, "preset")
                payload, name = _site(value["site"]), _name(value["name"])
            else:
                payload = _model(InputSource if kind == "input" else Destination, value, kind)
                name = _name(payload["name"])
            items.append({"key": f"{kind}:{i}", "kind": kind, "name": name, "payload": payload})
    if doc.get("current") is not None:
        current = doc["current"]
        _keys(current, {"name", "site"}, {"name", "site"}, "current snapshot")
        items.append({"key": "current", "kind": "preset", "name": _name(current["name"]), "payload": _site(current["site"])})
    if not items or len(items) > MAX_ITEMS:
        invalid("Import must contain 1–500 entries")
    if legacy:
        warnings.append("Older EasySRT emitted SRT latency values as microseconds despite the millisecond field name. Explicitly review milliseconds for each imported SRT preset; receiver latency is not inferred.")
    return items, legacy, warnings


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _state(session):
    rows = {kind: sorted([r.model_dump(mode="json") for r in session.exec(select(model)).all()], key=lambda r: r["id"]) for kind, model in MODELS.items()}
    rows["selection"] = [r.model_dump(mode="json") for r in session.exec(select(SiteConfigState)).all()]
    rows["files"] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None for p in
                     [settings.app_config_path, settings.site_config_path, settings.runtime_config_path, settings.sender_env_path]}
    return _hash(rows)


def redact(value):
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str) and "://" in value:
        try:
            u = urlsplit(value)
            host = u.netloc.rsplit("@", 1)[-1]
            return f"{u.scheme}://{'[credentials]@' if u.username is not None else ''}{host}{u.path}{'?[query redacted]' if u.query else ''}{'#[fragment redacted]' if u.fragment else ''}"
        except ValueError:
            return "[URL redacted]"
    return value


def _plan(session: Session, request: ImportRequest):
    items, legacy, warnings = normalize(request.document)
    decisions = {d.key: d for d in request.decisions}
    if len(decisions) != len(request.decisions) or set(decisions) - {i["key"] for i in items}:
        invalid("Duplicate or unknown import decision")
    errors, chosen = [], set()
    active = session.get(SiteConfigState, "default")
    for item in items:
        decision = decisions.get(item["key"])
        name = _name(decision.name) if decision and decision.name is not None else item["name"]
        model = MODELS[item["kind"]]
        target = session.exec(select(model).where(model.name == name)).first()
        action = decision.action if decision else ("skip" if target else "add")
        review = legacy and item["kind"] == "preset" and item["payload"]["destination"]["protocol"] == "srt"
        source_latency = item["payload"]["profile"]["srt_latency_ms"] if item["kind"] == "preset" else None
        latency = decision.latency_ms if decision else None
        if latency is not None and item["kind"] != "preset":
            invalid("Latency decisions apply only to presets")
        if item["kind"] == "preset" and latency is not None:
            item["payload"]["profile"]["srt_latency_ms"] = latency
        if action != "skip":
            if review and latency is None:
                errors.append(f'{item["key"]}: review SRT latency in milliseconds')
            if action == "add" and target:
                errors.append(f'{item["key"]}: name already exists; skip, rename or explicitly replace')
            if action == "replace" and not target:
                errors.append(f'{item["key"]}: replacement target no longer exists')
            if action == "replace" and item["kind"] == "preset" and active and target and active.active_saved_config_id == target.id:
                errors.append(f'{item["key"]}: active preset cannot be replaced; import under a different name')
            identity = (item["kind"], name)
            if identity in chosen:
                errors.append(f'{item["key"]}: duplicate target name in this import')
            chosen.add(identity)
        if item["kind"] != "preset":
            item["payload"]["name"] = name
        item.update(name=name, action=action, conflict=target is not None, target_id=target.id if target else None,
                    requires_latency_review=review, source_latency_ms=source_latency,
                    latency_ms=item["payload"]["profile"]["srt_latency_ms"] if item["kind"] == "preset" else None)
    return items, warnings, errors


def _serializer():
    return URLSafeTimedSerializer(settings.secret_key, salt="easysrt-config-import-v1")


def preview(session: Session, request: ImportRequest, user: User):
    items, warnings, errors = _plan(session, request)
    state = _state(session)
    token = _serializer().dumps({"user": user.id, "plan": _hash(items), "state": state,
                                 "request": _hash({"document": request.document, "decisions": [d.model_dump() for d in request.decisions]})})
    public = [redact({k: v for k, v in item.items() if k not in {"payload", "target_id"}} | {"settings": item["payload"]}) for item in items]
    return {"items": public, "warnings": warnings, "errors": errors, "can_import": not errors and any(i["action"] != "skip" for i in items), "preview_token": token}


def commit_import(session: Session, request: ImportRequest, user: User):
    try:
        claims = _serializer().loads(request.preview_token or "", max_age=PREVIEW_TTL)
    except (BadSignature, SignatureExpired):
        invalid("Preview expired or invalid; preview the import again", 409)
    # Serialize conflict checks and writes against other SQLite writers.
    session.connection().exec_driver_sql("BEGIN IMMEDIATE")
    try:
        items, _, errors = _plan(session, request)
        expected = {"user": user.id, "plan": _hash(items), "state": _state(session),
                    "request": _hash({"document": request.document, "decisions": [d.model_dump() for d in request.decisions]})}
        if claims != expected:
            invalid("Import or saved configuration changed; preview again", 409)
        if errors:
            invalid("Resolve all preview errors before importing")
        imported = []
        for item in items:
            if item["action"] == "skip":
                continue
            model = MODELS[item["kind"]]
            record = session.get(model, item["target_id"]) if item["target_id"] else model(name=item["name"], **{PAYLOADS[item["kind"]]: ""})
            setattr(record, PAYLOADS[item["kind"]], json.dumps(item["payload"]))
            record.updated_at = datetime.now(timezone.utc)
            if item["kind"] == "preset":
                record.created_by_user_id = user.id
            session.add(record)
            imported.append({"key": item["key"], "id": record.id, "kind": item["kind"], "name": redact(item["name"])})
        session.commit()
        return {"imported": imported, "active_configuration_changed": False}
    except Exception:
        session.rollback()
        raise


def export_document(session: Session):
    bundle = load_bundle()
    doc = {"format": FORMAT, "schema_version": SCHEMA_VERSION,
           "source": {"app_version": APP_VERSION, "commit": installed_commit()},
           "exported_at": datetime.now(timezone.utc).isoformat(), "station": bundle.app.model_dump(mode="json"),
           "presets": [{"name": r.name, "site": json.loads(r.site_payload)} for r in session.exec(select(SavedSiteConfigRecord).order_by(SavedSiteConfigRecord.name)).all()],
           "inputs": [json.loads(r.input_payload) for r in session.exec(select(SavedInputRecord).order_by(SavedInputRecord.name)).all()],
           "destinations": [json.loads(r.destination_payload) for r in session.exec(select(SavedDestinationRecord).order_by(SavedDestinationRecord.name)).all()],
           "current": {"name": "Imported current configuration", "site": bundle.site.model_dump(mode="json")}}
    normalize(doc)
    if len(json.dumps(doc).encode()) > MAX_BYTES // 2:
        invalid("Export too large for a portable import; reduce the saved collection", 413)
    return doc
