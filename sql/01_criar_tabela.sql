-- ============================================================
--  GratifPanel — Criação da tabela principal
--  Execute este script no SQL Editor do Supabase
--  Menu: Database > SQL Editor > New Query
-- ============================================================

-- Tabela principal de gratificações
CREATE TABLE IF NOT EXISTS gratificacoes (

    -- Chave primária auto-gerada
    id                BIGSERIAL PRIMARY KEY,

    -- Identificação do servidor (NUMFUNC + NUMVINC concatenados)
    cod               TEXT NOT NULL,

    -- Empresa e folha
    emp_codigo        TEXT,
    mes_ano           TEXT,           -- formato MM/AAAA
    num_folha         TEXT,

    -- Estrutura organizacional
    setor             TEXT,
    orgao             TEXT,

    -- Dados funcionais
    situacao          TEXT,
    cargo             TEXT,
    tipovinc          TEXT,

    -- Rubrica e pagamento
    rubrica           TEXT,
    nome_rubrica      TEXT,
    complemento       TEXT,
    competencia       TEXT,           -- formato DD/MM/AAAA
    info              TEXT,
    tipo_pagamento    TEXT,
    tipo_rubrica      TEXT,
    vda               TEXT,           -- indica crédito ou desconto

    -- Valor (armazenado como número)
    valor             NUMERIC(15, 2),

    -- Controle de importação
    importado_em      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    importado_por     TEXT

);

-- ============================================================
--  Índices para performance nas consultas do Looker Studio
-- ============================================================

-- Busca por servidor
CREATE INDEX IF NOT EXISTS idx_cod
    ON gratificacoes (cod);

-- Filtro por mês de pagamento (usado em todos os painéis)
CREATE INDEX IF NOT EXISTS idx_mes_ano
    ON gratificacoes (mes_ano);

-- Filtro por competência
CREATE INDEX IF NOT EXISTS idx_competencia
    ON gratificacoes (competencia);

-- Filtro por rubrica
CREATE INDEX IF NOT EXISTS idx_rubrica
    ON gratificacoes (rubrica);

-- Filtro combinado mais comum: mês + rubrica
CREATE INDEX IF NOT EXISTS idx_mes_rubrica
    ON gratificacoes (mes_ano, rubrica);

-- ============================================================
--  Constraint de unicidade para evitar duplicidade
--  Garante que a mesma linha não seja inserida duas vezes
-- ============================================================

ALTER TABLE gratificacoes
    ADD CONSTRAINT uq_registro
    UNIQUE (cod, rubrica, competencia, mes_ano, num_folha);

-- ============================================================
--  Tabela de log de importações
--  Registra quem importou, quando e quantas linhas
-- ============================================================

CREATE TABLE IF NOT EXISTS importacoes_log (

    id              BIGSERIAL PRIMARY KEY,
    mes_ano         TEXT NOT NULL,
    operacao        TEXT NOT NULL,     -- 'NOVA' ou 'SUBSTITUICAO'
    arquivo         TEXT,
    linhas_total    INTEGER,
    linhas_inseridas INTEGER,
    linhas_erro     INTEGER DEFAULT 0,
    importado_por   TEXT,
    importado_em    TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    observacao      TEXT

);

-- ============================================================
--  Comentários nas colunas (documentação no próprio banco)
-- ============================================================

COMMENT ON TABLE gratificacoes IS
    'Registros de pagamento de gratificação de desempenho. Cada linha representa uma rubrica paga a um servidor em uma competência.';

COMMENT ON COLUMN gratificacoes.cod IS
    'Identificador único do servidor — concatenação de NUMFUNC + NUMVINC';

COMMENT ON COLUMN gratificacoes.mes_ano IS
    'Mês em que o pagamento foi processado — formato MM/AAAA';

COMMENT ON COLUMN gratificacoes.competencia IS
    'Competência a que o pagamento se refere — formato DD/MM/AAAA. Pode ser diferente do mes_ano.';

COMMENT ON COLUMN gratificacoes.vda IS
    'Tipo de verba. Indica se o valor é crédito ou desconto. Consultar tabela de domínios.';

COMMENT ON COLUMN gratificacoes.valor IS
    'Valor da rubrica em reais. Sempre positivo — usar coluna VDA para interpretar crédito/desconto.';
