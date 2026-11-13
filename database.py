"""
EcoLock - Camada de acesso ao banco de dados MySQL.

Concentra todas as consultas SQL do sistema. Os demais módulos nunca
escrevem SQL diretamente: eles chamam os métodos desta classe.
"""

from datetime import datetime, timedelta
from pathlib import Path

import mysql.connector
import numpy as np

import config


class BancoDeDados:
    """Encapsula a conexão com o MySQL e as operações do EcoLock."""

    def __init__(self, cfg: dict = None):
        self.cfg = cfg or config.DB_CONFIG
        self._garantir_banco()
        self.conexao = mysql.connector.connect(**self.cfg)
        self.conexao.autocommit = True

    # ------------------------------------------------------------------ setup
    def _garantir_banco(self):
        """Cria o banco e as tabelas na primeira execução (executa schema.sql)."""
        sem_banco = {k: v for k, v in self.cfg.items() if k != "database"}
        con = mysql.connector.connect(**sem_banco)
        cur = con.cursor()
        script = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        for comando in self._dividir_script(script):
            cur.execute(comando)
        self._migrar(cur)
        con.commit()
        cur.close()
        con.close()

    def _migrar(self, cur):
        """
        Atualiza bancos criados por versões anteriores (sem a coluna areas.divisao)
        e define a divisão dona de cada área de nível 2.
        """
        banco = self.cfg["database"]
        cur.execute("""SELECT COUNT(*) FROM information_schema.COLUMNS
                        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'areas'
                          AND COLUMN_NAME = 'divisao'""", (banco,))
        if cur.fetchone()[0] == 0:
            cur.execute(f"ALTER TABLE `{banco}`.areas ADD COLUMN divisao VARCHAR(80) NULL")
        for area in config.DIVISOES:
            cur.execute(f"UPDATE `{banco}`.areas SET divisao = %s WHERE nome = %s", (area, area))

    @staticmethod
    def _dividir_script(script: str):
        """Separa o arquivo .sql em comandos individuais, ignorando comentários."""
        linhas = [l for l in script.splitlines() if not l.strip().startswith("--")]
        for comando in "\n".join(linhas).split(";"):
            if comando.strip():
                yield comando

    def _cursor(self):
        # Reconecta automaticamente caso o MySQL tenha encerrado a conexão ociosa
        self.conexao.ping(reconnect=True, attempts=3, delay=1)
        return self.conexao.cursor(dictionary=True)

    def fechar(self):
        if self.conexao.is_connected():
            self.conexao.close()

    # ----------------------------------------------------------------- níveis
    def listar_niveis(self):
        cur = self._cursor()
        cur.execute("SELECT id, nome, descricao FROM niveis ORDER BY id")
        return cur.fetchall()

    def listar_areas(self):
        cur = self._cursor()
        cur.execute("SELECT id, nome, nivel_minimo, divisao FROM areas ORDER BY nivel_minimo, nome")
        return cur.fetchall()

    # -------------------------------------------------------- administradores
    def tem_administrador(self) -> bool:
        cur = self._cursor()
        cur.execute("SELECT COUNT(*) AS total FROM administradores")
        return cur.fetchone()["total"] > 0

    def criar_administrador(self, usuario, sal, senha_hash):
        cur = self._cursor()
        cur.execute("INSERT INTO administradores (usuario, sal, senha_hash) VALUES (%s, %s, %s)",
                    (usuario, sal, senha_hash))

    def buscar_administrador(self, usuario):
        cur = self._cursor()
        cur.execute("SELECT * FROM administradores WHERE usuario = %s", (usuario,))
        return cur.fetchone()

    def contar_ativos_no_nivel(self, nivel_id, exceto_id=None):
        """Usado para garantir que exista um único ministro (nível 3) ativo."""
        cur = self._cursor()
        cur.execute("SELECT COUNT(*) AS total FROM usuarios WHERE nivel_id = %s AND ativo = TRUE"
                    " AND id <> %s", (nivel_id, exceto_id or 0))
        return cur.fetchone()["total"]

    # --------------------------------------------------------------- usuários
    def cadastrar_usuario(self, nome, cargo, divisao, nivel_id, vetores):
        """Grava o usuário e seus vetores faciais em uma única transação."""
        cur = self._cursor()
        self.conexao.start_transaction()
        try:
            cur.execute(
                "INSERT INTO usuarios (nome, cargo, divisao, nivel_id) VALUES (%s,%s,%s,%s)",
                (nome, cargo, divisao or None, nivel_id),
            )
            usuario_id = cur.lastrowid
            for vetor in vetores:
                cur.execute(
                    "INSERT INTO faces (usuario_id, vetor) VALUES (%s, %s)",
                    (usuario_id, np.asarray(vetor, dtype=np.float64).tobytes()),
                )
            self.conexao.commit()
            return usuario_id
        except Exception:
            self.conexao.rollback()
            raise

    def listar_usuarios(self):
        cur = self._cursor()
        cur.execute(
            """SELECT u.id, u.nome, u.cargo, u.divisao, u.nivel_id, u.ativo,
                      u.criado_em, COUNT(f.id) AS amostras
                 FROM usuarios u LEFT JOIN faces f ON f.usuario_id = u.id
             GROUP BY u.id ORDER BY u.nivel_id DESC, u.nome"""
        )
        return cur.fetchall()

    def buscar_usuario(self, usuario_id):
        cur = self._cursor()
        cur.execute("SELECT * FROM usuarios WHERE id = %s", (usuario_id,))
        return cur.fetchone()

    def alterar_status(self, usuario_id, ativo: bool):
        cur = self._cursor()
        cur.execute("UPDATE usuarios SET ativo = %s WHERE id = %s", (ativo, usuario_id))

    def excluir_usuario(self, usuario_id):
        """Remove o usuário e, em cascata, seus dados biométricos (direito da LGPD)."""
        cur = self._cursor()
        cur.execute("DELETE FROM usuarios WHERE id = %s", (usuario_id,))

    def carregar_vetores_ativos(self):
        """Retorna (ids, vetores) de todos os rostos de usuários ativos."""
        cur = self._cursor()
        cur.execute(
            """SELECT f.usuario_id, f.vetor FROM faces f
                 JOIN usuarios u ON u.id = f.usuario_id WHERE u.ativo = TRUE"""
        )
        ids, vetores = [], []
        for linha in cur.fetchall():
            ids.append(linha["usuario_id"])
            vetores.append(np.frombuffer(linha["vetor"], dtype=np.float64))
        return ids, vetores

    # ------------------------------------------------------------------- logs
    def registrar_acesso(self, usuario_id, area_id, permitido, motivo, distancia=None):
        cur = self._cursor()
        cur.execute(
            """INSERT INTO logs_acesso (usuario_id, area_id, resultado, motivo, distancia)
               VALUES (%s, %s, %s, %s, %s)""",
            (usuario_id, area_id, "PERMITIDO" if permitido else "NEGADO", motivo,
             None if distancia is None else float(distancia)),
        )

    def contar_negacoes_recentes(self, area_id, minutos):
        cur = self._cursor()
        limite = datetime.now() - timedelta(minutes=minutos)
        cur.execute(
            """SELECT COUNT(*) AS total FROM logs_acesso
                WHERE resultado = 'NEGADO' AND area_id = %s AND data_hora >= %s""",
            (area_id, limite),
        )
        return cur.fetchone()["total"]

    def consultar_logs(self, inicio: datetime, fim: datetime, resultado=None, usuario_id=None):
        sql = """SELECT l.id, l.data_hora, COALESCE(u.nome, 'Desconhecido') AS usuario,
                        a.nome AS area, a.nivel_minimo, l.resultado, l.motivo, l.distancia
                   FROM logs_acesso l
                   JOIN areas a ON a.id = l.area_id
              LEFT JOIN usuarios u ON u.id = l.usuario_id
                  WHERE l.data_hora BETWEEN %s AND %s"""
        params = [inicio, fim]
        if resultado:
            sql += " AND l.resultado = %s"
            params.append(resultado)
        if usuario_id:
            sql += " AND l.usuario_id = %s"
            params.append(usuario_id)
        sql += " ORDER BY l.data_hora DESC"
        cur = self._cursor()
        cur.execute(sql, params)
        return cur.fetchall()

    # ---------------------------------------------------------------- alertas
    def registrar_alerta(self, tipo, descricao, area_id=None):
        cur = self._cursor()
        cur.execute(
            "INSERT INTO alertas (tipo, descricao, area_id) VALUES (%s, %s, %s)",
            (tipo, descricao, area_id),
        )

    def alerta_aberto_recente(self, area_id, minutos):
        """Evita gerar vários alertas iguais para a mesma sequência de ataques."""
        cur = self._cursor()
        limite = datetime.now() - timedelta(minutes=minutos)
        cur.execute(
            """SELECT COUNT(*) AS total FROM alertas
                WHERE area_id = %s AND resolvido = FALSE AND data_hora >= %s""",
            (area_id, limite),
        )
        return cur.fetchone()["total"] > 0

    def listar_alertas(self, apenas_abertos=True):
        sql = """SELECT al.id, al.data_hora, al.tipo, al.descricao,
                        COALESCE(a.nome, '-') AS area, al.resolvido
                   FROM alertas al LEFT JOIN areas a ON a.id = al.area_id"""
        if apenas_abertos:
            sql += " WHERE al.resolvido = FALSE"
        sql += " ORDER BY al.data_hora DESC"
        cur = self._cursor()
        cur.execute(sql)
        return cur.fetchall()

    def resolver_alerta(self, alerta_id):
        cur = self._cursor()
        cur.execute("UPDATE alertas SET resolvido = TRUE WHERE id = %s", (alerta_id,))