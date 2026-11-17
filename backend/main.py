import os
import glob
import json
import time
import re
import unicodedata
from typing import Union, Dict, Any
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
    mais_recente = max(arquivos, key=os.path.getmtime)
    return os.path.normpath(mais_recente)

class RequisitoProjeto(BaseModel):
    # Flexibilizado para aceitar tanto uma string simples quanto um JSON/dicionário estruturado de escopo
    ideia: Union[str, Dict[str, Any]]

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

def _normalizar_ideia(ideia_input: Union[str, Dict[str, Any]]) -> str:
    """Normaliza a entrada da ideia/escopo para string legível pela IA."""
    if isinstance(ideia_input, dict):
        return json.dumps(ideia_input, ensure_ascii=False, indent=2)
    return str(ideia_input)

def _gerar_slug_projeto(ideia_input: Union[str, Dict[str, Any]]) -> str:
    """
    Gera um nome de diretório curto e sugestivo (slug) com base na entrada do usuário.
    Se for um dicionário, busca 'nome_projeto', 'titulo', etc. Se for string, normaliza as primeiras palavras.
    """
    bruto = "projeto_ia"
    
    if isinstance(ideia_input, dict):
        bruto = ideia_input.get("nome_projeto") or ideia_input.get("titulo") or ideia_input.get("nome") or "projeto_corporativo"
    elif isinstance(ideia_input, str):
        linhas = [l.strip() for l in ideia_input.split("\n") if l.strip()]
        bruto = linhas[0] if linhas else "projeto_ia"
        if len(bruto) > 40:
            bruto = " ".join(bruto.split()[:4]) # Pega até 4 palavras para formar um nome curto

    # Limpeza de acentos e caracteres especiais para criar uma pasta limpa no Windows
    nfkd = unicodedata.normalize('NFKD', str(bruto))
    slug = "".join([c for c in nfkd if not unicodedata.combining(c)])
    slug = re.sub(r'[^a-zA-Z0-9]+', '_', slug).strip('_').lower()
    
    return slug[:35] if slug else "projeto_ia"

@app.get("/")
def verificar_status():
    return {"status": "A Fábrica de Software está operacional."}

@app.post("/planejar-projeto")
def planejar_projeto(requisito: RequisitoProjeto):
    ideia_texto = _normalizar_ideia(requisito.ideia)
    nome_sugerido = _gerar_slug_projeto(requisito.ideia)
    print(f"Recebendo ideia/escopo. Nome sugestivo gerado para a pasta: {nome_sugerido}")
    
    resposta_texto = consultar_ia(
        prompt=ideia_texto,
        instrucao_sistema=AGENTE_ARQUITETO_SENIOR
    )
    
    texto_limpo = resposta_texto.replace("```json", "").replace("```", "").strip()
    
    try:
        plano_json = json.loads(texto_limpo)
        # Passa o nome sugerido para o gerenciador de arquivos criar a pasta corretamente
        caminho_fisico = salvar_arquitetura(plano_json, nome_sugerido=nome_sugerido)
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


# ==========================================================
# ROTA DO ORQUESTRADOR DE PIPELINE (BLINDADA)
# ==========================================================
@app.post("/executar-pipeline", tags=["Orquestrador"])
def executar_pipeline_completo(requisito: RequisitoProjeto):
    """
    Orquestra o ciclo de vida completo de ponta a ponta:
    1. Arquiteto Sênior (Gera o JSON de arquitetura e pasta no HD com nome inteligente)
    2. Programador Sênior (Lê a arquitetura e gera o main_gerado.py)
    3. QA Sênior (Lê o código gerado e produz o test_main.py)
    """
    inicio_total = time.time()
    
    ideia_texto_normalizada = _normalizar_ideia(requisito.ideia)
    nome_sugerido = _gerar_slug_projeto(requisito.ideia)
    print(f"[Orquestrador] Iniciando pipeline. Pasta alvo: {nome_sugerido}")
    
    # ETAPA 1: Arquiteto Sênior com força máxima no formato JSON
    prompt_arquiteto = f"""
    Analise estritamente esta ideia ou escopo de projeto:
    {ideia_texto_normalizada}
    
    Retorne EXCLUSIVAMENTE um objeto JSON válido contendo a especificação técnica, 
    arquitetura de pastas e tecnologias. NÃO inclua nenhum texto, saudação ou explicação fora do JSON.
    """
    
    resposta_texto = consultar_ia(
        prompt=prompt_arquiteto,
        instrucao_sistema=AGENTE_ARQUITETO_SENIOR
    )
    
    texto_limpo = resposta_texto.replace("```json", "").replace("```", "").strip()
    
    try:
        plano_json = json.loads(texto_limpo)
        # Salva utilizando o slug inteligente gerado
        caminho_fisico = salvar_arquitetura(plano_json, nome_sugerido=nome_sugerido)
        print(f"[Orquestrador] Etapa 1 concluída. Salvo em: {caminho_fisico}")
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500, 
            detail=f"Falha na Etapa 1 (Arquiteto): A IA não retornou um JSON válido. Resposta bruta: {resposta_texto[:200]}"
        )
    
    # Descobre o caminho do JSON recém-criado
    caminho_json_recente = _encontrar_ultimo_json()
    if not caminho_json_recente:
        raise HTTPException(status_code=500, detail="Erro crítico: O arquivo de arquitetura não foi localizado no HD.")

    # ETAPA 2: Programador Sênior
    req_codigo = RequisitoCodigo(caminho_arquivo_json=caminho_json_recente)
    resp_programador = gerar_codigo_do_projeto(req_codigo)

    # ETAPA 3: QA Sênior
    req_testes = RequisitoTestes(caminho_arquivo_json=caminho_json_recente)
    resp_testes = gerar_testes_do_projeto(req_testes)

    tempo_total = round(time.time() - inicio_total, 2)

    return {
        "status": "Pipeline autônomo executado com sucesso de ponta a ponta!",
        "tempo_execucao_segundos": tempo_total,
        "arquivo_arquitetura": caminho_json_recente,
        "detalhes": {
            "arquiteto": f"Salvo na pasta corrigida ({nome_sugerido})",
            "programador": "main_gerado.py criado com sucesso",
            "qa": "test_main.py criado com sucesso"
        }
    }