"""Typed catalog — the estate, the platforms, the policy and the cost model.

Everything the engine reasons about is data on disk under ``config/``. Nothing
about a particular estate is compiled into the rules (ADR-0005), so pointing this
at a different estate is an edit to YAML, not to Python.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


class Platform(StrEnum):
    """Where a workload lands.

    ``STAY_ON_SYNAPSE`` is the answer nobody puts on a slide and the one that is
    sometimes correct: every candidate was eliminated by a constraint, so the
    honest move is to change a constraint rather than to pretend one away.
    """

    FABRIC = "FABRIC"
    DATABRICKS = "DATABRICKS"
    STAY_ON_SYNAPSE = "STAY_ON_SYNAPSE"


#: The platforms the economics stage prices and compares.
CANDIDATES = (Platform.FABRIC, Platform.DATABRICKS)

WorkloadKind = Literal["dedicated_sql", "serverless_view", "spark_notebook", "pipeline", "stream"]
TsqlSurface = Literal["none", "queries", "procedures", "transactions"]
Consumer = Literal["powerbi_direct_lake", "powerbi_import", "sql_client", "notebook", "app", "ml"]
LatencyClass = Literal["interactive", "batch", "subsecond"]

#: T-SQL surfaces that do not lift onto a platform without stored procedures or
#: multi-table transactions. ``queries`` does; the other two do not.
TSQL_SURFACES_NEEDING_SUPPORT: dict[str, str] = {
    "procedures": "tsql_procedures",
    "transactions": "tsql_transactions",
}


class Governance(BaseModel):
    residency: list[str]
    pii: bool = False
    classification: str = "internal"


class Workload(BaseModel):
    """One thing in the Synapse estate that has to go somewhere."""

    id: str
    name: str
    domain: str
    kind: WorkloadKind
    tsql_surface: TsqlSurface = "none"
    size_gb: float = 0.0
    compute_hours_per_month: float = 0.0
    gb_scanned_per_month: float = 0.0
    consumer: Consumer
    latency_class: LatencyClass = "batch"
    peak_concurrency: int = 1
    latency_slo_seconds: float = 60.0
    ml_lifecycle: bool = False

    # Streams only. Defaults are the append-only, ingestion-time shape; a workload
    # that needs more has to say so, because the stricter semantics are what make a
    # stream expensive and the default should not smuggle them in.
    events_per_second: float = 0.0
    retention_days: float = 0.0
    late_arrival_tolerance_minutes: float = 0.0
    exactly_once_required: bool = False

    governance: Governance

    @property
    def tb_scanned_per_month(self) -> float:
        return self.gb_scanned_per_month / 1024.0

    @property
    def needs_event_time_restatement(self) -> bool:
        return self.kind == "stream" and self.late_arrival_tolerance_minutes > 0

    @property
    def needs_subsecond(self) -> bool:
        return self.latency_class == "subsecond"


class PlatformCapability(BaseModel):
    tsql_transactions: bool = False
    tsql_procedures: bool = False
    powerbi_direct_lake: bool = False
    subsecond_telemetry: bool = False
    event_time_restatement: bool = False
    exactly_once_streaming: bool = False
    ml_lifecycle: bool = False


class PlatformSpec(BaseModel):
    name: str
    capacity_regions: list[str] = Field(default_factory=list)
    workspace_regions: list[str] = Field(default_factory=list)
    surfaces: dict[str, str]
    capability: PlatformCapability

    @property
    def regions(self) -> list[str]:
        """Fabric calls it a capacity, Databricks calls it a workspace. Same question."""
        return self.capacity_regions or self.workspace_regions


class Platforms(BaseModel):
    target_region: str
    fabric: PlatformSpec
    databricks: PlatformSpec

    def spec(self, platform: Platform) -> PlatformSpec:
        return self.fabric if platform is Platform.FABRIC else self.databricks


class ResidencyPolicy(BaseModel):
    enforce: bool = True
    restricted_requires_cleared_platform: bool = True
    cleared_platform_for_restricted: str = "fabric"


class TsqlPolicy(BaseModel):
    eliminate_when_surface_unsupported: bool = True


class StreamingPolicy(BaseModel):
    eliminate_when_semantics_unsupported: bool = True
    subsecond_requires_capable_platform: bool = True


class MlPolicy(BaseModel):
    eliminate_when_lifecycle_unsupported: bool = True


class SemanticsPolicy(BaseModel):
    prefer_direct_lake_consumers: bool = True
    max_premium_ratio: float = 1.30


class CapacityPolicy(BaseModel):
    headroom: float = 0.75
    interactive_headroom: float = 0.65
    consolidation_floor: float = 0.55


class Policy(BaseModel):
    residency: ResidencyPolicy = Field(default_factory=ResidencyPolicy)
    tsql: TsqlPolicy = Field(default_factory=TsqlPolicy)
    streaming: StreamingPolicy = Field(default_factory=StreamingPolicy)
    ml: MlPolicy = Field(default_factory=MlPolicy)
    semantics: SemanticsPolicy = Field(default_factory=SemanticsPolicy)
    capacity: CapacityPolicy = Field(default_factory=CapacityPolicy)


class FabricCosts(BaseModel):
    skus: list[int]
    eur_per_cu_hour: float
    reservation_discount: float
    use_reservation: bool
    cu_hours_per_compute_hour: dict[str, float]
    cu_hours_per_tb_scanned: dict[str, float]
    cu_hours_per_billion_events: dict[str, float] = Field(default_factory=dict)
    storage_eur_per_gb_month: float
    eventhouse_hot_cache_eur_per_gb_month: float

    @property
    def effective_eur_per_cu_hour(self) -> float:
        if self.use_reservation:
            return self.eur_per_cu_hour * (1.0 - self.reservation_discount)
        return self.eur_per_cu_hour


class DatabricksCosts(BaseModel):
    eur_per_dbu: dict[str, float]
    dbu_hours_per_compute_hour: dict[str, float]
    dbu_hours_per_tb_scanned: dict[str, float]
    dbu_hours_per_billion_events: dict[str, float] = Field(default_factory=dict)
    storage_eur_per_gb_month: float


class MigrationCosts(BaseModel):
    amortise_months: float
    eur_per_workload: dict[str, float]
    tsql_rewrite_multiplier: float


class CostModel(BaseModel):
    currency: str
    hours_per_month: float
    fabric: FabricCosts
    databricks: DatabricksCosts
    platform_overhead_eur_per_month: dict[str, float]
    migration: MigrationCosts


class Catalog(BaseModel):
    """Everything loaded, in one object, so a caller passes one argument around."""

    platforms: Platforms
    policy: Policy
    costs: CostModel
    workloads: list[Workload]

    def workload(self, workload_id: str) -> Workload:
        for w in self.workloads:
            if w.id == workload_id:
                return w
        raise KeyError(f"unknown workload: {workload_id}")


def _read(path: Path) -> object:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_catalog(config_dir: Path | None = None) -> Catalog:
    """Load and validate the whole configuration set.

    Validation is deliberately strict. A typo in a workload kind or a missing
    consumer profile should fail here, loudly, rather than silently become a
    default that changes a platform decision.
    """
    cfg = Path(config_dir) if config_dir else CONFIG_DIR
    platforms = Platforms.model_validate(_read(cfg / "platforms.yaml"))
    policy = Policy.model_validate(_read(cfg / "policy.yaml"))
    costs = CostModel.model_validate(_read(cfg / "cost_model.yaml"))
    workloads = [Workload.model_validate(w) for w in _read(cfg / "estate.yaml")]

    seen: set[str] = set()
    for w in workloads:
        if w.id in seen:
            raise ValueError(f"duplicate workload id: {w.id}")
        seen.add(w.id)
        for p in CANDIDATES:
            spec = platforms.spec(p)
            if w.kind not in spec.surfaces:
                raise ValueError(f"{w.id}: {spec.name} has no surface for kind {w.kind!r}")

    return Catalog(platforms=platforms, policy=policy, costs=costs, workloads=workloads)
