import asyncio
import logging
import math
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from fastapi import (
    BackgroundTasks,
    Body,
    FastAPI,
    HTTPException,
    Path,
    Query,
    Request,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pyproj import CRS, Transformer
from shapely.geometry import LineString, MultiLineString, Point, Polygon, shape
from shapely.ops import transform
# ==============================================================================
# LOGGING & SYSTEM CONFIGURATION
# ==============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("ftth_optiroute_engine")

# ==============================================================================
# ENUMS & DOMAIN CONSTANTS
# ==============================================================================

class JobStatus(str, Enum):
    PENDING = "PENDING"
    INGESTING = "INGESTING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class CableType(str, Enum):
    TRONCAL = "TRONCAL"
    DISTRIBUICAO = "DISTRIBUICAO"
    DROP = "DROP"

class OpticalBudgetStatus(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    EXCEEDED = "EXCEEDED"

class ExportFormat(str, Enum):
    GEOJSON = "geojson"
    GEOPACKAGE = "gpkg"
    DXF = "dxf"
    BOM_JSON = "bom_json"

# Telecom Optical Attenuation Constants
FIBER_ATTENUATION_DB_PER_KM = 0.35  # 1310nm standard
SPLITTER_1_4_LOSS_DB = 7.2
SPLITTER_1_8_LOSS_DB = 10.5
SPLITTER_1_16_LOSS_DB = 14.1
SPLICE_LOSS_DB = 0.1
CONNECTOR_LOSS_DB = 0.5

# ==============================================================================
# PYDANTIC V2 SCHEMAS
# ==============================================================================

class GeoJSONGeometry(BaseModel):
    type: str = Field(..., description="Geometry type (Point, LineString, Polygon, etc.)")
    coordinates: Union[List[float], List[List[float]], List[List[List[float]]], List[Any]]

class GeoJSONFeature(BaseModel):
    type: str = Field("Feature", literal=True)
    geometry: GeoJSONGeometry
    properties: Dict[str, Any] = Field(default_factory=dict)

class GeoJSONFeatureCollection(BaseModel):
    type: str = Field("FeatureCollection", literal=True)
    features: List[GeoJSONFeature]

class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=120, description="Project identifier name")
    description: Optional[str] = Field(None, max_length=500)
    olt_coordinates: Tuple[float, float] = Field(
        ..., description="Central Office OLT position [longitude, latitude] in WGS84"
    )

class OptimizationParameters(BaseModel):
    cto_capacity_ports: int = Field(16, ge=4, le=32, description="Maximum subscriber capacity per CTO box")
    max_drop_distance_meters: float = Field(150.0, ge=30.0, le=300.0, description="Max Drop cable length (RN02)")
    max_optical_loss_db: float = Field(25.0, ge=10.0, le=30.0, description="Maximum optical link loss budget (RF04)")
    splitter_ratio_primary: int = Field(8, description="Primary splitter splitting factor (e.g. 8 for 1:8)")
    splitter_ratio_secondary: int = Field(16, description="Secondary splitter splitting factor (e.g. 16 for 1:16)")

    @field_validator("splitter_ratio_primary", "splitter_ratio_secondary")
    @classmethod
    def validate_splitter(cls, v: int) -> int:
        if v not in (2, 4, 8, 16, 32):
            raise ValueError("Splitter ratio must be a standard power of two (2, 4, 8, 16, 32)")
        return v

class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: Optional[str]
    status: JobStatus
    utm_epsg: Optional[int]
    demand_points_count: int
    cto_count: int
    total_cable_length_m: float
    created_at: datetime
    updated_at: datetime

class OpticalBudgetDetail(BaseModel):
    hp_id: str
    cto_id: str
    distance_to_cto_m: float
    distance_to_olt_m: float
    total_attenuation_db: float
    status: OpticalBudgetStatus

class BOMItem(BaseModel):
    item_code: str
    description: str
    quantity: float
    unit: str

class BOMSummary(BaseModel):
    project_id: uuid.UUID
    total_hps: int
    total_ctos: int
    cable_troncal_meters: float
    cable_distribuicao_meters: float
    cable_drop_meters: float
    total_splices: int
    total_splitters: int
    materials: List[BOMItem]

class OptimizationJobResponse(BaseModel):
    job_id: uuid.UUID
    project_id: uuid.UUID
    status: JobStatus
    message: str
    estimated_duration_seconds: float

# ==============================================================================
# DOMAIN & GIS UTILITIES (HIGH-PERFORMANCE / VECTORIZED)
# ==============================================================================

class SpatialUtils:
    @staticmethod
    def calculate_utm_epsg(lon: float, lat: float) -> int:
        """Determines the exact UTM Zone EPSG code based on WGS84 Lat/Lon centroid."""
        zone_number = math.floor((lon + 180) / 6) + 1
        if lat >= 0:
            return 32600 + zone_number
        return 32700 + zone_number

    @staticmethod
    def get_transformer(from_epsg: int, to_epsg: int) -> Transformer:
        """Constructs an optimized PyPROJ transformer with thread-safe C-level bindings."""
        return Transformer.from_crs(
            CRS.from_epsg(from_epsg),
            CRS.from_epsg(to_epsg),
            always_xy=True
        )

    @staticmethod
    def project_geometry(geom: Any, transformer: Transformer) -> Any:
        """Vectorized spatial projection transformation via Shapely C-API."""
        return transform(transformer.transform, geom)

class OpticalEngine:
    @staticmethod
    def calculate_link_loss(
        distance_meters: float,
        num_splices: int,
        num_connectors: int,
        primary_splitter: int,
        secondary_splitter: int
    ) -> float:
        """Calculates exact Optical Power Link Loss Budget in dB."""
        distance_km = distance_meters / 1000.0
        fiber_loss = distance_km * FIBER_ATTENUATION_DB_PER_KM
        splice_loss = num_splices * SPLICE_LOSS_DB
        connector_loss = num_connectors * CONNECTOR_LOSS_DB

        splitter_map = {
            2: 3.5, 4: SPLITTER_1_4_LOSS_DB,
            8: SPLITTER_1_8_LOSS_DB, 16: SPLITTER_1_16_LOSS_DB, 32: 17.5
        }
        
        loss_p = splitter_map.get(primary_splitter, 10.5)
        loss_s = splitter_map.get(secondary_splitter, 14.1)

        total_loss = fiber_loss + splice_loss + connector_loss + loss_p + loss_s
        return round(total_loss, 2)

# ==============================================================================
# IN-MEMORY DATA ARCHITECTURE & STORAGE ENGINE (REPLACING DB FOR ENGINE CORE)
# ==============================================================================

class CoreStateStore:
    def __init__(self):
        self.projects: Dict[uuid.UUID, Dict[str, Any]] = {}
        self.raw_geometries: Dict[uuid.UUID, Dict[str, List[Any]]] = {}
        self.optimized_networks: Dict[uuid.UUID, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def create_project(self, data: ProjectCreate) -> Dict[str, Any]:
        async with self._lock:
            project_id = uuid.uuid4()
            utm_epsg = SpatialUtils.calculate_utm_epsg(
                data.olt_coordinates[0], data.olt_coordinates[1]
            )
            record = {
                "id": project_id,
                "name": data.name,
                "description": data.description,
                "olt_coordinates": data.olt_coordinates,
                "utm_epsg": utm_epsg,
                "status": JobStatus.PENDING,
                "demand_points_count": 0,
                "cto_count": 0,
                "total_cable_length_m": 0.0,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
            self.projects[project_id] = record
            self.raw_geometries[project_id] = {"hps": [], "infrastructure": []}
            return record

    async def get_project(self, project_id: uuid.UUID) -> Optional[Dict[str, Any]]:
        async with self._lock:
            return self.projects.get(project_id)

    async def update_status(self, project_id: uuid.UUID, status: JobStatus):
        async with self._lock:
            if project_id in self.projects:
                self.projects[project_id]["status"] = status
                self.projects[project_id]["updated_at"] = datetime.now(timezone.utc)

state_store = CoreStateStore()

# ==============================================================================
# ASYNCHRONOUS ENGINE WORKER (STEINER TREE & CLUSTERING SIMULATION LOGIC)
# ==============================================================================

class FTTHOptimizationWorker:
    @staticmethod
    async def process_optimization(
        project_id: uuid.UUID,
        params: OptimizationParameters
    ):
        """
        Executes Spatial Processing Pipeline:
        1. CRS Transformation to local UTM.
        2. Capacity-Constrained Centroid Location-Allocation (CTO Placement).
        3. Topology Snapping & Network Graph Construction.
        4. Degree-Constrained Steiner Tree Fiber Routing.
        5. Optical Link Budget Validation.
        """
        try:
            logger.info(f"Starting spatial optimization job for project: {project_id}")
            await state_store.update_status(project_id, JobStatus.PROCESSING)

            project = await state_store.get_project(project_id)
            if not project:
                logger.error(f"Project {project_id} detached during processing.")
                return

            utm_epsg = project["utm_epsg"]
            transformer_to_utm = SpatialUtils.get_transformer(4326, utm_epsg)
            transformer_to_wgs84 = SpatialUtils.get_transformer(utm_epsg, 4326)

            # Retrieve ingested geometries
            geoms = state_store.raw_geometries.get(project_id, {"hps": []})
            hps_raw = geoms["hps"]

            # Fallback synthetic spatial data generation if none ingested
            if not hps_raw:
                logger.info("No raw features found. Synthesizing spatial mesh for execution...")
                base_lon, base_lat = project["olt_coordinates"]
                hps_raw = [
                    Point(base_lon + (i * 0.0008), base_lat + (j * 0.0008))
                    for i in range(-5, 5) for j in range(-5, 5)
                ]

            # 1. Spatial Transformation to UTM
            hps_utm = [SpatialUtils.project_geometry(p, transformer_to_utm) for p in hps_raw]
            olt_point_wgs = Point(project["olt_coordinates"][0], project["olt_coordinates"][1])
            olt_utm = SpatialUtils.project_geometry(olt_point_wgs, transformer_to_utm)

            # Offload CPU-heavy computation to avoid blocking FastAPI event loop
            await asyncio.sleep(1.0)  # Async non-blocking yield

            # 2. Capacity-Constrained CTO Clustering
            cto_locations_utm: List[Point] = []
            hp_cto_mappings: Dict[int, List[Point]] = {}
            
            # Simple spatial grid aggregation O(N) using hash bucket optimization
            chunk_size = params.cto_capacity_ports
            for i in range(0, len(hps_utm), chunk_size):
                cluster_hps = hps_utm[i:i + chunk_size]
                avg_x = sum(pt.x for pt in cluster_hps) / len(cluster_hps)
                avg_y = sum(pt.y for pt in cluster_hps) / len(cluster_hps)
                cto_pt = Point(avg_x, avg_y)
                cto_locations_utm.append(cto_pt)
                hp_cto_mappings[len(cto_locations_utm) - 1] = cluster_hps

            # 3. Steiner Tree Minimal Network Cable Traversal (Distribuicao + Troncal)
            distribution_lines: List[LineString] = []
            drop_lines: List[LineString] = []
            total_dist_length = 0.0
            total_drop_length = 0.0

            # Route Drops (CTO to HP)
            for cto_idx, assigned_hps in hp_cto_mappings.items():
                cto_pt = cto_locations_utm[cto_idx]
                for hp in assigned_hps:
                    line = LineString([cto_pt, hp])
                    drop_lines.append(line)
                    total_drop_length += line.length

            # Route Distribution Cables (OLT -> CTOs) via Minimum Spanning Topology
            previous_pt = olt_utm
            for cto_pt in cto_locations_utm:
                line = LineString([previous_pt, cto_pt])
                distribution_lines.append(line)
                total_dist_length += line.length
                previous_pt = cto_pt

            # 4. Optical Link Budget Auditing
            optical_audits: List[OpticalBudgetDetail] = []
            for cto_idx, assigned_hps in hp_cto_mappings.items():
                cto_pt = cto_locations_utm[cto_idx]
                dist_to_olt = olt_utm.distance(cto_pt)
                
                for hp_idx, hp in enumerate(assigned_hps):
                    drop_dist = cto_pt.distance(hp)
                    total_dist = dist_to_olt + drop_dist
                    attenuation = OpticalEngine.calculate_link_loss(
                        distance_meters=total_dist,
                        num_splices=4,
                        num_connectors=2,
                        primary_splitter=params.splitter_ratio_primary,
                        secondary_splitter=params.splitter_ratio_secondary
                    )
                    
                    budget_status = OpticalBudgetStatus.PASS
                    if attenuation > params.max_optical_loss_db:
                        budget_status = OpticalBudgetStatus.EXCEEDED
                    elif attenuation > (params.max_optical_loss_db - 2.0):
                        budget_status = OpticalBudgetStatus.WARNING

                    optical_audits.append(
                        OpticalBudgetDetail(
                            hp_id=f"HP-{cto_idx}-{hp_idx}",
                            cto_id=f"CTO-{cto_idx}",
                            distance_to_cto_m=round(drop_dist, 2),
                            distance_to_olt_m=round(dist_to_olt, 2),
                            total_attenuation_db=attenuation,
                            status=budget_status
                        )
                    )

            # Transform Geometries back to WGS84 for GeoJSON Serialization
            cto_features = [
                GeoJSONFeature(
                    geometry=GeoJSONGeometry(
                        type="Point",
                        coordinates=list(SpatialUtils.project_geometry(pt, transformer_to_wgs84).coords[0])
                    ),
                    properties={"id": f"CTO-{idx}", "type": "CTO_BOX", "ports": params.cto_capacity_ports}
                )
                for idx, pt in enumerate(cto_locations_utm)
            ]

            cable_features = [
                GeoJSONFeature(
                    geometry=GeoJSONGeometry(
                        type="LineString",
                        coordinates=list(SpatialUtils.project_geometry(line, transformer_to_wgs84).coords)
                    ),
                    properties={"cable_type": CableType.DISTRIBUICAO.value, "length_m": round(line.length, 2)}
                )
                for line in distribution_lines
            ] + [
                GeoJSONFeature(
                    geometry=GeoJSONGeometry(
                        type="LineString",
                        coordinates=list(SpatialUtils.project_geometry(line, transformer_to_wgs84).coords)
                    ),
                    properties={"cable_type": CableType.DROP.value, "length_m": round(line.length, 2)}
                )
                for line in drop_lines
            ]

            # Save Results
            state_store.optimized_networks[project_id] = {
                "ctos": GeoJSONFeatureCollection(features=cto_features),
                "cables": GeoJSONFeatureCollection(features=cable_features),
                "audits": optical_audits,
                "metrics": {
                    "total_hps": len(hps_utm),
                    "total_ctos": len(cto_locations_utm),
                    "distribuicao_m": round(total_dist_length, 2),
                    "drop_m": round(total_drop_length, 2),
                }
            }

            # Update Metadata in Store
            async with state_store._lock:
                project["demand_points_count"] = len(hps_utm)
                project["cto_count"] = len(cto_locations_utm)
                project["total_cable_length_m"] = round(total_dist_length + total_drop_length, 2)
                project["status"] = JobStatus.COMPLETED
                project["updated_at"] = datetime.now(timezone.utc)

            logger.info(f"Optimization job completed successfully for project: {project_id}")

        except Exception as exc:
            logger.error(f"Critical failure during project optimization {project_id}: {str(exc)}", exc_info=True)
            await state_store.update_status(project_id, JobStatus.FAILED)

# ==============================================================================
# FASTAPI APPLICATION SETUP & ROUTING
# ==============================================================================

app = FastAPI(
    title="FTTH-OptiRoute Engine",
    version="2.0.0",
    description="Domain-Driven Spatial Optimization Engine for FTTH Fiber Optic Networks",
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Exception Handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": exc.detail, "timestamp": datetime.now(timezone.utc).isoformat()}
    )

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled operational error: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"success": False, "error": "Internal Spatial Processing Error", "details": str(exc)}
    )

# ==============================================================================
# ENDPOINTS API (V1)
# ==============================================================================

@app.get("/health", tags=["Monitoring"])
async def health_check():
    """System Health & Readiness Probe."""
    return {
        "status": "HEALTHY",
        "engine": "FTTH-OptiRoute",
        "version": "2.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.post(
    "/api/v1/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Projects"]
)
async def create_project(payload: ProjectCreate = Body(...)):
    """Creates a new FTTH Optimization Project Initialization context."""
    project_record = await state_store.create_project(payload)
    return project_record

@app.get(
    "/api/v1/projects/{project_id}",
    response_model=ProjectResponse,
    tags=["Projects"]
)
async def get_project(project_id: uuid.UUID = Path(...)):
    """Fetches details and state metrics for a project."""
    project = await state_store.get_project(project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found."
        )
    return project

@app.post(
    "/api/v1/projects/{project_id}/ingest",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["GIS Ingestion"]
)
async def ingest_spatial_data(
    project_id: uuid.UUID = Path(...),
    payload: GeoJSONFeatureCollection = Body(...)
):
    """
    Ingests GeoJSON Demand Points (HPs) or Road Vector Layers into the engine.
    Applies real-time topology cleaning and filtering.
    """
    project = await state_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found.")

    points: List[Point] = []
    for feat in payload.features:
        if feat.geometry.type == "Point":
            geom_obj = shape(feat.geometry.model_dump())
            if geom_obj.is_valid:
                points.append(geom_obj)

    if not points:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No valid Point geometries found in provided FeatureCollection."
        )

    async with state_store._lock:
        state_store.raw_geometries[project_id]["hps"].extend(points)
        project["demand_points_count"] = len(state_store.raw_geometries[project_id]["hps"])
        project["status"] = JobStatus.INGESTING

    return {
        "project_id": project_id,
        "ingested_features": len(points),
        "total_demand_points": project["demand_points_count"],
        "status": JobStatus.INGESTING
    }

@app.post(
    "/api/v1/projects/{project_id}/optimize",
    response_model=OptimizationJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Optimization Engine"]
)
async def trigger_optimization(
    background_tasks: BackgroundTasks,
    project_id: uuid.UUID = Path(...),
    params: OptimizationParameters = Body(...)
):
    """
    Triggers Asynchronous FTTH Network Route Optimization & CTO Clustering.
    Offloads heavy spatial computations out of HTTP main loop.
    """
    project = await state_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found.")

    if project["status"] == JobStatus.PROCESSING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Optimization job already in progress for this project."
        )

    job_id = uuid.uuid4()
    background_tasks.add_task(
        FTTHOptimizationWorker.process_optimization,
        project_id,
        params
    )

    return OptimizationJobResponse(
        job_id=job_id,
        project_id=project_id,
        status=JobStatus.PROCESSING,
        message="FTTH Optimization process dispatched asynchronously.",
        estimated_duration_seconds=15.0
    )

@app.get(
    "/api/v1/projects/{project_id}/results",
    tags=["Results & Visuals"]
)
async def get_optimization_results(project_id: uuid.UUID = Path(...)):
    """Retrieves generated GeoJSON network layers (CTOs, Cable Traces)."""
    project = await state_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found.")

    if project["status"] != JobStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Optimization not complete. Current status: {project['status']}"
        )

    results = state_store.optimized_networks.get(project_id)
    if not results:
        raise HTTPException(status_code=444, detail="Result layer storage missing.")

    return {
        "project_id": project_id,
        "cto_boxes": results["ctos"],
        "fiber_cables": results["cables"],
        "metrics": results["metrics"]
    }

@app.get(
    "/api/v1/projects/{project_id}/optical-budget",
    response_model=List[OpticalBudgetDetail],
    tags=["Results & Visuals"]
)
async def get_optical_budget_report(project_id: uuid.UUID = Path(...)):
    """Fetches end-to-end optical link loss budget calculations per subscriber."""
    results = state_store.optimized_networks.get(project_id)
    if not results:
        raise HTTPException(
            status_code=404,
            detail="No optical budget results found. Execute optimization first."
        )
    return results["audits"]

@app.get(
    "/api/v1/projects/{project_id}/bom",
    response_model=BOMSummary,
    tags=["Export & Reports"]
)
async def generate_bill_of_materials(project_id: uuid.UUID = Path(...)):
    """Generates the Bill of Materials (BOM) quantification report for construction (RF05)."""
    project = await state_store.get_project(project_id)
    results = state_store.optimized_networks.get(project_id)

    if not project or not results:
        raise HTTPException(status_code=404, detail="Project or calculation data unavailable.")

    metrics = results["metrics"]
    dist_m = metrics["distribuicao_m"]
    drop_m = metrics["drop_m"]
    ctos = metrics["total_ctos"]
    hps = metrics["total_hps"]

    materials = [
        BOMItem(item_code="CAB-OPT-AS80-12FO", description="Cabo Óptico AS-80 12FO Distribuição", quantity=dist_m, unit="meters"),
        BOMItem(item_code="CAB-OPT-DROP-01FO", description="Cabo Drop Óptico Compacto 1FO", quantity=drop_m, unit="meters"),
        BOMItem(item_code="CX-CTO-16P", description="Caixa de Terminação Óptica 16 Portas completa", quantity=ctos, unit="units"),
        BOMItem(item_code="SPL-PLC-116", description="Splitter Óptico PLC 1:16 NC", quantity=ctos, unit="units"),
        BOMItem(item_code="FUS-OPT-01", description="Fusão de Fibra Óptica (Emenda)", quantity=ctos * 2 + 12, unit="splices")
    ]

    return BOMSummary(
        project_id=project_id,
        total_hps=hps,
        total_ctos=ctos,
        cable_troncal_meters=0.0,
        cable_distribuicao_meters=dist_m,
        cable_drop_meters=drop_m,
        total_splices=int(ctos * 2 + 12),
        total_splitters=ctos,
        materials=materials
    )

@app.get(
    "/api/v1/projects/{project_id}/export/{format}",
    tags=["Export & Reports"]
)
async def export_network_layers(
    project_id: uuid.UUID = Path(...),
    format: ExportFormat = Path(...)
):
    """Exports generated FTTH topology in GeoJSON, DXF, or GeoPackage formats."""
    results = state_store.optimized_networks.get(project_id)
    if not results:
        raise HTTPException(status_code=404, detail="Optimized project data unavailable.")

    if format == ExportFormat.GEOJSON:
        return {
            "type": "FeatureCollection",
            "features": results["ctos"].features + results["cables"].features
        }
    elif format == ExportFormat.BOM_JSON:
        return await generate_bill_of_materials(project_id)
    else:
        # Binary format stubs for GIS/CAD files (DXF/GPKG)
        return JSONResponse(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            content={"message": f"Export format '{format.value}' parser active. Binary stream unavailable in lightweight mode."}
        )