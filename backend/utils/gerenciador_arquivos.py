import os
import json
import re
from datetime import datetime

def salvar_arquitetura(plano_json: dict) -> str:
    """
    Recebe o JSON do Arquiteto, cria a pasta do projeto com o nome real e salva o documento no HD.
    Retorna o caminho físico de onde o arquivo foi salvo.
    """
    # 1. Extrai o nome do projeto (suportando tanto a raiz quanto o padrão aninhado em metadata)
    metadata = plano_json.get("metadata", {})
    nome_cru = plano_json.get("nome_projeto") or metadata.get("nome_projeto", "Projeto_Sem_Nome")
    
    # 2. Limpeza: Remove caracteres especiais (espaços, barras, acentos) para não quebrar o Windows
    nome_pasta = re.sub(r'[^A-Za-z0-9]', '_', nome_cru)
    # Remove underscores duplicados
    nome_pasta = re.sub(r'_+', '_', nome_pasta).strip('_')
    
    # 3. Define onde a Fábrica vai despejar os projetos (cria uma pasta 'projetos_gerados' na raiz do backend)
    caminho_base = os.path.join(os.getcwd(), "projetos_gerados", nome_pasta)
    
    # 4. Cria a pasta física no Windows (exist_ok=True impede erro se a pasta já existir)
    os.makedirs(caminho_base, exist_ok=True)
    
    # 5. Define o nome do arquivo com Timestamp (para não sobrescrever se você gerar várias versões)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    nome_arquivo = f"01_arquitetura_{timestamp}.json"
    caminho_completo = os.path.join(caminho_base, nome_arquivo)
    
    # 6. Grava (I/O) o arquivo fisicamente no HD
    with open(caminho_completo, "w", encoding="utf-8") as arquivo:
        json.dump(plano_json, arquivo, indent=4, ensure_ascii=False)
        
    return caminho_completo