import os
import glob
import json
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from agentes.llm_adapter import consultar_ia
from agentes.prompts import AGENTE_ARQUITETO_SENIOR, AGENTE_PROGRAMADOR_SENIOR, AGENTE_QA_SENIOR
from utils.gerenciador_arquivos import salvar_arquitetura

app = FastAPI(
    title="Plataforma de Engenharia IA", 
    description="Fábrica autônoma de desenvolvimento de software",
    version="2.0"
)

def _encontrar_ultimo_json() -> str:
    """Busca automaticamente o arquivo de arquitetura mais recente dentro de projetos_gerados."""
    padrao = os.path.join("projetos_gerados", "**", "*.json")
    arquivos = glob.glob(padrao, recursive=True)
    if not arquivos:
        return ""
    # Retorna o arquivo mais recente com base na data de modificação
    mais_recente = max(arquivos, key=os.path.getmtime)
    return os.path.normpath(mais_recente)

class RequisitoProjeto(BaseModel):
    ideia: str

class RequisitoCodigo(BaseModel):
    caminho_arquivo_json: str = Field(
        default_factory=_encontrar_ultimo_json,
        description="Caminho do arquivo JSON de arquitetura detectado automaticamente."
    )

class RequisitoTestes(BaseModel):
    caminho_arquivo_json: str = Field(
        default_factory=_encontrar_ultimo_json,
        description="Caminho do arquivo JSON de arquitetura detectado automaticamente para basear os testes."
    )

@app.get("/")
def verificar_status():
    return {"status": "A Fábrica de Software está operacional."}

@app.post("/planejar-projeto")
def planejar_projeto(requisito: RequisitoProjeto):
    print(f"Recebendo ideia: {requisito.ideia}")
    
    resposta_texto = consultar_ia(
        prompt=requisito.ideia,
        instrucao_sistema=AGENTE_ARQUITETO_SENIOR
    )
    
    texto_limpo = resposta_texto.replace("```json", "").replace("```", "").strip()
    
    try:
        plano_json = json.loads(texto_limpo)
        caminho_fisico = salvar_arquitetura(plano_json)
        plano_json["_STATUS_FABRICA"] = f"Sucesso! Projeto salvo fisicamente em: {caminho_fisico}"
        return plano_json
        
    except json.JSONDecodeError:
        return {
            "status": "Erro de Formatação",
            "aviso": "A IA não retornou um JSON válido.",
            "resposta_bruta": resposta_texto
        }

# ==========================================================
# ROTA DO AGENTE PROGRAMADOR SÊNIOR
# ==========================================================
@app.post("/gerar-codigo")
def gerar_codigo_do_projeto(requisito: RequisitoCodigo):
    caminho_alvo = requisito.caminho_arquivo_json
    
    # Se o campo vier vazio ou o arquivo não existir, tenta buscar o mais recente dinamicamente
    if not caminho_alvo or not os.path.exists(caminho_alvo):
        caminho_alvo = _encontrar_ultimo_json()
        if not caminho_alvo or not os.path.exists(caminho_alvo):
            raise HTTPException(status_code=404, detail="Nenhum arquivo de arquitetura válido encontrado no HD.")

    print(f"Lendo arquitetura do HD: {caminho_alvo}")
    
    try:
        with open(caminho_alvo, 'r', encoding='utf-8') as arquivo:
            arquitetura_json = arquivo.read()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Arquivo de arquitetura não encontrado no HD.")
        
    prompt_comando = f"Baseado estritamente nesta arquitetura, gere o código FastAPI principal (main.py): {arquitetura_json}"
    
    codigo_gerado = consultar_ia(
        prompt=prompt_comando,
        instrucao_sistema=AGENTE_PROGRAMADOR_SENIOR
    )
    
    codigo_limpo = codigo_gerado.replace("```python", "").replace("```", "").strip()
    
    # Salva o código gerado no HD identificando-o como o código final na mesma pasta do projeto
    try:
        pasta_projeto = os.path.dirname(caminho_alvo)
        caminho_codigo_final = os.path.join(pasta_projeto, "main_gerado.py")
        with open(caminho_codigo_final, "w", encoding="utf-8") as f_codigo:
            f_codigo.write(codigo_limpo)
        print(f"Código final salvo em: {caminho_codigo_final}")
    except Exception as e:
        print(f"Aviso ao salvar código final no HD: {str(e)}")
    
    return {
        "status": "Código gerado com sucesso!",
        "caminho_codigo_final": locals().get("caminho_codigo_final", "Salvo na pasta do projeto"),
        "codigo_fonte": codigo_limpo
    }

# ==========================================================
# ROTA DO AGENTE QA E TESTES SÊNIOR
# ==========================================================
@app.post("/gerar-testes", tags=["QA e Testes"])
def gerar_testes_do_projeto(requisito: RequisitoTestes):
    caminho_alvo = requisito.caminho_arquivo_json
    
    if not caminho_alvo or not os.path.exists(caminho_alvo):
        caminho_alvo = _encontrar_ultimo_json()
        if not caminho_alvo or not os.path.exists(caminho_alvo):
            raise HTTPException(status_code=404, detail="Nenhum arquivo de arquitetura válido encontrado para gerar os testes.")

    # Localiza o main_gerado.py na mesma pasta do projeto
    pasta_projeto = os.path.dirname(caminho_alvo)
    caminho_main_gerado = os.path.join(pasta_projeto, "main_gerado.py")
    
    if not os.path.exists(caminho_main_gerado):
        raise HTTPException(status_code=404, detail="Arquivo main_gerado.py não encontrado na pasta do projeto. Gere o código primeiro.")

    print(f"Lendo código fonte para testes: {caminho_main_gerado}")
    try:
        with open(caminho_main_gerado, "r", encoding="utf-8") as f:
            codigo_fonte = f.read()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Arquivo main_gerado.py não encontrado no HD.")

    prompt_comando = f"Baseado estritamente neste código fonte FastAPI, gere a suíte de testes em pytest (test_main.py): {codigo_fonte}"
    
    resposta_ia = consultar_ia(
        prompt=prompt_comando,
        instrucao_sistema=AGENTE_QA_SENIOR
    )
    
    codigo_testes_limpo = resposta_ia.replace("```python", "").replace("```", "").strip()
    
    # Salva o test_main.py na mesma pasta física do projeto no HD
    try:
        caminho_testes_final = os.path.join(pasta_projeto, "test_main.py")
        with open(caminho_testes_final, "w", encoding="utf-8") as f_test:
            f_test.write(codigo_testes_limpo)
        print(f"Suíte de testes salva em: {caminho_testes_final}")
    except Exception as e:
        print(f"Aviso ao salvar arquivo de testes no HD: {str(e)}")

    return {
        "status": "Suíte de testes gerada com sucesso!",
        "caminho_arquivo_testes": locals().get("caminho_arquivo_testes", "Salvo na pasta do projeto"),
        "codigo_testes": codigo_testes_limpo
    }