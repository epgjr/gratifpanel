"""
GratifPanel — Script de Ingestão
=================================
Lê o CSV mensal da gratificação de desempenho,
aplica transformações e envia ao Supabase.

Uso:
    python ingestao.py --arquivo pagamento_fev_2025.csv --usuario "joao.silva"
    python ingestao.py --arquivo pagamento_fev_2025.csv --usuario "joao.silva" --substituir
"""

import os
import sys
import argparse
import hashlib
import chardet
import pandas as pd
from datetime import datetime
from supabase import create_client, Client
from dotenv import load_dotenv

# ─────────────────────────────────────────────
#  Configuração
# ─────────────────────────────────────────────

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Colunas que serão MANTIDAS do CSV original
COLUNAS_MANTER = [
    "EMP_CODIGO",
    "MES_ANO",
    "NUM_FOLHA",
    "SETOR",
    "ORGAO",
    "NUMFUNC",
    "NUMVINC",
    "SITUACAO",
    "CARGO",
    "TIPOVINC",
    "RUBRICA",
    "NOME_RUBRICA",
    "COMPLEMENTO",
    "COMPETENCIA",
    "INFO",
    "TIPO_PAGAMENTO",
    "TIPO_RUBRICA",
    "VDA",
    "VALOR",
]

# Tamanho dos lotes de inserção (evita timeout)
TAMANHO_LOTE = 500


# ─────────────────────────────────────────────
#  Funções auxiliares
# ─────────────────────────────────────────────

def detectar_encoding(caminho_arquivo: str) -> str:
    """Detecta automaticamente o encoding do arquivo."""
    with open(caminho_arquivo, "rb") as f:
        resultado = chardet.detect(f.read(100_000))
    encoding = resultado.get("encoding", "utf-8")
    print(f"  → Encoding detectado: {encoding} (confiança: {resultado.get('confidence', 0):.0%})")
    return encoding


def ler_csv(caminho_arquivo: str) -> pd.DataFrame:
    """Lê o CSV com detecção automática de encoding."""
    print("\n📂 Lendo arquivo CSV...")
    encoding = detectar_encoding(caminho_arquivo)

    try:
        df = pd.read_csv(
            caminho_arquivo,
            sep=";",
            encoding=encoding,
            dtype=str,           # lê tudo como texto primeiro
            on_bad_lines="warn", # avisa sobre linhas problemáticas
        )
    except Exception:
        # Tenta Latin1 como fallback
        print("  → Tentando encoding Latin1 como fallback...")
        df = pd.read_csv(
            caminho_arquivo,
            sep=";",
            encoding="latin1",
            dtype=str,
            on_bad_lines="warn",
        )

    print(f"  → {len(df):,} linhas e {len(df.columns)} colunas encontradas")
    return df


def validar_colunas(df: pd.DataFrame) -> bool:
    """Verifica se as colunas obrigatórias existem no arquivo."""
    print("\n🔍 Validando estrutura do arquivo...")
    faltando = [c for c in COLUNAS_MANTER if c not in df.columns]

    if faltando:
        print(f"  ✗ ERRO — Colunas obrigatórias ausentes: {faltando}")
        return False

    print(f"  ✓ Todas as {len(COLUNAS_MANTER)} colunas obrigatórias encontradas")
    return True


def transformar(df: pd.DataFrame, usuario: str) -> pd.DataFrame:
    """Aplica todas as transformações necessárias."""
    print("\n⚙️  Transformando dados...")

    # 1. Manter apenas as colunas necessárias
    df = df[COLUNAS_MANTER].copy()

    # 2. Limpar espaços em branco em todas as colunas de texto
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].str.strip()

    # 3. Criar coluna COD (NUMFUNC + NUMVINC concatenados)
    df["cod"] = df["NUMFUNC"].fillna("") + df["NUMVINC"].fillna("")
    df["cod"] = df["cod"].str.strip()

    # 4. Converter VALOR: trocar vírgula por ponto e converter para número
    df["VALOR"] = (
        df["VALOR"]
        .str.replace(",", ".", regex=False)
        .str.replace(r"[^\d.\-]", "", regex=True)  # remove caracteres estranhos
    )
    df["VALOR"] = pd.to_numeric(df["VALOR"], errors="coerce")

    # 5. Remover linhas sem COD ou sem VALOR válido
    antes = len(df)
    df = df.dropna(subset=["cod", "VALOR"])
    df = df[df["cod"] != ""]
    depois = len(df)
    if antes != depois:
        print(f"  ⚠ {antes - depois:,} linhas removidas por COD ou VALOR inválidos")

    # 6. Renomear colunas para minúsculas (padrão do banco)
    df = df.rename(columns={
        "EMP_CODIGO":     "emp_codigo",
        "MES_ANO":        "mes_ano",
        "NUM_FOLHA":      "num_folha",
        "SETOR":          "setor",
        "ORGAO":          "orgao",
        "SITUACAO":       "situacao",
        "CARGO":          "cargo",
        "TIPOVINC":       "tipovinc",
        "RUBRICA":        "rubrica",
        "NOME_RUBRICA":   "nome_rubrica",
        "COMPLEMENTO":    "complemento",
        "COMPETENCIA":    "competencia",
        "INFO":           "info",
        "TIPO_PAGAMENTO": "tipo_pagamento",
        "TIPO_RUBRICA":   "tipo_rubrica",
        "VDA":            "vda",
        "VALOR":          "valor",
    })

    # 7. Remover colunas NUMFUNC e NUMVINC originais (já usadas no COD)
    df = df.drop(columns=["NUMFUNC", "NUMVINC"], errors="ignore")

    # 8. Adicionar metadados de importação
    df["importado_por"] = usuario
    df["importado_em"]  = datetime.now().isoformat()

    # 9. Substituir NaN por None (compatível com JSON/Supabase)
    df = df.where(pd.notnull(df), None)

    print(f"  ✓ {len(df):,} linhas prontas para importação")
    return df


def extrair_mes_ano(df: pd.DataFrame) -> str:
    """Extrai o MES_ANO dominante do arquivo para usar no log."""
    if "mes_ano" in df.columns:
        return df["mes_ano"].mode().iloc[0] if not df["mes_ano"].empty else "DESCONHECIDO"
    return "DESCONHECIDO"


def deletar_competencia(supabase: Client, mes_ano: str) -> int:
    """Remove todos os registros de um MES_ANO para reprocessamento."""
    print(f"\n🗑️  Removendo registros existentes de {mes_ano}...")
    resultado = supabase.table("gratificacoes").delete().eq("mes_ano", mes_ano).execute()
    total = len(resultado.data) if resultado.data else 0
    print(f"  ✓ {total:,} registros removidos")
    return total


def inserir_em_lotes(supabase: Client, df: pd.DataFrame) -> tuple[int, int]:
    """Insere os dados em lotes para evitar timeout."""
    print(f"\n📤 Enviando dados ao Supabase em lotes de {TAMANHO_LOTE}...")
    total = len(df)
    inseridos = 0
    erros = 0

    registros = df.to_dict(orient="records")

    for i in range(0, total, TAMANHO_LOTE):
        lote = registros[i : i + TAMANHO_LOTE]
        progresso = min(i + TAMANHO_LOTE, total)

        try:
            supabase.table("gratificacoes").insert(lote).execute()
            inseridos += len(lote)
            print(f"  → {progresso:,} / {total:,} registros enviados...", end="\r")
        except Exception as e:
            erros += len(lote)
            print(f"\n  ⚠ Erro no lote {i}–{progresso}: {e}")

    print(f"\n  ✓ Concluído: {inseridos:,} inseridos, {erros:,} erros")
    return inseridos, erros


def registrar_log(
    supabase: Client,
    mes_ano: str,
    operacao: str,
    arquivo: str,
    linhas_total: int,
    linhas_inseridas: int,
    linhas_erro: int,
    usuario: str,
):
    """Registra a importação na tabela de log."""
    supabase.table("importacoes_log").insert({
        "mes_ano":          mes_ano,
        "operacao":         operacao,
        "arquivo":          arquivo,
        "linhas_total":     linhas_total,
        "linhas_inseridas": linhas_inseridas,
        "linhas_erro":      linhas_erro,
        "importado_por":    usuario,
        "importado_em":     datetime.now().isoformat(),
    }).execute()


# ─────────────────────────────────────────────
#  Função principal
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="GratifPanel — Importação de CSV para o Supabase"
    )
    parser.add_argument(
        "--arquivo",
        required=True,
        help="Caminho do arquivo CSV (ex: pagamento_fev_2025.csv)"
    )
    parser.add_argument(
        "--usuario",
        required=True,
        help="Nome ou e-mail de quem está fazendo a importação"
    )
    parser.add_argument(
        "--substituir",
        action="store_true",
        help="Remove os dados do mês antes de importar (reprocessamento)"
    )
    args = parser.parse_args()

    # ── Validações iniciais
    if not os.path.exists(args.arquivo):
        print(f"\n✗ Arquivo não encontrado: {args.arquivo}")
        sys.exit(1)

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("\n✗ Variáveis SUPABASE_URL e SUPABASE_KEY não configuradas no .env")
        sys.exit(1)

    print("\n" + "═" * 50)
    print("  GratifPanel — Importação de Gratificação")
    print("═" * 50)
    print(f"  Arquivo : {os.path.basename(args.arquivo)}")
    print(f"  Usuário : {args.usuario}")
    print(f"  Modo    : {'SUBSTITUIÇÃO' if args.substituir else 'NOVA IMPORTAÇÃO'}")

    # ── Conectar ao Supabase
    print("\n🔌 Conectando ao Supabase...")
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("  ✓ Conexão estabelecida")
    except Exception as e:
        print(f"  ✗ Erro de conexão: {e}")
        sys.exit(1)

    # ── Ler e transformar
    df_raw = ler_csv(args.arquivo)

    if not validar_colunas(df_raw):
        sys.exit(1)

    df = transformar(df_raw, args.usuario)
    mes_ano = extrair_mes_ano(df)
    operacao = "SUBSTITUICAO" if args.substituir else "NOVA"

    print(f"\n📅 Competência detectada: {mes_ano}")

    # ── Confirmar substituição
    if args.substituir:
        print(f"\n⚠️  ATENÇÃO: Todos os registros de {mes_ano} serão removidos antes da importação.")
        confirmacao = input("  Digite SIM para confirmar: ").strip().upper()
        if confirmacao != "SIM":
            print("  Operação cancelada.")
            sys.exit(0)
        deletar_competencia(supabase, mes_ano)

    # ── Inserir dados
    inseridos, erros = inserir_em_lotes(supabase, df)

    # ── Registrar log
    registrar_log(
        supabase=supabase,
        mes_ano=mes_ano,
        operacao=operacao,
        arquivo=os.path.basename(args.arquivo),
        linhas_total=len(df),
        linhas_inseridas=inseridos,
        linhas_erro=erros,
        usuario=args.usuario,
    )

    # ── Resumo final
    print("\n" + "═" * 50)
    print("  IMPORTAÇÃO CONCLUÍDA")
    print("═" * 50)
    print(f"  MES_ANO   : {mes_ano}")
    print(f"  Total     : {len(df):,} linhas processadas")
    print(f"  Inseridos : {inseridos:,}")
    print(f"  Erros     : {erros:,}")
    print(f"  Operação  : {operacao}")
    print("═" * 50 + "\n")


if __name__ == "__main__":
    main()
