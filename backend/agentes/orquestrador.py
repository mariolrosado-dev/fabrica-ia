import os
import time
from backend.agentes.prompts import chamar_gemini
from backend.utils.gerenciador_arquivos import salvar_arquivo_projeto

def executar_pipeline_completo(ideia_projeto: str) -> dict:
    """
    Orquestra o ciclo de vida completo: Arquiteto -> Programador -> QA
    """
    inicio_total = time.time()
    relatorio = {
        "projeto": "",
        "status": "sucesso",
        "etapas": {},
        "erros": None
    }

    try:
        # ==========================================
        # ETAPA 1: AGENTE ARQUITETO SÊNIOR
        # ==========================================
        print(f"[Orquestrador] Iniciando Etapa 1: Arquitetura para -> {ideia_projeto}")
        prompt_arquiteto = f"""
        Você é um Arquiteto de Software Sênior. Analise a ideia: '{ideia_projeto}'.
        Gere a especificação técnica e estrutura de pastas em formato JSON puro.
        """
        resp_arquiteto = chamar_gemini(prompt_arquiteto)
        
        # Nome do projeto normalizado para pasta
        nome_projeto = ideia_projeto.strip().replace(" ", "_").replace("-", "_")[:30]
        relatorio["projeto"] = nome_projeto
        
        # Salva o contrato de arquitetura
        path_arq = salvar_arquivo_projeto(nome_projeto, "01_arquitetura.json", resp_arquiteto)
        relatorio["etapas"]["arquiteto"] = {"status": "concluido", "arquivo": path_arq}

        # ==========================================
        # ETAPA 2: AGENTE PROGRAMADOR SÊNIOR
        # ==========================================
        print(f"[Orquestrador] Iniciando Etapa 2: Geração de Código para -> {nome_projeto}")
        prompt_programador = f"""
        Com base na arquitetura e ideia '{ideia_projeto}', escreva o código Python completo 
        e funcional (em FastAPI ou script principal) utilizando boas práticas. 
        Retorne apenas o código Python limpo.
        """
        resp_codigo = chamar_gemini(prompt_programador)
        
        # Limpeza de blocos markdown se o LLM retornar
        codigo_limpo = resp_codigo.replace("```python", "").replace("```", "").strip()
        path_codigo = salvar_arquivo_projeto(nome_projeto, "main_gerado.py", codigo_limpo)
        relatorio["etapas"]["programador"] = {"status": "concluido", "arquivo": path_codigo}

        # ==========================================
        # ETAPA 3: AGENTE QA SÊNIOR
        # ==========================================
        print(f"[Orquestrador] Iniciando Etapa 3: Geração de Testes Automatizados (Pytest)")
        prompt_qa = f"""
        Você é um Engenheiro QA Sênior. Analise o código abaixo e crie uma suíte de 
        testes robusta utilizando 'pytest' que garanta 100% de cobertura das funções principais.
        Retorne apenas o código Python do teste limpo.
        
        CÓDIGO FONTE:
        {codigo_limpo}
        """
        resp_testes = chamar_gemini(prompt_qa)
        
        testes_limpos = resp_testes.replace("```python", "").replace("```", "").strip()
        path_testes = salvar_arquivo_projeto(nome_projeto, "test_main.py", testes_limpos)
        relatorio["etapas"]["qa"] = {"status": "concluido", "arquivo": path_testes}

        tempo_total = round(time.time() - inicio_total, 2)
        relatorio["tempo_execucao_segundos"] = tempo_total
        print(f"[Orquestrador] Pipeline concluído com sucesso em {tempo_total}s!")

    except Exception as e:
        relatorio["status"] = "erro"
        relatorio["erros"] = str(e)
        print(f"[Orquestrador] ERRO CRÍTICO no pipeline: {e}")

    return relatorio