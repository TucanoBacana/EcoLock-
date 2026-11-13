"""
EcoLock - Regras de controle de acesso por nível de permissão.

    Nível 1  Acesso concedido a indivíduos com permissão geral.
    Nível 2  Acesso restrito aos diretores de divisões específicas.
    Nível 3  Acesso exclusivo ao ministro do Meio Ambiente.

Cada área do cofre exige um nível mínimo. Um usuário entra em uma área
quando o seu nível é maior ou igual ao nível exigido. As áreas de nível 2
pertencem a uma divisão específica: um diretor só entra na área da sua
própria divisão (o ministro, nível 3, entra em todas). Toda decisão é
registrada no histórico e tentativas repetidas negadas geram alerta.
"""

from dataclasses import dataclass

import config


@dataclass
class Decisao:
    permitido: bool
    motivo: str
    usuario: dict | None = None
    alerta_gerado: bool = False


class ControleAcesso:

    def __init__(self, banco):
        self.banco = banco

    def decidir(self, area: dict, usuario_id, distancia=None, prova_vida_ok=True,
                motivo_falha=None) -> Decisao:
        """
        Aplica as regras na ordem abaixo e registra o resultado:
          1. houve falha antes do reconhecimento (tempo esgotado, foto etc.)?
          2. o rosto pertence a alguém cadastrado?
          3. o usuário está ativo?
          4. a prova de vida foi confirmada?
          5. o nível do usuário é suficiente para a área?
          6. se for diretor (nível 2) em área de divisão, a divisão é a dele?
        """
        usuario = self.banco.buscar_usuario(usuario_id) if usuario_id else None

        if motivo_falha:
            decisao = Decisao(False, motivo_falha, usuario)
        elif usuario is None:
            decisao = Decisao(False, "Rosto não reconhecido")
        elif not usuario["ativo"]:
            decisao = Decisao(False, "Usuário desativado", usuario)
        elif not prova_vida_ok:
            decisao = Decisao(False, "Prova de vida não confirmada (possível foto)", usuario)
        elif usuario["nivel_id"] < area["nivel_minimo"]:
            decisao = Decisao(
                False,
                f"Nível insuficiente (possui {usuario['nivel_id']}, exige {area['nivel_minimo']})",
                usuario,
            )
        elif (area.get("divisao") and usuario["nivel_id"] == 2
              and usuario.get("divisao") != area["divisao"]):
            decisao = Decisao(
                False,
                f"Diretor de outra divisão ({usuario.get('divisao') or 'sem divisão'})",
                usuario,
            )
        else:
            decisao = Decisao(True, "Acesso autorizado", usuario)

        self.banco.registrar_acesso(
            usuario["id"] if usuario else None, area["id"],
            decisao.permitido, decisao.motivo, distancia,
        )
        if not decisao.permitido:
            decisao.alerta_gerado = self._verificar_alerta(area)
        return decisao

    def _verificar_alerta(self, area) -> bool:
        """Gera um alerta quando há muitas negações seguidas na mesma área."""
        negacoes = self.banco.contar_negacoes_recentes(area["id"], config.JANELA_ALERTA_MINUTOS)
        if negacoes < config.MAX_NEGACOES:
            return False
        if self.banco.alerta_aberto_recente(area["id"], config.JANELA_ALERTA_MINUTOS):
            return False
        self.banco.registrar_alerta(
            "TENTATIVAS_REPETIDAS",
            f"{negacoes} acessos negados em {config.JANELA_ALERTA_MINUTOS} minutos "
            f"na área '{area['nome']}'",
            area["id"],
        )
        return True