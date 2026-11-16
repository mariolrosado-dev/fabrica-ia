import asyncio
import time
import uuid
import pytest
from fastapi.testclient import TestClient

from main_gerado import (
    ExportFormat,
    JobStatus,
    OpticalBudgetStatus,
    app,
    state_store,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_state_store():
    """Fixture para limpar o armazenamento em memória antes de cada teste."""
    state_store.projects.clear()
    state_store.raw_geometries.clear()
    state_store.optimized_networks.clear()
    yield


# ==============================================================================
# 1. TESTES DO ENDPOINT DE HEALTH CHECK
# ==============================================================================

def test_health_check_returns_200_and_correct_schema():
    """Valida a disponibilidade da API e o formato da resposta do Health Check."""
    response = client.get("/health")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "HEALTHY"
    assert data["engine"] == "FTTH-OptiRoute"
    assert data["version"] == "2.0.0"
    assert "timestamp" in data


# ==============================================================================
# 2. TESTES DE CRIAÇÃO DE PROJETO E VALIDAÇÃO DE CONTRATOS (PYDANTIC V2)
# ==============================================================================

def test_create_project_success():
    """Valida a criação de um projeto com payload totalmente válido."""
    payload = {
        "name": "Projeto FTTH Centro",
        "description": "Expansão de fibra óptica para a zona central",
        "olt_coordinates": [-46.633308, -23.550520]
    }
    
    response = client.post("/api/v1/projects", json=payload)
    
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert data["name"] == payload["name"]
    assert data["description"] == payload["description"]
    assert data["status"] == JobStatus.PENDING.value
    assert data["demand_points_count"] == 0
    assert data["cto_count"] == 0
    assert data["total_cable_length_m"] == 0.0
    assert data["utm_epsg"] == 32723  # UTM Zone 23S para São Paulo WGS84


@pytest.mark.parametrize(
    "invalid_payload, expected_detail_loc",
    [
        (
            {"description": "Sem nome", "olt_coordinates": [-46.63, -23.55]},
            "name"
        ),
        (
            {"name": "AB", "olt_coordinates": [-46.63, -23.55]},
            "name"
        ),
        (
            {"name": "A" * 121, "olt_coordinates": [-46.63, -23.55]},
            "name"
        ),
        (
            {"name": "Projeto Teste", "olt_coordinates": [-46.63]},
            "olt_coordinates"
        ),
        (
            {"name": "Projeto Teste", "olt_coordinates": "coordenadas_invalidas"},
            "olt_coordinates"
        ),
    ]
)
def test_create_project_validation_errors(invalid_payload, expected_detail_loc):
    """Garante que payloads inválidos falhem na validação do Pydantic retornando 422."""
    response = client.post("/api/v1/projects", json=invalid_payload)
    assert response.status_code == 422
    errors = response.json().get("detail", [])
    assert any(expected_detail_loc in err.get("loc", []) for err in errors)


def test_get_project_not_found():
    """Valida a resposta 404 ao buscar um UUID não existente."""
    random_uuid = str(uuid.uuid4())
    response = client.get(f"/api/v1/projects/{random_uuid}")
    assert response.status_code == 404
    assert "not found" in response.json()["error"]


# ==============================================================================
# 3. TESTES DE INGESTÃO DE DADOS ESPACIAIS (GIS)
# ==============================================================================

def test_ingest_spatial_data_success():
    """Valida a ingestão de pontos de demanda (HPs) via GeoJSON."""
    # 1. Cria projeto
    proj_resp = client.post("/api/v1/projects", json={
        "name": "Projeto Ingestão GIS",
        "olt_coordinates": [-46.633308, -23.550520]
    })
    project_id = proj_resp.json()["id"]

    # 2. Ingere FeatureCollection GeoJSON
    geojson_payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [-46.633000, -23.550000]
                },
                "properties": {"client_id": "HP-001"}
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [-46.634000, -23.551000]
                },
                "properties": {"client_id": "HP-002"}
            }
        ]
    }

    response = client.post(f"/api/v1/projects/{project_id}/ingest", json=geojson_payload)
    
    assert response.status_code == 202
    data = response.json()
    assert data["ingested_features"] == 2
    assert data["total_demand_points"] == 2
    assert data["status"] == JobStatus.INGESTING.value


def test_ingest_spatial_data_invalid_geometry():
    """Garante erro 422 ao enviar GeoJSON sem geometrias do tipo Point válidas."""
    proj_resp = client.post("/api/v1/projects", json={
        "name": "Projeto Sem Pontos",
        "olt_coordinates": [-46.633308, -23.550520]
    })
    project_id = proj_resp.json()["id"]

    invalid_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-46.633, -23.550], [-46.634, -23.551]]
                },
                "properties": {}
            }
        ]
    }

    response = client.post(f"/api/v1/projects/{project_id}/ingest", json=invalid_geojson)
    assert response.status_code == 422
    assert "No valid Point geometries found" in response.json()["error"]


# ==============================================================================
# 4. TESTES DO FLUXO ASSÍNCRONO DE OTIMIZAÇÃO E REGRAS DE NEGÓCIO
# ==============================================================================

@pytest.mark.parametrize(
    "invalid_param, value",
    [
        ("cto_capacity_ports", 3),      # ge=4
        ("cto_capacity_ports", 64),     # le=32
        ("max_drop_distance_meters", 10.0), # ge=30.0
        ("max_drop_distance_meters", 500.0), # le=300.0
        ("max_optical_loss_db", 5.0),   # ge=10.0
        ("max_optical_loss_db", 40.0),  # le=30.0
        ("splitter_ratio_primary", 5),  # Não é potência de 2 permitida
        ("splitter_ratio_secondary", 12),# Não é potência de 2 permitida
    ]
)
def test_optimization_parameters_validation(invalid_param, value):
    """Valida restricões dos parâmetros de otimização no Pydantic."""
    proj_resp = client.post("/api/v1/projects", json={
        "name": "Projeto Params Invalido",
        "olt_coordinates": [-46.633308, -23.550520]
    })
    project_id = proj_resp.json()["id"]

    params = {
        "cto_capacity_ports": 16,
        "max_drop_distance_meters": 150.0,
        "max_optical_loss_db": 25.0,
        "splitter_ratio_primary": 8,
        "splitter_ratio_secondary": 16
    }
    params[invalid_param] = value

    response = client.post(f"/api/v1/projects/{project_id}/optimize", json=params)
    assert response.status_code == 422


def test_async_optimization_flow_execution_and_results():
    """
    Testa o ciclo de vida completo do processo assíncrono:
    Disparo da otimização -> Execução da BackgroundTask -> Validação dos Resultados/BOM/Budget.
    """
    # 1. Cria Projeto
    proj_resp = client.post("/api/v1/projects", json={
        "name": "Projeto Otimizacao Completa",
        "olt_coordinates": [-46.633308, -23.550520]
    })
    project_id = proj_resp.json()["id"]

    # 2. Ingere Pontos de Demanda (HPs)
    geojson_data = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-46.6331, -23.5501]},
                "properties": {"id": 1}
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-46.6332, -23.5502]},
                "properties": {"id": 2}
            }
        ]
    }
    client.post(f"/api/v1/projects/{project_id}/ingest", json=geojson_data)

    # 3. Dispara Otimização
    opt_params = {
        "cto_capacity_ports": 16,
        "max_drop_distance_meters": 150.0,
        "max_optical_loss_db": 25.0,
        "splitter_ratio_primary": 8,
        "splitter_ratio_secondary": 16
    }

    opt_resp = client.post(f"/api/v1/projects/{project_id}/optimize", json=opt_params)
    assert opt_resp.status_code == 202
    opt_data = opt_resp.json()
    assert opt_data["status"] == JobStatus.PROCESSING.value
    assert "job_id" in opt_data

    # 4. Aguarda a BackgroundTask concluir no event loop
    max_retries = 20
    completed = False
    for _ in range(max_retries):
        time.sleep(0.15)
        status_resp = client.get(f"/api/v1/projects/{project_id}")
        if status_resp.json()["status"] == JobStatus.COMPLETED.value:
            completed = True
            break
            
    assert completed is True, "A task assíncrona de otimização não foi concluída no tempo esperado."

    # 5. Valida Estruturas de Dados do Resultado
    res_resp = client.get(f"/api/v1/projects/{project_id}/results")
    assert res_resp.status_code == 200
    res_data = res_resp.json()
    
    assert "cto_boxes" in res_data
    assert "fiber_cables" in res_data
    assert "metrics" in res_data
    assert res_data["metrics"]["total_hps"] > 0
    assert res_data["metrics"]["total_ctos"] > 0
    assert res_data["metrics"]["distribuicao_m"] >= 0.0

    # 6. Valida Relatório de Orçamento Óptico (Optical Budget)
    budget_resp = client.get(f"/api/v1/projects/{project_id}/optical-budget")
    assert budget_resp.status_code == 200
    budget_data = budget_resp.json()
    assert len(budget_data) > 0
    assert "total_attenuation_db" in budget_data[0]
    assert budget_data[0]["status"] in [s.value for s in OpticalBudgetStatus]

    # 7. Valida Geração do Bill of Materials (BOM)
    bom_resp = client.get(f"/api/v1/projects/{project_id}/bom")
    assert bom_resp.status_code == 200
    bom_data = bom_resp.json()
    assert bom_data["project_id"] == project_id
    assert len(bom_data["materials"]) > 0
    assert any(m["item_code"] == "CX-CTO-16P" for m in bom_data["materials"])

    # 8. Valida Exportação de Camadas
    export_geojson = client.get(f"/api/v1/projects/{project_id}/export/geojson")
    assert export_geojson.status_code == 200
    assert export_geojson.json()["type"] == "FeatureCollection"

    export_dxf = client.get(f"/api/v1/projects/{project_id}/export/dxf")
    assert export_dxf.status_code == 501


def test_optimization_results_before_completion_fails():
    """Garante erro 400 ao buscar resultados de um projeto não concluído."""
    proj_resp = client.post("/api/v1/projects", json={
        "name": "Projeto Pendente",
        "olt_coordinates": [-46.633308, -23.550520]
    })
    project_id = proj_resp.json()["id"]

    response = client.get(f"/api/v1/projects/{project_id}/results")
    assert response.status_code == 400
    assert "Optimization not complete" in response.json()["error"]