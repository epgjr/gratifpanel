"""
GratifPanel — Servidor Web
===========================
API FastAPI que serve a aplicação de upload
e processa os arquivos CSV enviados pela equipe.

Início: uvicorn app:app --host 0.0.0.0 --port 8000
"""

import os
import io
import traceback
from datetime import datetime
from typing import Optional

import chardet
import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from supabase import create_client, Client

# Reutiliza as funções do script de ingestão
from ingestao import (
    COLUNAS_MANTER,
    TAMANHO_LOTE,
    validar_colunas,
    transformar,
    extrair_mes_ano,
    deletar_competencia,
    inserir_em_lotes,
    registrar_log,
)

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

app = FastAPI(title="GratifPanel", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Usuários autorizados (carregados da variável de ambiente)
# Formato: email1:senha1,email2:senha2,email3:senha3
ALLOWED_USERS_RAW = os.getenv("ALLOWED_USERS", "")
ALLOWED_USERS = {}

if ALLOWED_USERS_RAW:
    for user_entry in ALLOWED_USERS_RAW.split(","):
        if ":" in user_entry:
            email, password = user_entry.strip().split(":", 1)
            ALLOWED_USERS[email.strip().lower()] = password.strip()


def get_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)


# ─────────────────────────────────────────────
#  Rota de autenticação
# ─────────────────────────────────────────────

@app.post("/api/login")
async def login(email: str = Form(...), password: str = Form(...)):
    """
    Valida e-mail e senha do usuário.
    Usuários são definidos na variável de ambiente ALLOWED_USERS.
    Formato: email1:senha1,email2:senha2,email3:senha3
    """
    email_lower = email.strip().lower()
    
    # Se não houver usuários configurados, bloqueia acesso
    if not ALLOWED_USERS:
        raise HTTPException(
            status_code=403, 
            detail="Sistema não configurado. Entre em contato com o administrador."
        )
    
    # Valida e-mail e senha
    if email_lower in ALLOWED_USERS and ALLOWED_USERS[email_lower] == password:
        return JSONResponse({"ok": True, "email": email})
    else:
        raise HTTPException(status_code=401, detail="E-mail ou senha incorretos")


# ─────────────────────────────────────────────
#  Rota principal — serve o frontend
# ─────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    with open("../frontend/index.html", "r", encoding="utf-8") as f:
        return f.read()


# ─────────────────────────────────────────────
#  Rota de validação prévia do CSV
#  Chamada antes de confirmar a importação
# ─────────────────────────────────────────────

@app.post("/api/validar")
async def validar_csv(arquivo: UploadFile = File(...)):
    """
    Recebe o CSV, faz validações e retorna preview
    sem gravar nada no banco.
    """
    try:
        conteudo = await arquivo.read()

        # Detectar encoding
        resultado = chardet.detect(conteudo[:100_000])
        encoding  = resultado.get("encoding", "utf-8")

        # Ler CSV
        try:
            df = pd.read_csv(
                io.BytesIO(conteudo),
                sep=";",
                encoding=encoding,
                dtype=str,
                on_bad_lines="warn",
            )
        except Exception:
            df = pd.read_csv(
                io.BytesIO(conteudo),
                sep=";",
                encoding="latin1",
                dtype=str,
                on_bad_lines="warn",
            )

        # Validações
        colunas_faltando = [c for c in COLUNAS_MANTER if c not in df.columns]
        colunas_ok       = len(colunas_faltando) == 0
        total_linhas     = len(df)

        # Extrai MES_ANO para checar se já existe no banco
        mes_ano = df["MES_ANO"].mode().iloc[0].strip() if "MES_ANO" in df.columns else None
        ja_existe = False

        if mes_ano:
            supabase   = get_supabase()
            existentes = (
                supabase.table("gratificacoes")
                .select("id", count="exact")
                .eq("mes_ano", mes_ano)
                .execute()
            )
            ja_existe = (existentes.count or 0) > 0

        # Preview das primeiras 5 linhas (colunas selecionadas)
        colunas_preview = [
            c for c in [
                "NUMFUNC", "NUMVINC", "NOME_CARGO", "NOME_ORGAO",
                "MES_ANO", "COMPETENCIA", "NOME_RUBRICA", "VALOR"
            ]
            if c in df.columns
        ]
        preview = df[colunas_preview].head(5).fillna("").to_dict(orient="records")

        # Validação de valores
        if "VALOR" in df.columns:
            valores_invalidos = df["VALOR"].str.replace(",", ".", regex=False)
            valores_invalidos = pd.to_numeric(valores_invalidos, errors="coerce").isna().sum()
        else:
            valores_invalidos = 0

        return JSONResponse({
            "ok":                colunas_ok,
            "total_linhas":      total_linhas,
            "colunas_faltando":  colunas_faltando,
            "mes_ano":           mes_ano,
            "ja_existe":         ja_existe,
            "valores_invalidos": int(valores_invalidos),
            "preview":           preview,
            "encoding":          encoding,
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────
#  Rota de importação
#  Processa e grava no Supabase
# ─────────────────────────────────────────────

@app.post("/api/importar")
async def importar_csv(
    arquivo:    UploadFile = File(...),
    usuario:    str        = Form(...),
    substituir: bool       = Form(False),
):
    """
    Recebe o CSV, transforma e grava no Supabase.
    Se substituir=True, remove os dados do mês antes.
    """
    try:
        conteudo = await arquivo.read()
        resultado = chardet.detect(conteudo[:100_000])
        encoding  = resultado.get("encoding", "utf-8")

        try:
            df_raw = pd.read_csv(
                io.BytesIO(conteudo),
                sep=";",
                encoding=encoding,
                dtype=str,
                on_bad_lines="warn",
            )
        except Exception:
            df_raw = pd.read_csv(
                io.BytesIO(conteudo),
                sep=";",
                encoding="latin1",
                dtype=str,
                on_bad_lines="warn",
            )

        if not validar_colunas(df_raw):
            raise HTTPException(status_code=400, detail="Estrutura do CSV inválida.")

        df      = transformar(df_raw, usuario)
        mes_ano = extrair_mes_ano(df)
        operacao = "SUBSTITUICAO" if substituir else "NOVA"

        supabase = get_supabase()

        if substituir:
            deletar_competencia(supabase, mes_ano)

        inseridos, erros = inserir_em_lotes(supabase, df)

        registrar_log(
            supabase=supabase,
            mes_ano=mes_ano,
            operacao=operacao,
            arquivo=arquivo.filename,
            linhas_total=len(df),
            linhas_inseridas=inseridos,
            linhas_erro=erros,
            usuario=usuario,
        )

        return JSONResponse({
            "ok":         True,
            "mes_ano":    mes_ano,
            "inseridos":  inseridos,
            "erros":      erros,
            "operacao":   operacao,
        })

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────
#  Rota de histórico de importações
# ─────────────────────────────────────────────

@app.get("/api/historico")
async def historico():
    """Retorna as últimas importações registradas."""
    try:
        supabase = get_supabase()
        resultado = (
            supabase.table("importacoes_log")
            .select("*")
            .order("importado_em", desc=True)
            .limit(20)
            .execute()
        )
        return JSONResponse({"ok": True, "dados": resultado.data})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/competencias")
async def listar_competencias():
    """Lista todas as competências (MES_ANO) no banco com contagem de registros."""
    try:
        supabase = get_supabase()
        
        # Busca TODOS os registros (só a coluna mes_ano)
        # IMPORTANTE: range com valor alto para pegar tudo
        resultado = supabase.table("gratificacoes").select("mes_ano", count="exact").range(0, 999999).execute()
        
        # Conta manualmente usando Python
        from collections import Counter
        if resultado.data:
            counts = Counter([r["mes_ano"] for r in resultado.data if r.get("mes_ano")])
            competencias = [
                {"mes_ano": mes, "total": total} 
                for mes, total in sorted(counts.items(), reverse=True)
            ]
            return JSONResponse({"ok": True, "competencias": competencias})
        else:
            return JSONResponse({"ok": True, "competencias": []})
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/delete-competencia")
async def deletar_competencia(request: Request):
    """Deleta todos os registros de uma competência específica."""
    try:
        body = await request.json()
        mes_ano = body.get("mes_ano")
        
        if not mes_ano:
            raise HTTPException(status_code=400, detail="mes_ano não fornecido")
        
        supabase = get_supabase()
        resultado = (
            supabase.table("gratificacoes")
            .delete()
            .eq("mes_ano", mes_ano)
            .execute()
        )
        return JSONResponse({"ok": True, "deleted": len(resultado.data) if resultado.data else 0})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)
