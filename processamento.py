"""
EcoLock - As cinco fases do processamento de imagens digitais.

    1. Aquisição .................. Camera.ler()
    2. Pré-processamento .......... preprocessar()
    3. Segmentação ................ segmentar_rostos()
    4. Extração de características  extrair_caracteristicas()
    5. Reconhecimento ............. reconhecimento.Reconhecedor

Este módulo cobre as quatro primeiras fases. O reconhecimento, que depende
do banco de dados, fica no módulo reconhecimento.py.
"""

import platform
from dataclasses import dataclass

import cv2
import face_recognition
import numpy as np

import config


# =============================================================================
# FASE 1 - AQUISIÇÃO
# =============================================================================
class ErroCamera(Exception):
    """Lançada quando a câmera não está disponível ou para de responder."""


class Camera:
    """Abre a webcam e entrega os quadros capturados em tempo real."""

    def __init__(self, indice: int = config.CAMERA_INDICE):
        # No Windows o backend DirectShow abre a câmera bem mais rápido
        backend = cv2.CAP_DSHOW if platform.system() == "Windows" else cv2.CAP_ANY
        self.captura = cv2.VideoCapture(indice, backend)
        if not self.captura.isOpened():
            raise ErroCamera(
                "Não foi possível acessar a câmera. Verifique se ela está conectada "
                "e se não está sendo usada por outro programa."
            )
        self.captura.set(cv2.CAP_PROP_FRAME_WIDTH, config.LARGURA_CAPTURA)
        self.captura.set(cv2.CAP_PROP_FRAME_HEIGHT, config.ALTURA_CAPTURA)
        # Mantém só o quadro mais recente no buffer, evitando atraso na imagem
        self.captura.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def ler(self) -> np.ndarray:
        """Captura um quadro (imagem BGR). Espelha a imagem para parecer um espelho."""
        ok, quadro = self.captura.read()
        if not ok or quadro is None:
            raise ErroCamera("A câmera parou de enviar imagens.")
        return cv2.flip(quadro, 1)

    def liberar(self):
        if self.captura is not None:
            self.captura.release()
            self.captura = None


# =============================================================================
# FASE 2 - PRÉ-PROCESSAMENTO
# =============================================================================
@dataclass
class QuadroProcessado:
    original: np.ndarray      # quadro BGR original (usado para exibição)
    rgb: np.ndarray           # quadro reduzido, equalizado e convertido para RGB
    cinza: np.ndarray         # versão em escala de cinza (análise de qualidade)
    brilho: float             # média de intensidade dos pixels (0 a 255)
    nitidez: float            # variância do Laplaciano (quanto maior, mais nítido)


_clahe = cv2.createCLAHE(clipLimit=config.CLAHE_LIMITE, tileGridSize=config.CLAHE_GRADE)


def preprocessar(quadro_bgr: np.ndarray) -> QuadroProcessado:
    """
    Prepara o quadro para a análise:
      a) redimensiona para acelerar o processamento;
      b) reduz ruído com um filtro Gaussiano leve;
      c) corrige a iluminação com CLAHE aplicado só no canal de luminância (L)
         do espaço de cor LAB, preservando as cores;
      d) converte de BGR (padrão do OpenCV) para RGB (padrão do face_recognition);
      e) mede brilho e nitidez para avisar o usuário quando a imagem está ruim.
    """
    pequeno = cv2.resize(quadro_bgr, (0, 0),
                         fx=config.ESCALA_PROCESSAMENTO, fy=config.ESCALA_PROCESSAMENTO)
    suave = cv2.GaussianBlur(pequeno, (3, 3), 0)

    lab = cv2.cvtColor(suave, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l_eq = _clahe.apply(l)
    equalizado = cv2.cvtColor(cv2.merge((l_eq, a, b)), cv2.COLOR_LAB2BGR)

    rgb = cv2.cvtColor(equalizado, cv2.COLOR_BGR2RGB)
    cinza = cv2.cvtColor(pequeno, cv2.COLOR_BGR2GRAY)
    brilho = float(np.mean(cinza))
    nitidez = float(cv2.Laplacian(cinza, cv2.CV_64F).var())

    return QuadroProcessado(quadro_bgr, np.ascontiguousarray(rgb), cinza, brilho, nitidez)


def avaliar_qualidade(q: QuadroProcessado):
    """Retorna uma mensagem de problema ou None quando a imagem está adequada."""
    if q.brilho < config.BRILHO_MINIMO:
        return "Ambiente muito escuro. Aproxime-se de uma fonte de luz."
    if q.brilho > config.BRILHO_MAXIMO:
        return "Imagem muito clara. Evite luz forte atrás ou sobre o rosto."
    if q.nitidez < config.NITIDEZ_MINIMA:
        return "Imagem borrada. Fique parado em frente à câmera."
    return None


# =============================================================================
# FASE 3 - SEGMENTAÇÃO
# =============================================================================
def segmentar_rostos(q: QuadroProcessado):
    """
    Localiza os rostos na imagem com o detector HOG + SVM linear do dlib.
    Retorna as caixas (topo, direita, base, esquerda) no quadro REDUZIDO,
    descartando rostos pequenos demais (pessoa muito longe da câmera).
    """
    caixas = face_recognition.face_locations(q.rgb,
                                             number_of_times_to_upsample=config.AMPLIACOES_DETECCAO,
                                             model=config.MODELO_DETECCAO)
    minimo = config.TAMANHO_MINIMO_ROSTO * config.ESCALA_PROCESSAMENTO
    return [c for c in caixas if (c[1] - c[3]) >= minimo]


def caixa_no_original(caixa):
    """Converte uma caixa do quadro reduzido para as coordenadas do quadro original."""
    fator = 1.0 / config.ESCALA_PROCESSAMENTO
    topo, direita, base, esquerda = caixa
    return int(topo * fator), int(direita * fator), int(base * fator), int(esquerda * fator)


# =============================================================================
# FASE 4 - EXTRAÇÃO DE CARACTERÍSTICAS
# =============================================================================
def extrair_caracteristicas(q: QuadroProcessado, caixa):
    """
    Gera o vetor de 128 dimensões que representa o rosto (embedding).
    Internamente o face_recognition alinha o rosto pelos 5 pontos de referência
    e o passa por uma rede neural ResNet treinada com a função de perda triplet.
    """
    vetores = face_recognition.face_encodings(q.rgb, known_face_locations=[caixa],
                                              num_jitters=1, model="small")
    return vetores[0] if vetores else None


def extrair_marcos(q: QuadroProcessado, caixa):
    """Retorna os 68 pontos de referência faciais (usados na prova de vida)."""
    marcos = face_recognition.face_landmarks(q.rgb, face_locations=[caixa], model="large")
    return marcos[0] if marcos else None


# =============================================================================
# Utilitários de desenho para a interface
# =============================================================================
VERDE = (94, 197, 34)        # BGR equivalente a #22C55E
VERMELHO = (68, 68, 239)     # BGR equivalente a #EF4444
AMARELO = (11, 158, 245)     # BGR equivalente a #F59E0B


def desenhar_caixa(quadro_bgr, caixa_original, texto, cor):
    """Desenha cantoneiras em volta do rosto e uma etiqueta com o texto."""
    topo, direita, base, esquerda = caixa_original
    lado = max(12, (direita - esquerda) // 5)
    for (x, y, dx, dy) in [(esquerda, topo, 1, 1), (direita, topo, -1, 1),
                           (esquerda, base, 1, -1), (direita, base, -1, -1)]:
        cv2.line(quadro_bgr, (x, y), (x + dx * lado, y), cor, 3, cv2.LINE_AA)
        cv2.line(quadro_bgr, (x, y), (x, y + dy * lado), cor, 3, cv2.LINE_AA)

    (largura, altura), _ = cv2.getTextSize(texto, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    x0, y0 = esquerda, max(0, topo - altura - 16)
    fundo = quadro_bgr.copy()
    cv2.rectangle(fundo, (x0, y0), (x0 + largura + 16, y0 + altura + 12), cor, cv2.FILLED)
    cv2.addWeighted(fundo, 0.85, quadro_bgr, 0.15, 0, quadro_bgr)
    cv2.putText(quadro_bgr, texto, (x0 + 8, y0 + altura + 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return quadro_bgr