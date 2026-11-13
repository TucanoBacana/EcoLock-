"""
EcoLock - Prova de vida (detecção de fraude com foto).

Uma foto impressa ou exibida no celular não pisca. O sistema só libera o
acesso depois de detectar pelo menos uma piscada natural, medida pela
Razão de Aspecto do Olho (EAR - Eye Aspect Ratio), proposta por
Soukupová e Čech (2016):

            |p2 - p6| + |p3 - p5|
    EAR = -------------------------
                2 * |p1 - p4|

Com o olho aberto o EAR fica em torno de 0,25 a 0,35; quando o olho
fecha, ele cai para perto de zero.
"""

import numpy as np

import config


def razao_aspecto_olho(pontos) -> float:
    """Calcula o EAR a partir dos 6 pontos de um olho (modelo de 68 marcos)."""
    p = np.asarray(pontos, dtype=np.float64)
    vertical_1 = np.linalg.norm(p[1] - p[5])
    vertical_2 = np.linalg.norm(p[2] - p[4])
    horizontal = np.linalg.norm(p[0] - p[3])
    if horizontal == 0:
        return 0.0
    return (vertical_1 + vertical_2) / (2.0 * horizontal)


class DetectorPiscada:
    """Conta piscadas ao longo dos quadros recebidos."""

    def __init__(self):
        self.quadros_fechado = 0
        self.piscadas = 0
        self.ultimo_ear = None

    def atualizar(self, marcos: dict) -> bool:
        """
        Recebe os marcos faciais de um quadro e retorna True quando a prova
        de vida já foi confirmada (ao menos uma piscada completa).
        """
        if not config.LIVENESS_ATIVO:
            return True
        if not marcos or "left_eye" not in marcos or "right_eye" not in marcos:
            return self.piscadas > 0

        ear = (razao_aspecto_olho(marcos["left_eye"]) +
               razao_aspecto_olho(marcos["right_eye"])) / 2.0
        self.ultimo_ear = ear

        if ear < config.EAR_LIMIAR:
            self.quadros_fechado += 1
        else:
            # O olho reabriu: se ficou fechado tempo suficiente, foi uma piscada
            if self.quadros_fechado >= config.EAR_QUADROS_FECHADO:
                self.piscadas += 1
            self.quadros_fechado = 0

        return self.piscadas > 0

    def reiniciar(self):
        self.__init__()