from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import gc

app = FastAPI()

class DocumentoArquitetura(BaseModel):
    diretrizes: str
    componentes: list
    modulos: list
    requisitos: list

@app.post("/arquitetura")
async def criar_arquitetura(doc: DocumentoArquitetura):
    if not isinstance(doc, DocumentoArquitetura):
        raise HTTPException(status_code=400, detail="Entrada inválida")
    
    # Implementação de transformação do JSON em código produtivo, seguro, otimizado e modular
    # Aqui iria a lógica de transformação do JSON em código Python
    
    # Exemplo de código simplificado para demonstração
    arquitetura = {
        "diretrizes": doc.diretrizes,
        "componentes": doc.componentes,
        "modulos": doc.modulos,
        "requisitos": doc.requisitos
    }
    
    # Limpeza manual de memória fora de loops de I/O pesado
    gc.collect()
    
    return arquitetura