"""Typed catalog — the estate, the platforms, the policy and the cost model.

Everything the engine reasons about is data on disk under ``config/``. Nothing
about a particular estate is compiled into the rules (ADR-0005), so pointing this
at a different estate is an edit to YAML, not to Python.

That extends to the platform list itself (ADR-0007). The engine knows about two
*pricing shapes* — a pre-paid capacity and a meter — and not about three vendors.
Adding a fourth target is an entry in ``platforms.yaml`` and ``cost_model.yaml``
plus a member of :class:`Platform`; it is not a new branch in the rules.
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
    SNOWFLAKE = "SNOWFLAKE"
    STAY_ON_SYNAPSE = "STAY_ON_SYNAPSE"

    @property
    def key(self) -> str:
        """The lowercase key this platform is configured under."""
        return self.value.lower()


#: The platforms the economics stage prices and compares. Order is the tie-break
#: order and therefore has to be stable — determinism is a working rule, and a set
#: here would make two runs differ (AGENTS.md rule 8).
CANDIDATES = (Platform.FABRIC, Platform.DATABRICKS, Platform.SNOWFLAKE)

Pricing = Literal["capacity", "metered"]

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
    pricing: Pricing
    capacity_regions: list[str] = Field(default_factory=list)
    workspace_regions: list[str] = Field(default_factory=list)
    surfaces: dict[str, str]
    capability: PlatformCapability

    @property
    def regions(self) -> list[str]:
        """Fabric calls it a capacity, the others a workspace or an account.

        Same question: where is this platform allowed to put the data down.
        """
        return self.capacity_regions or self.workspace_regions

    @property
    def is_metered(self) -> bool:
        return self.pricing == "metered"


class Platforms(BaseModel):
    target_region: str
    platforms: dict[str, PlatformSpec]

    def spec(self, platform: Platform) -> PlatformSpec:
        try:
            return self.platforms[platform.key]
        except KeyError:
            raise KeyError(f"no configuration for platform {platform.value}") from None

    @property
    def fabric(self) -> PlatformSpec:
        """The capacity platform, by the name everything else calls it."""
        return self.spec(Platform.FABRIC)


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


class PlatformsPolicy(BaseModel):
    review_platform_overhead: bool = True
    pinned_platforms_are_not_reviewable: bool = True


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
    platforms: PlatformsPolicy = Field(default_factory=PlatformsPolicy)
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


class MeteredCosts(BaseModel):
    """One metered platform's meter.

    The same five fields describe a DBU and a Snowflake credit, because the two
    platforms bill in the same *shape* and differ only in slope. Holding them in one
    model is what keeps the engine from growing a per-vendor branch, and what makes
    "which meter is cheaper for this surface" a question the config answers rather
    than the code.
    """

    unit: str
    eur_per_unit: dict[str, float]
    units_per_compute_hour: dict[str, float]
    units_per_tb_scanned: dict[str, float]
    units_per_billion_events: dict[str, float] = Field(default_factory=dict)
    storage_eur_per_gb_month: float


class MigrationCosts(BaseModel):
    amortise_months: float
    eur_per_workload: dict[str, float]
    tsql_rewrite_multiplier: float


class CostModel(BaseModel):
    currency: str
    hours_per_month: float
    fabric: FabricCosts
    metered: dict[str, MeteredCosts]
    platform_overhead_eur_per_month: dict[str, float]
    migration: MigrationCosts

    def meter(self, platform: Platform) -> MeteredCosts:
        try:
            return self.metered[platform.key]
        except KeyError:
            raise KeyError(f"{platform.value} has no meter in the cost model") from None

    def overhead(self, platform: Platform) -> float:
        return self.platform_overhead_eur_per_month.get(platform.key, 0.0)


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

    @property
    def metered_platforms(self) -> tuple[Platform, ...]:
        """Candidates that bill by consumption, in the stable candidate order."""
        return tuple(p for p in CANDIDATES if self.platforms.spec(p).is_metered)

    @property
    def capacity_platform(self) -> Platform:
        """The one candidate priced as a pre-paid pool.

        Singular on purpose. Two capacity platforms in one estate is a genuinely
        different allocation problem — two ladders interacting, where filling one
        does nothing to empty the other — and pretending the code below solves it
        would be the dishonest move. It raises instead.
        """
        capacity = [p for p in CANDIDATES if not self.platforms.spec(p).is_metered]
        if len(capacity) != 1:
            raise ValueError(
                f"expected exactly one capacity-priced platform, found {len(capacity)}: "
                f"{[p.value for p in capacity]}"
            )
        return capacity[0]


def _read(path: Path) -> object:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_catalog(config_dir: Path | None = None) -> Catalog:
    """Load and validate the whole configuration set.

    Validation is deliberately strict. A typo in a workload kind, a missing consumer
    profile, or a candidate platform with no meter behind it should fail here,
    loudly, rather than silently become a default that changes a platform decision.
    """
    cfg = Path(config_dir) if config_dir else CONFIG_DIR
    platforms = Platforms.model_validate(_read(cfg / "platforms.yaml"))
    policy = Policy.model_validate(_read(cfg / "policy.yaml"))
    costs = CostModel.model_validate(_read(cfg / "cost_model.yaml"))
    workloads = [Workload.model_validate(w) for w in _read(cfg / "estate.yaml")]

    cat = Catalog(platforms=platforms, policy=policy, costs=costs, workloads=workloads)

    # Every candidate must be configured, priced in the shape it claims, and able to
    # host every kind in the estate. A metered candidate with no meter behind it
    # would silently cost nothing and win everything, which is the failure this
    # catches before it reaches a report.
    _ = cat.capacity_platform  # raises unless exactly one platform is a capacity
    for p in CANDIDATES:
        spec = platforms.spec(p)
        if spec.is_metered:
            costs.meter(p)
        if p.key not in costs.platform_overhead_eur_per_month:
            raise ValueError(f"{spec.name} has no platform overhead in the cost model")

    seen: set[str] = set()
    for w in workloads:
        if w.id in seen:
            raise ValueError(f"duplicate workload id: {w.id}")
        seen.add(w.id)
        for p in CANDIDATES:
            spec = platforms.spec(p)
            if w.kind not in spec.surfaces:
                raise ValueError(f"{w.id}: {spec.name} has no surface for kind {w.kind!r}")

    return cat
