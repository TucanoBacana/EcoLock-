"""
EcoLock - Configurações gerais do sistema.

Todos os parâmetros ajustáveis ficam centralizados neste arquivo para que
o comportamento do sistema possa ser calibrado sem alterar o código dos
demais módulos.
"""

# ---------------------------------------------------------------------------
# Banco de dados (MySQL rodando localmente no XAMPP)
# ---------------------------------------------------------------------------
DB_CONFIG = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "",          # padrão do XAMPP: usuário root sem senha
    "database": "ecolock",
}

# ---------------------------------------------------------------------------
# Fase 1 - Aquisição
# ---------------------------------------------------------------------------
CAMERA_INDICE = 0            # 0 = webcam padrão do computador
LARGURA_CAPTURA = 640
ALTURA_CAPTURA = 480

# ---------------------------------------------------------------------------
# Fase 2 - Pré-processamento
# ---------------------------------------------------------------------------
ESCALA_PROCESSAMENTO = 0.5   # reduz o quadro pela metade para acelerar a análise
CLAHE_LIMITE = 2.0           # limite de contraste da equalização adaptativa
CLAHE_GRADE = (8, 8)         # tamanho da grade da equalização adaptativa
BRILHO_MINIMO = 50           # abaixo disso a imagem é considerada escura demais
BRILHO_MAXIMO = 210          # acima disso a imagem é considerada estourada
NITIDEZ_MINIMA = 40.0        # variância do Laplaciano mínima (imagem borrada)

# ---------------------------------------------------------------------------
# Fase 3 - Segmentação
# ---------------------------------------------------------------------------
MODELO_DETECCAO = "hog"      # "hog" (CPU, mais rápido) ou "cnn" (exige GPU)
AMPLIACOES_DETECCAO = 0      # 0 = rápido (rosto a até ~60 cm); 1 = detecta mais longe, ~10x mais lento
TAMANHO_MINIMO_ROSTO = 60    # largura mínima do rosto, em pixels, no quadro original

# ---------------------------------------------------------------------------
# Fases 4 e 5 - Extração de características e reconhecimento
# ---------------------------------------------------------------------------
TOLERANCIA = 0.50            # distância euclidiana máxima para aceitar um rosto
QUADROS_CONFIRMACAO = 3      # reconhecimentos iguais e seguidos para confirmar a identidade
AMOSTRAS_CADASTRO = 5        # quantidade de fotos capturadas no cadastro de cada usuário
PROCESSOS_EXTRACAO = 2       # processos paralelos que geram os vetores (evita travar a tela)

# ---------------------------------------------------------------------------
# Prova de vida (detecção de fraude com foto)
# ---------------------------------------------------------------------------
LIVENESS_ATIVO = True
EAR_LIMIAR = 0.21            # razão de aspecto do olho abaixo da qual o olho está fechado
EAR_QUADROS_FECHADO = 2      # quadros seguidos com olho fechado para contar uma piscada
TEMPO_MAXIMO_TENTATIVA = 12  # segundos para concluir a verificação antes de negar o acesso

# ---------------------------------------------------------------------------
# Alertas de segurança
# ---------------------------------------------------------------------------
MAX_NEGACOES = 3             # negações dentro da janela que disparam um alerta
JANELA_ALERTA_MINUTOS = 5    # janela de tempo analisada para gerar alertas

# ---------------------------------------------------------------------------
# Divisões e administração
# ---------------------------------------------------------------------------
# Áreas de nível 2 pertencem a uma divisão: só o diretor dela pode entrar.
DIVISOES = ["Divisão de Toxinas", "Divisão de Biodiversidade"]
TEMPO_MAXIMO_CADASTRO = 30   # segundos para concluir a captura (inclui a prova de vida)
MAX_FALHAS_LOGIN = 3         # senhas erradas seguidas que geram alerta de segurança

# ---------------------------------------------------------------------------
# Relatórios
# ---------------------------------------------------------------------------
PASTA_RELATORIOS = "relatorios"