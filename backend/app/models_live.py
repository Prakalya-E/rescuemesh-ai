"""Tables for live ingestion, model registry and risk assessments.
Additive only: does not change users / recommendations / audit_log.
All datetimes are stored as UTC."""
from datetime import datetime, timezone
from sqlalchemy import (JSON, CheckConstraint, DateTime, Float, ForeignKey, Index,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


def utcnow():
    return datetime.now(timezone.utc)


class DataSource(Base):
    __tablename__ = "data_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    provider: Mapped[str] = mapped_column(String(100))
    hazard: Mapped[str] = mapped_column(String(30))
    base_url: Mapped[str] = mapped_column(String(300), default="")
    requires_key: Mapped[bool] = mapped_column(default=False)
    license_note: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(default=True)
    stale_after_minutes: Mapped[int] = mapped_column(default=180)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")
    http_status: Mapped[int | None] = mapped_column(nullable=True)
    records_fetched: Mapped[int] = mapped_column(default=0)
    records_new: Mapped[int] = mapped_column(default=0)
    records_updated: Mapped[int] = mapped_column(default=0)
    records_rejected: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (
        CheckConstraint("status in ('running','success','failed','skipped')", name="ck_run_status"),
        Index("ix_runs_source_started", "source_id", "started_at"),
    )


class LiveObservation(Base):
    __tablename__ = "live_observations"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("ingestion_runs.id"), nullable=True)
    external_id: Mapped[str] = mapped_column(String(120))
    hazard: Mapped[str] = mapped_column(String(30))
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))   # time reported by the source
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    magnitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    place: Mapped[str | None] = mapped_column(String(300), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)       # original source record
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_obs_source_external"),
        CheckConstraint("latitude between -90 and 90 and longitude between -180 and 180", name="ck_obs_coords"),
        Index("ix_obs_hazard_time", "hazard", "event_time"),
    )


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    hazard: Mapped[str] = mapped_column(String(30))
    version: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(20))            # 'ml' or 'rule_based'
    artifact_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    trained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    features: Mapped[list | None] = mapped_column(JSON, nullable=True)
    data_provenance: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    __table_args__ = (
        UniqueConstraint("hazard", "version", name="uq_model_hazard_version"),
        CheckConstraint("kind in ('ml','rule_based')", name="ck_model_kind"),
    )


class RiskAssessment(Base):
    """risk_score is a relative ranking score, NOT a calibrated probability
    and NOT an official warning."""
    __tablename__ = "risk_assessments"
    id: Mapped[int] = mapped_column(primary_key=True)
    model_version_id: Mapped[int | None] = mapped_column(ForeignKey("model_versions.id"), nullable=True)
    observation_id: Mapped[int | None] = mapped_column(ForeignKey("live_observations.id"), nullable=True)
    hazard: Mapped[str] = mapped_column(String(30))
    district: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_score: Mapped[float] = mapped_column(Float)
    risk_level: Mapped[str] = mapped_column(String(20))
    method: Mapped[str] = mapped_column(String(20))         # ml | rule_based | hybrid
    inputs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        CheckConstraint("risk_level in ('low','medium','high','severe')", name="ck_risk_level"),
        CheckConstraint("method in ('ml','rule_based','hybrid')", name="ck_risk_method"),
        Index("ix_risk_hazard_district", "hazard", "district"),
    )
