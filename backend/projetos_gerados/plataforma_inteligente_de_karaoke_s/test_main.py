import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from pydantic import BaseModel
from main import app, DocumentoArquitetura

client = TestClient(app)

class TestArquitetura:
    
    def test_health_check(self):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "OK"}
    
    def test_create_arquitetura_valid_payload(self):
        doc = DocumentoArquitetura(
            diretrizes="Diretrizes válidas",
            componentes=["Componente 1", "Componente 2"],
            modulos=["Modulo 1", "Modulo 2"],
            requisitos=["Requisito 1", "Requisito 2"]
        )
        response = client.post("/arquitetura", json=doc.dict())
        assert response.status_code == 200
        assert response.json() == doc.dict()
    
    def test_create_arquitetura_invalid_payload(self):
        doc = DocumentoArquitetura(
            diretrizes="Diretrizes válidas",
            componentes=["Componente 1", "Componente 2"],
            modulos=["Modulo 1", "Modulo 2"],
            requisitos=["Requisito 1", "Requisito 2"],
            extra_field="Extra"
        )
        response = client.post("/arquitetura", json=doc.dict())
        assert response.status_code == 400
        assert response.json() == {"detail": "Entrada inválida"}
    
    async def test_async_optimization(self):
        doc = DocumentoArquitetura(
            diretrizes="Diretrizes válidas",
            componentes=["Componente 1", "Componente 2"],
            modulos=["Modulo 1", "Modulo 2"],
            requisitos=["Requisito 1", "Requisito 2"]
        )
        response = await client.post("/arquitetura", json=doc.dict())
        assert response.status_code == 200
        assert response.json() == doc.dict()

#Este código cria um arquivo de testes chamado `test_main.py` que cobre os requisitos solicitados. Ele utiliza `pytest` e `TestClient` do FastAPI para testar os endpoints e validações necessárias.