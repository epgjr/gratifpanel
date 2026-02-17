# GratifPanel — Guia de Instalação e Uso

Sistema de importação e gestão da Gratificação de Desempenho.

---

## Arquitetura

```
CSV do sistema → Aplicação Web (Render.com) → Supabase (PostgreSQL) → Looker Studio
```

---

## PASSO 1 — Criar o banco no Supabase

1. Acesse https://supabase.com e crie uma conta gratuita
2. Clique em **New Project** e dê um nome (ex: `gratifpanel`)
3. No menu lateral, vá em **SQL Editor → New Query**
4. Cole o conteúdo do arquivo `sql/01_criar_tabela.sql` e clique em **Run**
5. Vá em **Project Settings → API** e copie:
   - **Project URL** → será o `SUPABASE_URL`
   - **anon / public key** → será o `SUPABASE_KEY`

---

## PASSO 2 — Configurar as credenciais

1. Copie o arquivo `backend/.env.example` para `backend/.env`
2. Preencha com as credenciais copiadas do Supabase:

```
SUPABASE_URL=https://SEUPROJETO.supabase.co
SUPABASE_KEY=SUA_CHAVE_AQUI
SECRET_KEY=qualquer-texto-longo-aleatorio
```

> ⚠️ NUNCA suba o arquivo `.env` para o GitHub.
> Ele está no `.gitignore` por padrão.

---

## PASSO 3 — Instalar dependências Python

```bash
cd backend
pip install -r requirements.txt
```

---

## PASSO 4 — Opção A: Rodar localmente

```bash
cd backend
python app.py
```

Acesse no navegador: http://localhost:8000

---

## PASSO 4 — Opção B: Publicar no Render.com (acesso para a equipe)

1. Suba o projeto para o GitHub
2. Acesse https://render.com e crie uma conta gratuita
3. Clique em **New → Web Service**
4. Conecte ao repositório GitHub
5. Configure:
   - **Root Directory:** `backend`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app:app --host 0.0.0.0 --port $PORT`
6. Em **Environment Variables**, adicione as mesmas variáveis do `.env`
7. Clique em **Deploy**

O sistema ficará disponível em: `https://gratifpanel.onrender.com`

---

## USO MENSAL — Como importar um novo mês

### Via aplicação web (recomendado para a equipe)

1. Acesse o link da aplicação
2. Informe seu nome ou e-mail
3. Faça upload do CSV exportado do sistema
4. Aguarde a validação automática
5. Revise o preview e confirme

### Via linha de comando (opcional — para o administrador)

```bash
# Importação normal
python ingestao.py --arquivo pagamento_fev_2025.csv --usuario "seu.email@orgao.gov.br"

# Substituir um mês já importado (reprocessamento)
python ingestao.py --arquivo pagamento_fev_2025.csv --usuario "seu.email@orgao.gov.br" --substituir
```

---

## PASSO 5 — Conectar ao Looker Studio

1. Acesse https://lookerstudio.google.com
2. Clique em **Criar → Fonte de dados**
3. Escolha o conector **PostgreSQL**
4. Preencha com os dados do Supabase:
   - **Host:** `db.SEUPROJETO.supabase.co`
   - **Porta:** `5432`
   - **Banco:** `postgres`
   - **Usuário:** `postgres`
   - **Senha:** (a senha que você definiu ao criar o projeto no Supabase)
5. Selecione a tabela `gratificacoes`
6. Clique em **Conectar** e comece a montar seus painéis

---

## Estrutura de arquivos

```
gratifpanel/
├── sql/
│   └── 01_criar_tabela.sql      ← Rodar no Supabase primeiro
├── backend/
│   ├── app.py                   ← Servidor web (FastAPI)
│   ├── ingestao.py              ← Script de importação
│   ├── requirements.txt         ← Dependências Python
│   └── .env.example             ← Modelo de configuração
└── frontend/
    └── index.html               ← Interface de upload
```

---

## Colunas que chegam ao banco

| Coluna | Tipo | Descrição |
|---|---|---|
| cod | TEXT | NUMFUNC + NUMVINC (chave do servidor) |
| emp_codigo | TEXT | Código da empresa |
| mes_ano | TEXT | Mês do pagamento (MM/AAAA) |
| num_folha | TEXT | Número da folha |
| setor | TEXT | Código do setor |
| orgao | TEXT | Código do órgão |
| situacao | TEXT | Situação do servidor |
| cargo | TEXT | Código do cargo |
| tipovinc | TEXT | Tipo de vínculo |
| rubrica | TEXT | Código da rubrica |
| nome_rubrica | TEXT | Nome da rubrica |
| complemento | TEXT | Complemento |
| competencia | TEXT | Competência do pagamento (DD/MM/AAAA) |
| info | TEXT | Informações adicionais |
| tipo_pagamento | TEXT | Tipo de pagamento |
| tipo_rubrica | TEXT | Tipo da rubrica |
| vda | TEXT | Tipo de verba (crédito/desconto) |
| valor | NUMERIC | Valor em reais (ponto como separador decimal) |

---

## Suporte

Em caso de dúvidas ou erros, verificar:
- Logs da aplicação no Render.com (aba Logs)
- Tabela `importacoes_log` no Supabase para histórico de operações
