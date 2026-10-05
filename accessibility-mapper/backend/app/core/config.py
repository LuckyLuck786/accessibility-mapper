"""Application settings.

Everything is overridable through the environment (or a ``.env`` file sitting
next to ``requirements.txt``). The same codebase therefore runs in three
places without code changes:

* **Local dev** - ``DATABASE_URL`` unset falls back to a SQLite file so a judge
  can clone the repo and ``uvicorn app.main:app`` with no provisioning.
* **Container** - ``DATABASE_URL`` points at Postgres.
* **Vercel (serverless)** - ``DATABASE_URL`` points at hosted Postgres (Neon).
  Nothing is written to the filesystem except ``/tmp``, there is no background
  work, and the connection pool is ``NullPool`` because function instances are
  recycled constantly.

Only ``DATABASE_URL`` and ``ADMIN_TOKEN`` are strictly required in production;
everything else has a defensible default. See ``.env.example``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- identity ---------------------------------------------------------
    app_name: str = "Ghost Space - Campus Space & Accessibility Mapper"
    version: str = "2.0.0"
    api_prefix: str = "/api/v1"
    environment: str = "development"

    # --- persistence ------------------------------------------------------
    # Unset => zero-config SQLite for the local demo. On Vercel this MUST be a
    # hosted Postgres URL (``postgresql://...`` or ``postgres://...``); Neon
    # hands out the ``postgres://`` form and SQLAlchemy 2.x wants the explicit
    # ``postgresql+psycopg://`` driver name.
    database_url: str | None = None
    sqlite_path: Path = BACKEND_DIR / "data" / "accessibility.db"
    #: Optional PostGIS upgrade. Off by default - plain float columns plus
    #: haversine are enough at campus scale and keep the bundle small.
    use_postgis: bool = False
    auto_seed: bool = True
    seed_nodes: int = 34
    #: Neon aggressively closes idle connections; fail fast and retry instead of
    #: surfacing a 500 to the user.
    db_connect_retries: int = 3

    # --- media / privacy --------------------------------------------------
    # Media lives in Postgres (bytea) and is served from /api/v1/media/{id}.
    # There is no media directory: serverless filesystems are read-only.
    store_media_in_db: bool = True
    #: Client-side canvas compression targets <= 1.5 MB; the server refuses
    #: anything larger so a 12 MB phone photo cannot blow the 4.5 MB body cap.
    max_upload_bytes: int = 1_600_000
    #: Re-encoded JPEG ceiling. Anything bigger gets re-encoded again, smaller.
    max_stored_image_bytes: int = 320_000
    max_stored_edge_px: int = 1280
    blur_faces: bool = True
    blur_license_plates: bool = True
    redaction_min_area_px: int = 120

    # --- classifier -------------------------------------------------------
    # Barrier classification sits behind a `BarrierClassifier` interface:
    #   * empty CV_ENDPOINT_URL -> HeuristicBarrierClassifier (image features +
    #     reporter text). Fast, dependency-light, honestly labelled "heuristic".
    #   * CV_ENDPOINT_URL set   -> ExternalClassifier posts the JPEG to your
    #     own inference service and maps its JSON onto the same contract.
    # ultralytics/torch are deliberately NOT part of the deployed bundle.
    cv_endpoint_url: str = ""
    cv_endpoint_token: str = ""
    cv_endpoint_timeout_s: float = 12.0

    barrier_confidence_threshold: float = 0.85  # auto-verify above this
    confirmation_threshold: int = 2  # auto-verify at N citizen confirmations
    duplicate_radius_m: float = 15.0
    barrier_ttl_hours: int = 24 * 7
    #: Anti-abuse policy for *public* (unauthenticated) reports. Spec: a public
    #: report lands as "unverified" and expires. Staff reports carrying a valid
    #: admin token may still auto-verify on confidence alone.
    public_report_auto_verify: bool = False

    # --- public abuse limits ---------------------------------------------
    #: Reports accepted per client per rolling hour (counted in the DB).
    max_reports_per_hour: int = 8
    max_reports_per_day: int = 40

    # --- routing engine ---------------------------------------------------
    walk_speed_mps: float = 1.35
    wheelchair_speed_mps: float = 1.05
    stair_penalty_multiplier: float = 1.0
    barrier_weight_multiplier: float = 10.0
    max_snap_distance_m: float = 400.0
    max_matched_geometry_m: float = 5.0

    # --- Ghost Space engine ----------------------------------------------
    ghost_grace_minutes: int = 10  # after start before a release may fire
    ghost_probability_threshold: float = 0.7
    ghost_reclaim_window_minutes: int = 5
    ghost_beta_alpha: float = 1.0  # Beta prior for no-show smoothing
    ghost_beta_beta: float = 1.0
    #: Hours an empty-but-booked room keeps its lights/HVAC on in the baseline.
    ghost_setback_power_kw: float = 0.0
    ghost_demo_epoch_hour: int = 9  # demo day starts at 09:00
    ghost_demo_date: str = ""  # blank => next weekday from today

    # --- auth -------------------------------------------------------------
    jwt_secret: str = "dev-secret-change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 12
    #: Shared secret for the `X-Admin-Token` header. Every mutating admin action
    #: (resolve barrier, Ghost Space override, demo reset, seed) requires it.
    admin_token: str = ""
    #: Demo convenience: when true (the local default) admin *reads* stay open
    #: and mutations are accepted from the JWT alone. Production sets
    #: ENVIRONMENT=production, which forces ADMIN_TOKEN on every mutation.
    open_admin_endpoints: bool = True

    # --- CORS -------------------------------------------------------------
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://localhost:3000",
        ]
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept CSV, JSON array, or a real list for CORS_ORIGINS."""
        if isinstance(value, str):
            raw = value.strip()
            if raw.startswith("["):
                return raw
            return [part.strip() for part in raw.split(",") if part.strip()]
        return value

    # --- derived ----------------------------------------------------------
    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            url = self.database_url.strip()
            if url.startswith("postgres://"):
                return url.replace("postgres://", "postgresql+psycopg://", 1)
            if url.startswith("postgresql://"):
                return url.replace("postgresql://", "postgresql+psycopg://", 1)
            return url
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{self.sqlite_path}"

    @property
    def is_sqlite(self) -> bool:
        return self.resolved_database_url.startswith("sqlite")

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def media_url_prefix(self) -> str:
        """Where redacted images are served from (same origin, DB-backed)."""
        return f"{self.api_prefix}/media"

    def speed_for(self, wheelchair: bool) -> float:
        return self.wheelchair_speed_mps if wheelchair else self.walk_speed_mps


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()