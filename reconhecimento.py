"""
EcoLock - Fase 5: reconhecimento facial.

Compara o vetor de 128 dimensões extraído da câmera com os vetores
cadastrados no banco e decide a qual usuário o rosto pertence.
"""

from collections import deque
from dataclasses import dataclass

import numpy as np

import config


@dataclass
class Identificacao:
    usuario_id: int | None    # None quando o rosto não pertence a ninguém cadastrado
    distancia: float          # distância euclidiana até o rosto mais parecido
    confianca: float          # 0 a 100%, derivada da distância (apenas para exibição)


class Reconhecedor:
    """Mantém os vetores cadastrados em memória e identifica rostos."""

    def __init__(self, banco):
        self.banco = banco
        self.ids = []
        self.vetores = np.empty((0, 128))
        self.recarregar()

    def recarregar(self):
        """Lê novamente os vetores do banco (chamado após cadastro ou exclusão)."""
        ids, vetores = self.banco.carregar_vetores_ativos()
        self.ids = ids
        self.vetores = np.vstack(vetores) if vetores else np.empty((0, 128))

    @property
    def total_cadastrados(self):
        return len(set(self.ids))

    def identificar(self, vetor: np.ndarray) -> Identificacao:
        """
        Calcula a distância euclidiana entre o vetor capturado e todos os vetores
        do banco. O menor valor indica o rosto mais parecido; se ele estiver
        abaixo da TOLERANCIA, a identidade é aceita.
        """
        if len(self.vetores) == 0:
            return Identificacao(None, 1.0, 0.0)

        distancias = np.linalg.norm(self.vetores - vetor, axis=1)
        indice = int(np.argmin(distancias))
        menor = float(distancias[indice])
        confianca = max(0.0, (1.0 - menor / (config.TOLERANCIA * 2))) * 100

        if menor <= config.TOLERANCIA:
            return Identificacao(self.ids[indice], menor, confianca)
        return Identificacao(None, menor, confianca)


class ConfirmadorIdentidade:
    """
    Só confirma uma identidade quando ela aparece em N quadros seguidos.
    Isso evita que um único quadro com erro libere o acesso por engano.
    """

    def __init__(self, quadros=config.QUADROS_CONFIRMACAO):
        self.historico = deque(maxlen=quadros)

    def adicionar(self, identificacao: Identificacao):
        self.historico.append(identificacao.usuario_id)

    def confirmado(self):
        """Retorna o id confirmado, 'DESCONHECIDO' ou None (ainda indefinido)."""
        if len(self.historico) < self.historico.maxlen:
            return None
        primeiro = self.historico[0]
        if all(i == primeiro for i in self.historico):
            return primeiro if primeiro is not None else "DESCONHECIDO"
        return None

    def limpar(self):
        self.historico.clear()