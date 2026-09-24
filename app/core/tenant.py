"""
app/core/tenant.py
──────────────────
Installation (tenant) configuration for MadziHub.

Each installation serves exactly one utility. Everything that differs between
utilities — identity, currency, fiscal calendar, hierarchy labels, zone list,
targets, thresholds, strategic-plan KPIs, enabled modules and AI policy — is
read from ``tenants/<name>/tenant.yaml`` instead of being hardcoded.

Select the tenant with ``MADZI_TENANT`` (a folder name under ``tenants/`` or a
path to a YAML file). The default is ``srwb`` so the reference installation
keeps working unchanged during the transition.
"""
from __future__ import annotations

import calendar
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml
from pydantic import BaseModel, Field, field_validator

from app.core.config import BASE_DIR, settings

TENANTS_DIR = BASE_DIR / "tenants"
MONTH_NAMES = list(calendar.month_name)[1:]


class Identity(BaseModel):
    name: str
    short_name: str
    product_title: str = "MadziHub"
    tagline: str = "Every drop, accounted for."
    country: Optional[str] = None
    regulator: Optional[str] = None
    registration_no: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    website: Optional[str] = None
    service_area_km2: Optional[float] = None
    population_served: Optional[int] = None


class Branding(BaseModel):
    logo: Optional[str] = None           # file name inside the tenant folder
    primary_color: str = "#0f766e"
    accent_color: str = "#0369a1"


class Currency(BaseModel):
    code: str = "USD"
    symbol: str = "$"
    decimals: int = 0


class FiscalYearCfg(BaseModel):
    start_month: int = Field(4, ge=1, le=12)


class Level(BaseModel):
    key: str
    label: str
    plural: str


class Zone(BaseModel):
    name: str
    color: str = "#64748b"


class Hierarchy(BaseModel):
    levels: List[Level] = [
        Level(key="zone", label="Zone", plural="Zones"),
        Level(key="scheme", label="Scheme", plural="Schemes"),
    ]
    zones: List[Zone] = []


class StrategicKpi(BaseModel):
    focus_area: str
    name: str
    unit: str
    # int | float keeps whole numbers as ints so API output matches the source plan.
    baseline: Optional[Union[int, float]] = None
    targets: Dict[int, Optional[Union[int, float]]] = {}
    actual_key: Optional[str] = None
    direction: str = "high"              # "high" | "low"
    capture: str = "gap"                 # "live" | "operational" | "gap"


class StrategicPlan(BaseModel):
    title: str = "Strategic Plan"
    years: List[int] = []
    default_year: Optional[int] = None
    kpis: List[StrategicKpi] = []


class AiCfg(BaseModel):
    # Off by default: operational data must not leave the network without an explicit decision.
    enabled: bool = False
    provider: str = "groq"
    model: str = "llama-3.3-70b-versatile"


class Tenant(BaseModel):
    key: str = "default"
    identity: Identity
    branding: Branding = Branding()
    currency: Currency = Currency()
    locale: str = "en"
    timezone: str = "UTC"
    fiscal_year: FiscalYearCfg = FiscalYearCfg()
    hierarchy: Hierarchy = Hierarchy()
    targets: Dict[str, float] = {}
    thresholds: Dict[str, float] = {}
    strategic_plan: StrategicPlan = StrategicPlan()
    modules: Dict[str, bool] = {}
    ai: AiCfg = AiCfg()
    folder: Optional[Path] = None

    @field_validator("targets", "thresholds")
    @classmethod
    def _floats(cls, v: Dict[str, Any]) -> Dict[str, float]:
        return {k: float(x) for k, x in v.items()}

    # ── convenience ────────────────────────────────────────────────────────
    @property
    def zone_colors(self) -> Dict[str, str]:
        return {z.name: z.color for z in self.hierarchy.zones}

    @property
    def zone_names(self) -> List[str]:
        return [z.name for z in self.hierarchy.zones]

    def target(self, key: str, default: Optional[float] = None) -> Optional[float]:
        return self.targets.get(key, default)

    def module_enabled(self, key: str) -> bool:
        return self.modules.get(key, True)

    @property
    def logo_path(self) -> Optional[Path]:
        if self.folder and self.branding.logo:
            p = self.folder / self.branding.logo
            return p if p.exists() else None
        return None

    def public_dict(self) -> Dict[str, Any]:
        """What the login screen may see before authentication."""
        return {
            "product": "MadziHub",
            "name": self.identity.name,
            "short_name": self.identity.short_name,
            "product_title": self.identity.product_title,
            "tagline": self.identity.tagline,
            "branding": self.branding.model_dump(),
            "logo_url": "/api/config/logo",
        }

    def client_dict(self) -> Dict[str, Any]:
        """Configuration the authenticated UI needs to render labels, money and targets."""
        from app.utils import FY_MONTH_NOS, MONTHS_LBL, MONTHS_ORDER
        return {
            **self.public_dict(),
            "identity": self.identity.model_dump(),
            "currency": self.currency.model_dump(),
            "locale": self.locale,
            "timezone": self.timezone,
            "fiscal_year": {
                "start_month": self.fiscal_year.start_month,
                "months": MONTHS_ORDER,
                "months_short": MONTHS_LBL,
                "month_numbers": FY_MONTH_NOS,
            },
            "hierarchy": {
                "levels": [lvl.model_dump() for lvl in self.hierarchy.levels],
                "zones": [z.model_dump() for z in self.hierarchy.zones],
            },
            "targets": self.targets,
            "thresholds": self.thresholds,
            "modules": self.modules,
            "ai_enabled": self.ai.enabled,
        }


def _resolve(name_or_path: str) -> Path:
    p = Path(name_or_path)
    if p.suffix in {".yaml", ".yml"}:
        return p if p.is_absolute() else BASE_DIR / p
    return TENANTS_DIR / name_or_path / "tenant.yaml"


def load_tenant(name_or_path: str) -> Tenant:
    path = _resolve(name_or_path)
    if not path.exists():
        raise RuntimeError(f"Tenant configuration not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data.setdefault("key", path.parent.name)
    data["folder"] = path.parent
    return Tenant.model_validate(data)


@lru_cache(maxsize=1)
def get_tenant() -> Tenant:
    return load_tenant(settings.tenant)


tenant = get_tenant()
