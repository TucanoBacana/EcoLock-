"""
EcoLock - Extração de características em processos paralelos.

Gerar o vetor de 128 dimensões é a etapa mais pesada do sistema (centenas
de milissegundos por rosto em CPU). Como a biblioteca dlib não libera o
interpretador Python enquanto calcula, rodar essa etapa na mesma linha de
execução da interface faria a tela congelar a cada quadro.

Por isso a extração roda em processos separados (multiprocessing). A
interface envia o quadro e continua exibindo a câmera normalmente; o vetor
volta pela fila de resultados assim que fica pronto.
"""

import multiprocessing as mp
import queue

PRONTO = "PRONTO"


def _trabalhador(entrada, saida):
    """Executado em um processo separado: carrega o modelo uma vez e atende pedidos."""
    import face_recognition  # importado aqui para carregar o modelo só no processo filho

    saida.put((PRONTO, None))
    while True:
        pedido = entrada.get()
        if pedido is None:          # sinal de encerramento
            break
        etiqueta, imagem_rgb, caixa = pedido
        try:
            vetores = face_recognition.face_encodings(imagem_rgb, known_face_locations=[caixa],
                                                      num_jitters=1, model="small")
            saida.put((etiqueta, vetores[0] if vetores else None))
        except Exception:
            saida.put((etiqueta, None))


class ExtratorParalelo:
    """Distribui pedidos de extração entre N processos trabalhadores."""

    def __init__(self, processos: int = 2):
        self.quantidade = max(1, processos)
        self.entrada = mp.Queue()
        self.saida = mp.Queue()
        self.processos = []
        self.pendentes = 0
        self.prontos = 0

    @property
    def pronto(self) -> bool:
        return self.prontos > 0

    def iniciar(self):
        for _ in range(self.quantidade):
            p = mp.Process(target=_trabalhador, args=(self.entrada, self.saida), daemon=True)
            p.start()
            self.processos.append(p)

    def livre(self) -> bool:
        return self.pendentes < self.quantidade

    def enviar(self, etiqueta, imagem_rgb, caixa) -> bool:
        """Envia um rosto para extração se houver processo livre. Não bloqueia."""
        if not self.livre():
            return False
        self.entrada.put((etiqueta, imagem_rgb, tuple(int(v) for v in caixa)))
        self.pendentes += 1
        return True

    def coletar(self):
        """Retorna a lista de (etiqueta, vetor) já calculados, sem esperar."""
        resultados = []
        while True:
            try:
                etiqueta, vetor = self.saida.get_nowait()
            except queue.Empty:
                break
            if etiqueta == PRONTO:
                self.prontos += 1
                continue
            self.pendentes = max(0, self.pendentes - 1)
            resultados.append((etiqueta, vetor))
        return resultados

    def encerrar(self):
        for _ in self.processos:
            self.entrada.put(None)
        for p in self.processos:
            p.join(timeout=2)
            if p.is_alive():
                p.terminate()