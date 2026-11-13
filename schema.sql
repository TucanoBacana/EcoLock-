-- ============================================================================
-- EcoLock - Script de criação do banco de dados (MySQL / XAMPP)
-- Execute no phpMyAdmin ou no terminal:  mysql -u root < schema.sql
-- ============================================================================

CREATE DATABASE IF NOT EXISTS ecolock
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE ecolock;

-- Níveis de permissão definidos pelo Ministério do Meio Ambiente
CREATE TABLE IF NOT EXISTS niveis (
    id          TINYINT      PRIMARY KEY,
    nome        VARCHAR(40)  NOT NULL,
    descricao   VARCHAR(200) NOT NULL
);

-- Pessoas autorizadas a solicitar acesso ao cofre
CREATE TABLE IF NOT EXISTS usuarios (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    nome        VARCHAR(120) NOT NULL,
    cargo       VARCHAR(80)  NOT NULL,
    divisao     VARCHAR(80)  NULL,
    nivel_id    TINYINT      NOT NULL,
    ativo       BOOLEAN      NOT NULL DEFAULT TRUE,
    criado_em   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_usuario_nivel FOREIGN KEY (nivel_id) REFERENCES niveis(id)
);

-- Vetores faciais (128 números) de cada usuário. Nenhuma foto é armazenada.
CREATE TABLE IF NOT EXISTS faces (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    usuario_id  INT          NOT NULL,
    vetor       BLOB         NOT NULL,
    criado_em   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_face_usuario FOREIGN KEY (usuario_id)
        REFERENCES usuarios(id) ON DELETE CASCADE
);

-- Áreas do cofre, o nível mínimo exigido e, nas áreas de nível 2, a divisão
-- dona da área (só o diretor DAQUELA divisão entra)
CREATE TABLE IF NOT EXISTS areas (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    nome         VARCHAR(80)  NOT NULL,
    nivel_minimo TINYINT      NOT NULL,
    divisao      VARCHAR(80)  NULL,
    CONSTRAINT fk_area_nivel FOREIGN KEY (nivel_minimo) REFERENCES niveis(id)
);

-- Administradores: únicos autorizados a cadastrar, excluir e auditar.
-- A senha nunca é gravada: só o resumo PBKDF2-SHA256 com sal aleatório.
CREATE TABLE IF NOT EXISTS administradores (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    usuario     VARCHAR(40)  NOT NULL UNIQUE,
    sal         CHAR(32)     NOT NULL,
    senha_hash  CHAR(64)     NOT NULL,
    criado_em   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Histórico de todas as tentativas de acesso (permitidas e negadas)
CREATE TABLE IF NOT EXISTS logs_acesso (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    usuario_id  INT          NULL,
    area_id     INT          NOT NULL,
    resultado   ENUM('PERMITIDO','NEGADO') NOT NULL,
    motivo      VARCHAR(200) NOT NULL,
    distancia   FLOAT        NULL,
    data_hora   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_log_usuario FOREIGN KEY (usuario_id)
        REFERENCES usuarios(id) ON DELETE SET NULL,
    CONSTRAINT fk_log_area FOREIGN KEY (area_id) REFERENCES areas(id),
    INDEX idx_log_data (data_hora)
);

-- Alertas gerados por tentativas suspeitas
CREATE TABLE IF NOT EXISTS alertas (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    tipo        VARCHAR(40)  NOT NULL,
    descricao   VARCHAR(255) NOT NULL,
    area_id     INT          NULL,
    resolvido   BOOLEAN      NOT NULL DEFAULT FALSE,
    data_hora   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_alerta_area FOREIGN KEY (area_id) REFERENCES areas(id)
);

-- Dados iniciais -------------------------------------------------------------
INSERT IGNORE INTO niveis (id, nome, descricao) VALUES
 (1, 'Nível 1 - Geral',   'Indivíduos com permissão geral'),
 (2, 'Nível 2 - Diretor', 'Diretores de divisões específicas'),
 (3, 'Nível 3 - Ministro','Exclusivo do ministro do Meio Ambiente');

INSERT INTO areas (nome, nivel_minimo)
SELECT * FROM (SELECT 'Arquivo Geral', 1) AS a
WHERE NOT EXISTS (SELECT 1 FROM areas WHERE nome = 'Arquivo Geral');
INSERT INTO areas (nome, nivel_minimo)
SELECT * FROM (SELECT 'Divisão de Toxinas', 2) AS a
WHERE NOT EXISTS (SELECT 1 FROM areas WHERE nome = 'Divisão de Toxinas');
INSERT INTO areas (nome, nivel_minimo)
SELECT * FROM (SELECT 'Divisão de Biodiversidade', 2) AS a
WHERE NOT EXISTS (SELECT 1 FROM areas WHERE nome = 'Divisão de Biodiversidade');
INSERT INTO areas (nome, nivel_minimo)
SELECT * FROM (SELECT 'Cofre Central', 3) AS a
WHERE NOT EXISTS (SELECT 1 FROM areas WHERE nome = 'Cofre Central');
-- (a coluna "divisao" das áreas de nível 2 é preenchida por database.py, que
--  também a cria em bancos gerados por versões anteriores do EcoLock)