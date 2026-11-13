"""
EcoLock - Interface gráfica (CustomTkinter).

Layout com menu lateral e quatro páginas:
    Acesso ao Cofre  verificação facial em tempo real e decisão de acesso
    Cadastro         registro de novos usuários com captura do rosto
    Usuários         consulta, ativação/desativação e exclusão de usuários
    Relatórios       indicadores, histórico de acessos, exportação e alertas

A câmera é lida e exibida na linha principal da interface. A etapa pesada
(extração do vetor facial) roda em processos separados (extrator.py), para
que a imagem nunca congele durante a verificação.
"""

import time
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox, ttk

import customtkinter as ctk
import cv2
from PIL import Image, ImageTk

import autenticacao
import config
import relatorios
from controle_acesso import ControleAcesso
from extrator import ExtratorParalelo
from liveness import DetectorPiscada
from processamento import (AMARELO, VERDE, VERMELHO, Camera, ErroCamera, avaliar_qualidade,
                           caixa_no_original, desenhar_caixa, extrair_marcos, preprocessar,
                           segmentar_rostos)
from reconhecimento import ConfirmadorIdentidade, Reconhecedor

# ------------------------------------------------------------------ paleta
FUNDO = "#0B1410"
MENU = "#0F1C16"
CARTAO = "#14251D"
CARTAO_2 = "#1A3025"
BORDA = "#21402F"
TEXTO = "#E6F2EA"
SUAVE = "#8FA89A"
VERDE_UI = "#22C55E"
VERDE_ESCURO = "#15803D"
VERMELHO_UI = "#EF4444"
AMARELO_UI = "#F59E0B"
AZUL_UI = "#38BDF8"
NEUTRO = "#334155"

NOMES_NIVEIS = {1: "Nível 1 · Geral", 2: "Nível 2 · Diretor", 3: "Nível 3 · Ministro"}
PAGINAS = [("acesso", "Acesso ao Cofre"), ("cadastro", "Cadastro"),
           ("usuarios", "Usuários"), ("relatorios", "Relatórios e Alertas")]
PAGINAS_ADMIN = ("cadastro", "usuarios", "relatorios")   # exigem login de administrador
SEM_DIVISAO = "Nenhuma"


class DialogoAdmin(ctk.CTkToplevel):
    """Janela modal de login (ou de criação do primeiro administrador)."""

    def __init__(self, pai, criar: bool):
        super().__init__(pai, fg_color=CARTAO)
        self.resultado = None
        self.criar = criar
        self.title("Criar administrador" if criar else "Área administrativa")
        altura = 400 if criar else 330
        pai.update_idletasks()     # centraliza o diálogo sobre a janela principal
        x = pai.winfo_rootx() + (pai.winfo_width() - 380) // 2
        y = pai.winfo_rooty() + (pai.winfo_height() - altura) // 2
        self.geometry(f"380x{altura}+{max(x, 0)}+{max(y, 0)}")
        self.resizable(False, False)
        self.transient(pai)

        ctk.CTkLabel(self, text="Primeiro acesso" if criar else "Acesso restrito",
                     font=fonte(18, "bold"), text_color=TEXTO).pack(anchor="w", padx=24, pady=(22, 0))
        ctk.CTkLabel(self, font=fonte(12), text_color=SUAVE, justify="left", wraplength=330,
                     text=("Crie o administrador do EcoLock. Só ele poderá cadastrar, excluir e auditar."
                           if criar else "Cadastro, usuários e relatórios exigem login de administrador.")
                     ).pack(anchor="w", padx=24, pady=(2, 10))
        self.usuario = self._campo("Usuário", False)
        self.senha = self._campo("Senha", True)
        self.confirmacao = self._campo("Confirmar senha", True) if criar else None
        ctk.CTkButton(self, text="Criar e entrar" if criar else "Entrar", height=42, corner_radius=10,
                      font=fonte(14, "bold"), fg_color=VERDE_UI, hover_color=VERDE_ESCURO,
                      text_color="#04210F", command=self._confirmar).pack(fill="x", padx=24, pady=18)
        self.bind("<Return>", lambda _e: self._confirmar())
        self.after(150, self._focar)

    def _campo(self, rotulo, oculto):
        ctk.CTkLabel(self, text=rotulo, font=fonte(12), text_color=SUAVE).pack(anchor="w", padx=24)
        entrada = ctk.CTkEntry(self, height=36, corner_radius=10, show="•" if oculto else "",
                               fg_color=CARTAO_2, border_color=BORDA, font=fonte(13))
        entrada.pack(fill="x", padx=24, pady=(2, 8))
        return entrada

    def _focar(self):
        self.lift()
        self.grab_set()          # bloqueia a janela principal até fechar este diálogo
        self.usuario.focus_set()

    def _confirmar(self):
        usuario, senha = self.usuario.get().strip(), self.senha.get()
        if not usuario or not senha:
            messagebox.showwarning("EcoLock", "Informe usuário e senha.", parent=self)
            return
        if self.criar:
            problema = autenticacao.validar_senha_nova(senha)
            if problema or senha != self.confirmacao.get():
                messagebox.showwarning("EcoLock", problema or "As senhas não conferem.", parent=self)
                return
        self.resultado = (usuario, senha)
        self.destroy()


def fonte(tamanho=13, peso="normal"):
    return ctk.CTkFont(family="Segoe UI", size=tamanho, weight=peso)


class AplicacaoEcoLock(ctk.CTk):

    def __init__(self, banco):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("green")
        super().__init__(fg_color=FUNDO)
        self.title("EcoLock · Controle de Acesso Biométrico · Ministério do Meio Ambiente")
        self.geometry("1280x780")
        self.minsize(1120, 720)

        self.banco = banco
        self.reconhecedor = Reconhecedor(banco)
        self.controle = ControleAcesso(banco)
        self.areas = banco.listar_areas()
        self.extrator = ExtratorParalelo(config.PROCESSOS_EXTRACAO)
        self.extrator.iniciar()

        self.camera = None
        self.pagina = "acesso"
        self.modo = "OCIOSO"          # OCIOSO | VERIFICANDO | RESULTADO | CADASTRO
        self.sessao = 0               # identifica os pedidos enviados ao extrator
        self.confirmador = ConfirmadorIdentidade()
        self.detector_piscada = DetectorPiscada()
        self.inicio_tentativa = 0.0
        self.ultima_identificacao = None
        self.amostras_cadastro = []
        self.ultima_amostra = 0.0
        self._ultima_tentativa_camera = 0.0
        self._foto_tk = None
        self.admin = None             # nome do administrador logado (None = área bloqueada)
        self.falhas_login = 0
        self.dados_cadastro = None
        self.inicio_cadastro = 0.0

        self._estilo_tabelas()
        self._montar_menu()
        self.conteudo = ctk.CTkFrame(self, fg_color=FUNDO, corner_radius=0)
        self.conteudo.pack(side="left", fill="both", expand=True)
        self.paginas = {
            "acesso": self._pagina_acesso(),
            "cadastro": self._pagina_cadastro(),
            "usuarios": self._pagina_usuarios(),
            "relatorios": self._pagina_relatorios(),
        }
        self.mostrar_pagina("acesso")
        self.protocol("WM_DELETE_WINDOW", self.encerrar)
        self._timer_camera = self.after(100, self._ciclo_camera)
        self._timer_status = self.after(500, self._atualizar_status)

    # ================================================================ estilo
    def _estilo_tabelas(self):
        estilo = ttk.Style(self)
        estilo.theme_use("clam")
        estilo.configure("Eco.Treeview", background=CARTAO, fieldbackground=CARTAO,
                         foreground=TEXTO, rowheight=32, borderwidth=0, font=("Segoe UI", 10))
        estilo.configure("Eco.Treeview.Heading", background=CARTAO_2, foreground=SUAVE,
                         relief="flat", borderwidth=0, font=("Segoe UI", 10, "bold"), padding=8)
        estilo.map("Eco.Treeview", background=[("selected", VERDE_ESCURO)],
                   foreground=[("selected", "white")])
        estilo.map("Eco.Treeview.Heading", background=[("active", BORDA)])
        estilo.layout("Eco.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        estilo.configure("Eco.Vertical.TScrollbar", background=CARTAO_2, troughcolor=CARTAO,
                         borderwidth=0, arrowcolor=SUAVE)

    def _cartao(self, pai, **kw):
        return ctk.CTkFrame(pai, fg_color=CARTAO, corner_radius=16, border_width=1,
                            border_color=BORDA, **kw)

    def _titulo_pagina(self, pai, titulo, subtitulo):
        topo = ctk.CTkFrame(pai, fg_color="transparent")
        topo.pack(fill="x", padx=28, pady=(24, 12))
        ctk.CTkLabel(topo, text=titulo, font=fonte(24, "bold"), text_color=TEXTO).pack(anchor="w")
        ctk.CTkLabel(topo, text=subtitulo, font=fonte(13), text_color=SUAVE).pack(anchor="w")
        return topo

    # ================================================================== menu
    def _montar_menu(self):
        menu = ctk.CTkFrame(self, fg_color=MENU, corner_radius=0, width=240)
        menu.pack(side="left", fill="y")
        menu.pack_propagate(False)

        marca = ctk.CTkFrame(menu, fg_color="transparent")
        marca.pack(fill="x", padx=20, pady=(26, 30))
        icone = tk.Canvas(marca, width=40, height=40, bg=MENU, highlightthickness=0)
        icone.create_oval(2, 2, 38, 38, fill=VERDE_ESCURO, outline="")
        icone.create_rectangle(13, 19, 27, 30, fill="white", outline="")
        icone.create_arc(14, 10, 26, 26, start=0, extent=180, style="arc", outline="white", width=3)
        icone.pack(side="left")
        textos = ctk.CTkFrame(marca, fg_color="transparent")
        textos.pack(side="left", padx=10)
        ctk.CTkLabel(textos, text="EcoLock", font=fonte(20, "bold"), text_color=TEXTO).pack(anchor="w")
        ctk.CTkLabel(textos, text="Acesso biométrico", font=fonte(11), text_color=SUAVE).pack(anchor="w")

        self.botoes_menu = {}
        for chave, rotulo in PAGINAS:
            botao = ctk.CTkButton(menu, text=rotulo, anchor="w", height=42, corner_radius=10,
                                  font=fonte(14), fg_color="transparent", text_color=SUAVE,
                                  hover_color=CARTAO_2, command=lambda c=chave: self.mostrar_pagina(c))
            botao.pack(fill="x", padx=14, pady=3)
            self.botoes_menu[chave] = botao

        rodape = ctk.CTkFrame(menu, fg_color=CARTAO, corner_radius=12)
        rodape.pack(side="bottom", fill="x", padx=14, pady=18)
        ctk.CTkLabel(rodape, text="STATUS DO SISTEMA", font=fonte(10, "bold"),
                     text_color=SUAVE).pack(anchor="w", padx=14, pady=(12, 4))
        self.status = {}
        for chave, rotulo in [("banco", "Banco de dados"), ("camera", "Câmera"),
                              ("motor", "Motor de reconhecimento"), ("usuarios", "Usuários ativos")]:
            linha = ctk.CTkFrame(rodape, fg_color="transparent")
            linha.pack(fill="x", padx=14, pady=2)
            ponto = ctk.CTkLabel(linha, text="●", font=fonte(12), text_color=NEUTRO, width=14)
            ponto.pack(side="left")
            valor = ctk.CTkLabel(linha, text=rotulo, font=fonte(12), text_color=TEXTO, anchor="w")
            valor.pack(side="left", padx=6)
            self.status[chave] = (ponto, valor, rotulo)
        ctk.CTkLabel(rodape, text="Operação 100% local · LGPD", font=fonte(10),
                     text_color=SUAVE).pack(anchor="w", padx=14, pady=(6, 12))

        caixa_admin = ctk.CTkFrame(menu, fg_color=CARTAO, corner_radius=12)
        caixa_admin.pack(side="bottom", fill="x", padx=14)
        ctk.CTkLabel(caixa_admin, text="ADMINISTRAÇÃO", font=fonte(10, "bold"),
                     text_color=SUAVE).pack(anchor="w", padx=14, pady=(12, 2))
        self.lbl_admin = ctk.CTkLabel(caixa_admin, text="Bloqueada", font=fonte(12),
                                      text_color=AMARELO_UI, anchor="w")
        self.lbl_admin.pack(anchor="w", padx=14)
        self.btn_bloquear = ctk.CTkButton(caixa_admin, text="Bloquear agora", height=30,
                                          corner_radius=8, font=fonte(12), fg_color=CARTAO_2,
                                          hover_color=BORDA, command=self.bloquear_admin)
        ctk.CTkLabel(caixa_admin, text="", height=6).pack()

    def _definir_status(self, chave, cor, texto=None):
        ponto, valor, rotulo = self.status[chave]
        ponto.configure(text_color=cor)
        valor.configure(text=texto or rotulo)

    def _atualizar_status(self):
        self._definir_status("banco", VERDE_UI if self.banco.conexao.is_connected() else VERMELHO_UI)
        self._definir_status("camera", VERDE_UI if self.camera is not None else NEUTRO,
                             "Câmera ativa" if self.camera is not None else "Câmera em espera")
        self._definir_status("motor", VERDE_UI if self.extrator.pronto else AMARELO_UI,
                             "Reconhecimento pronto" if self.extrator.pronto else "Carregando modelo...")
        self._definir_status("usuarios", AZUL_UI,
                             f"{self.reconhecedor.total_cadastrados} usuários com biometria")
        self._timer_status = self.after(1000, self._atualizar_status)

    # ======================================================= administração
    def _autenticar(self) -> bool:
        """
        Exige login de administrador para as páginas administrativas. Sem isso,
        qualquer pessoa diante do terminal poderia se cadastrar como ministro.
        """
        criar = not self.banco.tem_administrador()
        dialogo = DialogoAdmin(self, criar)
        self.wait_window(dialogo)
        if dialogo.resultado is None:
            return False
        usuario, senha = dialogo.resultado
        if criar:
            self.banco.criar_administrador(usuario, *autenticacao.gerar_hash(senha))
            messagebox.showinfo("EcoLock", f"Administrador '{usuario}' criado.")
        else:
            admin = self.banco.buscar_administrador(usuario)
            if admin is None or not autenticacao.conferir_senha(senha, admin["sal"], admin["senha_hash"]):
                self.falhas_login += 1
                if self.falhas_login >= config.MAX_FALHAS_LOGIN:
                    self.falhas_login = 0
                    self.banco.registrar_alerta("LOGIN_ADMIN_FALHO",
                                                f"{config.MAX_FALHAS_LOGIN} senhas de administrador "
                                                f"erradas seguidas (usuário informado: '{usuario}')")
                    self.bell()
                messagebox.showerror("EcoLock", "Usuário ou senha inválidos.")
                return False
        self.falhas_login = 0
        self.admin = usuario
        self.lbl_admin.configure(text=f"Liberada para {usuario}", text_color=VERDE_UI)
        self.btn_bloquear.pack(fill="x", padx=14, pady=(6, 0))
        return True

    def bloquear_admin(self):
        """Encerra a sessão do administrador e volta para a página de acesso."""
        self.admin = None
        self.lbl_admin.configure(text="Bloqueada", text_color=AMARELO_UI)
        self.btn_bloquear.pack_forget()
        if self.pagina in PAGINAS_ADMIN and self.modo == "OCIOSO":
            self.mostrar_pagina("acesso")

    def mostrar_pagina(self, chave):
        if self.modo in ("VERIFICANDO", "CADASTRO") and chave != self.pagina:
            messagebox.showinfo("EcoLock", "Aguarde a conclusão da operação em andamento.")
            return
        if chave in PAGINAS_ADMIN and self.admin is None and not self._autenticar():
            return
        if chave == "acesso" and self.admin is not None:
            self.bloquear_admin()     # voltar à porta encerra a sessão administrativa
        for frame in self.paginas.values():
            frame.pack_forget()
        self.paginas[chave].pack(fill="both", expand=True)
        for c, b in self.botoes_menu.items():
            ativo = c == chave
            b.configure(fg_color=CARTAO_2 if ativo else "transparent",
                        text_color=TEXTO if ativo else SUAVE,
                        font=fonte(14, "bold" if ativo else "normal"))
        self.pagina = chave
        if chave in ("usuarios", "relatorios") and self.camera is not None:
            self.camera.liberar()     # libera a webcam fora das páginas que a utilizam
            self.camera = None
        if chave == "usuarios":
            self.carregar_usuarios()
        elif chave == "relatorios":
            self.carregar_relatorio()

    # ======================================================== página: acesso
    def _pagina_acesso(self):
        pagina = ctk.CTkFrame(self.conteudo, fg_color=FUNDO)
        self._titulo_pagina(pagina, "Acesso ao Cofre",
                            "Verificação facial em tempo real com prova de vida")
        corpo = ctk.CTkFrame(pagina, fg_color="transparent")
        corpo.pack(fill="both", expand=True, padx=28, pady=(0, 24))

        cartao_video = self._cartao(corpo)
        cartao_video.pack(side="left", fill="both", expand=True)
        self.video_acesso = tk.Label(cartao_video, bg="#05090A", bd=0)
        self.video_acesso.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        self.lbl_instrucao = ctk.CTkLabel(cartao_video, text="Selecione a área e clique em Solicitar acesso",
                                          font=fonte(14), text_color=TEXTO)
        self.lbl_instrucao.pack(pady=(4, 4))
        self.barra_tempo = ctk.CTkProgressBar(cartao_video, height=6, corner_radius=3,
                                              progress_color=VERDE_UI, fg_color=CARTAO_2)
        self.barra_tempo.set(0)
        self.barra_tempo.pack(fill="x", padx=16, pady=(0, 14))

        lateral = ctk.CTkFrame(corpo, fg_color="transparent", width=340)
        lateral.pack(side="right", fill="y", padx=(18, 0))
        lateral.pack_propagate(False)

        solicitar = self._cartao(lateral)
        solicitar.pack(fill="x")
        ctk.CTkLabel(solicitar, text="Área solicitada", font=fonte(13, "bold"),
                     text_color=TEXTO).pack(anchor="w", padx=18, pady=(16, 6))
        self.opcoes_area = [a["nome"] for a in self.areas]
        self.cmb_area = ctk.CTkOptionMenu(solicitar, values=self.opcoes_area, height=38,
                                          font=fonte(13), fg_color=CARTAO_2, button_color=BORDA,
                                          button_hover_color=VERDE_ESCURO, dropdown_font=fonte(13),
                                          command=lambda _v: self._atualizar_exigencia())
        self.cmb_area.pack(fill="x", padx=18)
        self.lbl_exigencia = ctk.CTkLabel(solicitar, text="", font=fonte(12), text_color=SUAVE)
        self.lbl_exigencia.pack(anchor="w", padx=18, pady=(6, 0))
        self.btn_solicitar = ctk.CTkButton(solicitar, text="Solicitar acesso", height=46,
                                           corner_radius=12, font=fonte(15, "bold"),
                                           fg_color=VERDE_UI, hover_color=VERDE_ESCURO,
                                           text_color="#04210F", command=self.iniciar_verificacao)
        self.btn_solicitar.pack(fill="x", padx=18, pady=(14, 18))
        self._atualizar_exigencia()

        self.cartao_resultado = ctk.CTkFrame(lateral, fg_color=NEUTRO, corner_radius=16)
        self.cartao_resultado.pack(fill="x", pady=14)
        self.lbl_resultado = ctk.CTkLabel(self.cartao_resultado, text="AGUARDANDO",
                                          font=fonte(22, "bold"), text_color="white")
        self.lbl_resultado.pack(pady=(16, 0))
        self.lbl_resultado_sub = ctk.CTkLabel(self.cartao_resultado, text="Nenhuma verificação em andamento",
                                              font=fonte(12), text_color="#E5E7EB")
        self.lbl_resultado_sub.pack(pady=(0, 16))

        detalhes = self._cartao(lateral)
        detalhes.pack(fill="x")
        self.detalhes = {}
        for chave in ("Usuário", "Permissão", "Área", "Motivo", "Horário"):
            linha = ctk.CTkFrame(detalhes, fg_color="transparent")
            linha.pack(fill="x", padx=18, pady=3)
            ctk.CTkLabel(linha, text=chave, font=fonte(12), text_color=SUAVE, width=80,
                         anchor="w").pack(side="left")
            valor = ctk.CTkLabel(linha, text="—", font=fonte(12, "bold"), text_color=TEXTO,
                                 anchor="w", justify="left", wraplength=210)
            valor.pack(side="left", fill="x")
            self.detalhes[chave] = valor
        ctk.CTkFrame(detalhes, height=1, fg_color=BORDA).pack(fill="x", padx=18, pady=10)

        ctk.CTkLabel(detalhes, text="Etapas da verificação", font=fonte(13, "bold"),
                     text_color=TEXTO).pack(anchor="w", padx=18, pady=(0, 4))
        self.etapas = {}
        for chave, texto in [("rosto", "Rosto detectado"), ("identidade", "Identidade confirmada"),
                             ("vida", "Prova de vida (piscar)"), ("nivel", "Nível de permissão")]:
            linha = ctk.CTkFrame(detalhes, fg_color="transparent")
            linha.pack(fill="x", padx=18, pady=2)
            marca = ctk.CTkLabel(linha, text="○", font=fonte(15), text_color=SUAVE, width=20)
            marca.pack(side="left")
            rotulo = ctk.CTkLabel(linha, text=texto, font=fonte(12), text_color=SUAVE)
            rotulo.pack(side="left", padx=6)
            self.etapas[chave] = (marca, rotulo)
        ctk.CTkLabel(detalhes, text="", height=8).pack()
        return pagina

    def _area_selecionada(self):
        return self.areas[self.opcoes_area.index(self.cmb_area.get())]

    def _atualizar_exigencia(self):
        area = self._area_selecionada()
        if area.get("divisao"):
            texto = f"Exige o diretor da {area['divisao']} ou o ministro"
        else:
            texto = f"Exige {NOMES_NIVEIS[area['nivel_minimo']]} ou superior"
        self.lbl_exigencia.configure(text=texto)

    # ====================================================== página: cadastro
    def _pagina_cadastro(self):
        pagina = ctk.CTkFrame(self.conteudo, fg_color=FUNDO)
        self._titulo_pagina(pagina, "Cadastro de usuário",
                            "Registre uma pessoa autorizada e capture sua biometria facial")
        corpo = ctk.CTkFrame(pagina, fg_color="transparent")
        corpo.pack(fill="both", expand=True, padx=28, pady=(0, 24))

        cartao_video = self._cartao(corpo)
        cartao_video.pack(side="left", fill="both", expand=True)
        self.video_cadastro = tk.Label(cartao_video, bg="#05090A", bd=0)
        self.video_cadastro.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        self.lbl_progresso = ctk.CTkLabel(cartao_video, text="Preencha os dados ao lado para começar",
                                          font=fonte(14), text_color=TEXTO)
        self.lbl_progresso.pack(pady=4)
        self.barra_amostras = ctk.CTkProgressBar(cartao_video, height=6, corner_radius=3,
                                                 progress_color=VERDE_UI, fg_color=CARTAO_2)
        self.barra_amostras.set(0)
        self.barra_amostras.pack(fill="x", padx=16, pady=(0, 14))

        form = self._cartao(corpo, width=360)
        form.pack(side="right", fill="y", padx=(18, 0))
        form.pack_propagate(False)
        ctk.CTkLabel(form, text="Dados do usuário", font=fonte(15, "bold"),
                     text_color=TEXTO).pack(anchor="w", padx=20, pady=(18, 8))
        self.campos = {}
        for chave, rotulo, exemplo in [("nome", "Nome completo", "Ex.: Maria Souza"),
                                       ("cargo", "Cargo", "Ex.: Diretora de Divisão")]:
            ctk.CTkLabel(form, text=rotulo, font=fonte(12), text_color=SUAVE).pack(
                anchor="w", padx=20, pady=(8, 2))
            entrada = ctk.CTkEntry(form, height=38, corner_radius=10, placeholder_text=exemplo,
                                   fg_color=CARTAO_2, border_color=BORDA, font=fonte(13))
            entrada.pack(fill="x", padx=20)
            self.campos[chave] = entrada

        ctk.CTkLabel(form, text="Nível de permissão", font=fonte(12), text_color=SUAVE).pack(
            anchor="w", padx=20, pady=(8, 2))
        self.seg_nivel = ctk.CTkSegmentedButton(form, values=["Nível 1", "Nível 2", "Nível 3"],
                                                height=36, font=fonte(12), selected_color=VERDE_ESCURO,
                                                selected_hover_color=VERDE_ESCURO,
                                                unselected_color=CARTAO_2, fg_color=CARTAO_2)
        self.seg_nivel.set("Nível 1")
        self.seg_nivel.pack(fill="x", padx=20)

        ctk.CTkLabel(form, text="Divisão (obrigatória para diretores)", font=fonte(12),
                     text_color=SUAVE).pack(anchor="w", padx=20, pady=(8, 2))
        self.cmb_divisao = ctk.CTkOptionMenu(form, values=[SEM_DIVISAO] + config.DIVISOES, height=36,
                                             font=fonte(13), fg_color=CARTAO_2, button_color=BORDA,
                                             button_hover_color=VERDE_ESCURO, dropdown_font=fonte(13))
        self.cmb_divisao.set(SEM_DIVISAO)
        self.cmb_divisao.pack(fill="x", padx=20)

        self.btn_capturar = ctk.CTkButton(form, text="Capturar rosto e salvar", height=46,
                                          corner_radius=12, font=fonte(14, "bold"),
                                          fg_color=VERDE_UI, hover_color=VERDE_ESCURO,
                                          text_color="#04210F", command=self.iniciar_cadastro)
        self.btn_capturar.pack(fill="x", padx=20, pady=20)

        aviso = ctk.CTkFrame(form, fg_color=CARTAO_2, corner_radius=12)
        aviso.pack(fill="x", padx=20)
        ctk.CTkLabel(aviso, justify="left", wraplength=290, font=fonte(11), text_color=SUAVE,
                     text=("Primeiro a pessoa pisca (prova de vida: fotos não são aceitas). "
                           f"Depois o sistema captura {config.AMOSTRAS_CADASTRO} amostras do rosto; "
                           "mova levemente a cabeça entre as capturas.\n\n"
                           "Somente vetores numéricos são armazenados. Nenhuma foto é guardada, "
                           "em conformidade com a LGPD.")).pack(padx=14, pady=12)
        return pagina

    # ====================================================== página: usuários
    def _pagina_usuarios(self):
        pagina = ctk.CTkFrame(self.conteudo, fg_color=FUNDO)
        topo = self._titulo_pagina(pagina, "Usuários", "Pessoas autorizadas e seus níveis de acesso")
        barra = ctk.CTkFrame(topo, fg_color="transparent")
        barra.place(relx=1.0, rely=0.5, anchor="e")
        self._botao_secundario(barra, "Atualizar", self.carregar_usuarios).pack(side="left", padx=4)
        self._botao_secundario(barra, "Ativar / Desativar", self.alternar_status).pack(side="left", padx=4)
        ctk.CTkButton(barra, text="Excluir usuário", height=38, corner_radius=10, font=fonte(13),
                      fg_color="#7F1D1D", hover_color=VERMELHO_UI,
                      command=self.excluir_usuario).pack(side="left", padx=4)

        cartao = self._cartao(pagina)
        cartao.pack(fill="both", expand=True, padx=28, pady=(0, 24))
        self.tabela_usuarios = self._criar_tabela(
            cartao, ("id", "nome", "cargo", "divisao", "nivel", "status", "amostras", "criado"),
            ("ID", "Nome", "Cargo", "Divisão", "Nível", "Status", "Amostras", "Cadastrado em"),
            (50, 240, 170, 160, 150, 90, 80, 140))
        self.tabela_usuarios.tag_configure("inativo", foreground=SUAVE)
        return pagina

    def _botao_secundario(self, pai, texto, comando):
        return ctk.CTkButton(pai, text=texto, height=38, corner_radius=10, font=fonte(13),
                             fg_color=CARTAO_2, hover_color=BORDA, border_width=1,
                             border_color=BORDA, command=comando)

    # ==================================================== página: relatórios
    def _pagina_relatorios(self):
        pagina = ctk.CTkFrame(self.conteudo, fg_color=FUNDO)
        topo = self._titulo_pagina(pagina, "Relatórios e Alertas", "Auditoria de todas as tentativas de acesso")
        filtros = ctk.CTkFrame(topo, fg_color="transparent")
        filtros.place(relx=1.0, rely=0.5, anchor="e")
        self.cmb_periodo = ctk.CTkOptionMenu(filtros, values=["Hoje", "Últimos 7 dias", "Últimos 30 dias", "Tudo"],
                                             width=150, height=38, fg_color=CARTAO_2, button_color=BORDA,
                                             font=fonte(13), command=lambda _v: self.carregar_relatorio())
        self.cmb_periodo.set("Últimos 7 dias")
        self.cmb_periodo.pack(side="left", padx=4)
        self.cmb_resultado = ctk.CTkOptionMenu(filtros, values=["Todos", "PERMITIDO", "NEGADO"],
                                               width=130, height=38, fg_color=CARTAO_2, button_color=BORDA,
                                               font=fonte(13), command=lambda _v: self.carregar_relatorio())
        self.cmb_resultado.set("Todos")
        self.cmb_resultado.pack(side="left", padx=4)
        ctk.CTkButton(filtros, text="Exportar CSV", height=38, corner_radius=10, font=fonte(13, "bold"),
                      fg_color=VERDE_UI, hover_color=VERDE_ESCURO, text_color="#04210F",
                      command=self.exportar_relatorio).pack(side="left", padx=4)

        kpis = ctk.CTkFrame(pagina, fg_color="transparent")
        kpis.pack(fill="x", padx=28)
        self.kpis = {}
        for i, (chave, rotulo, cor) in enumerate([("total", "Tentativas", AZUL_UI),
                                                  ("permitidos", "Permitidos", VERDE_UI),
                                                  ("negados", "Negados", VERMELHO_UI),
                                                  ("taxa", "Taxa de aprovação", AMARELO_UI)]):
            cartao = self._cartao(kpis)
            cartao.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 12, 0))
            kpis.grid_columnconfigure(i, weight=1)
            ctk.CTkFrame(cartao, width=4, height=40, fg_color=cor, corner_radius=2).pack(
                side="left", padx=(16, 0), pady=16)
            caixa = ctk.CTkFrame(cartao, fg_color="transparent")
            caixa.pack(side="left", padx=14, pady=12)
            ctk.CTkLabel(caixa, text=rotulo, font=fonte(12), text_color=SUAVE).pack(anchor="w")
            valor = ctk.CTkLabel(caixa, text="0", font=fonte(26, "bold"), text_color=TEXTO)
            valor.pack(anchor="w")
            self.kpis[chave] = valor

        cartao_logs = self._cartao(pagina)
        cartao_logs.pack(fill="both", expand=True, padx=28, pady=14)
        ctk.CTkLabel(cartao_logs, text="Histórico de acessos", font=fonte(14, "bold"),
                     text_color=TEXTO).pack(anchor="w", padx=18, pady=(14, 4))
        self.tabela_logs = self._criar_tabela(
            cartao_logs, ("data", "usuario", "area", "resultado", "motivo", "distancia"),
            ("Data/Hora", "Usuário", "Área", "Resultado", "Motivo", "Distância"),
            (140, 190, 170, 95, 290, 75), altura=8)
        self.tabela_logs.tag_configure("NEGADO", foreground="#FCA5A5")
        self.tabela_logs.tag_configure("PERMITIDO", foreground="#86EFAC")

        cartao_alertas = self._cartao(pagina)
        cartao_alertas.pack(fill="x", padx=28, pady=(0, 24))
        cabecalho = ctk.CTkFrame(cartao_alertas, fg_color="transparent")
        cabecalho.pack(fill="x", padx=18, pady=(14, 4))
        ctk.CTkLabel(cabecalho, text="Alertas de segurança em aberto", font=fonte(14, "bold"),
                     text_color=AMARELO_UI).pack(side="left")
        self._botao_secundario(cabecalho, "Marcar como resolvido", self.resolver_alerta).pack(side="right")
        self.tabela_alertas = self._criar_tabela(
            cartao_alertas, ("id", "data", "tipo", "descricao", "area"),
            ("ID", "Data/Hora", "Tipo", "Descrição", "Área"), (50, 150, 190, 430, 150), altura=3)
        return pagina

    @staticmethod
    def _criar_tabela(pai, colunas, titulos, larguras, altura=14):
        moldura = ctk.CTkFrame(pai, fg_color="transparent")
        moldura.pack(fill="both", expand=True, padx=12, pady=(4, 12))
        tabela = ttk.Treeview(moldura, columns=colunas, show="headings", height=altura,
                              style="Eco.Treeview")
        for c, t, l in zip(colunas, titulos, larguras):
            tabela.heading(c, text=t, anchor="w")
            tabela.column(c, width=l, anchor="w")
        rolagem = ctk.CTkScrollbar(moldura, command=tabela.yview, fg_color=CARTAO,
                                   button_color=BORDA, button_hover_color=VERDE_ESCURO)
        tabela.configure(yscrollcommand=rolagem.set)
        tabela.pack(side="left", fill="both", expand=True)
        rolagem.pack(side="right", fill="y")
        return tabela

    # ================================================================ câmera
    def _garantir_camera(self, avisar=True) -> bool:
        if self.camera is not None:
            return True
        agora = time.time()
        if not avisar and agora - self._ultima_tentativa_camera < 3:
            return False   # tenta reabrir no máximo a cada 3 s para não travar a tela
        self._ultima_tentativa_camera = agora
        try:
            self.camera = Camera()
            return True
        except ErroCamera as erro:
            if avisar:
                messagebox.showerror("Câmera indisponível", str(erro))
            else:
                self.lbl_instrucao.configure(text="Câmera não encontrada. Conecte uma webcam.")
            return False

    def _ciclo_camera(self):
        """Laço principal: executado a cada ~15 ms pela própria interface."""
        try:
            if self.pagina in ("acesso", "cadastro") and self._garantir_camera(avisar=False):
                quadro = self.camera.ler()
                if self.modo == "VERIFICANDO":
                    quadro = self._passo_verificacao(quadro)
                elif self.modo == "CADASTRO":
                    quadro = self._passo_cadastro(quadro)
                else:
                    self.extrator.coletar()   # descarta resultados atrasados
                destino = self.video_acesso if self.pagina == "acesso" else self.video_cadastro
                self._exibir(quadro, destino)
        except ErroCamera as erro:
            self._cancelar_modo(str(erro))
            if self.camera:
                self.camera.liberar()
            self.camera = None
        except Exception as erro:  # nunca deixa a interface travar por um erro inesperado
            self._cancelar_modo(f"Erro inesperado: {erro}")
        self._timer_camera = self.after(15, self._ciclo_camera)

    def _exibir(self, quadro_bgr, rotulo):
        largura = max(rotulo.winfo_width(), 320)
        altura = max(rotulo.winfo_height(), 240)
        h, w = quadro_bgr.shape[:2]
        escala = min(largura / w, altura / h)
        quadro = cv2.resize(quadro_bgr, (int(w * escala), int(h * escala)),
                            interpolation=cv2.INTER_LINEAR)
        self._foto_tk = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(quadro, cv2.COLOR_BGR2RGB)))
        rotulo.configure(image=self._foto_tk)

    # ======================================================= acesso ao cofre
    def iniciar_verificacao(self):
        if self.modo != "OCIOSO" or not self._garantir_camera():
            return
        if self.reconhecedor.total_cadastrados == 0:
            messagebox.showinfo("EcoLock", "Nenhum usuário cadastrado. Use a página Cadastro.")
            return
        self.area_atual = self._area_selecionada()
        self.sessao += 1
        self.confirmador.limpar()
        self.detector_piscada.reiniciar()
        self.ultima_identificacao = None
        self.inicio_tentativa = time.time()
        self.modo = "VERIFICANDO"
        self.btn_solicitar.configure(state="disabled", text="Verificando...")
        self._marcar_etapas()
        self._mostrar_resultado("VERIFICANDO", f"Área: {self.area_atual['nome']}", AMARELO_UI)
        for chave in self.detalhes:
            self.detalhes[chave].configure(text="—")
        self.detalhes["Área"].configure(text=self.area_atual["nome"])

    def _receber_vetores(self):
        """Fase 5: identifica cada vetor que voltou dos processos de extração."""
        for etiqueta, vetor in self.extrator.coletar():
            if etiqueta != self.sessao or vetor is None:
                continue
            ident = self.reconhecedor.identificar(vetor)
            self.ultima_identificacao = ident
            self.confirmador.adicionar(ident)

    def _passo_verificacao(self, quadro):
        """Executa as fases sobre um quadro e avança a máquina de estados."""
        restante = config.TEMPO_MAXIMO_TENTATIVA - (time.time() - self.inicio_tentativa)
        self.barra_tempo.set(max(0.0, restante / config.TEMPO_MAXIMO_TENTATIVA))
        self.barra_tempo.configure(progress_color=VERDE_UI if restante > 4 else AMARELO_UI)

        q = preprocessar(quadro)                                   # fase 2
        problema = avaliar_qualidade(q)
        caixas = segmentar_rostos(q)                               # fase 3
        self._receber_vetores()                                    # fases 4 e 5 (assíncronas)

        if len(caixas) != 1:
            self._marcar_etapas()
            self.lbl_instrucao.configure(text=problema or (
                "Posicione o rosto em frente à câmera (a até ~60 cm)" if not caixas
                else "Apenas uma pessoa por vez em frente à câmera"))
            if restante <= 0:
                self._finalizar(None, motivo_falha="Tempo esgotado sem identificação")
            return quadro

        caixa = caixas[0]
        confirmado = self.confirmador.confirmado()
        if confirmado is None:
            self.extrator.enviar(self.sessao, q.rgb, caixa)        # fase 4 em paralelo
        vivo = self.detector_piscada.atualizar(extrair_marcos(q, caixa))

        ident = self.ultima_identificacao
        if ident is None:
            cor, rotulo = AMARELO, "Analisando..."
        elif ident.usuario_id is None:
            cor, rotulo = VERMELHO, "Nao reconhecido"
        else:
            cor, rotulo = VERDE, f"Confianca {ident.confianca:.0f}%"
        desenhar_caixa(quadro, caixa_no_original(caixa), rotulo, cor)
        self._marcar_etapas(rosto=True, identidade=confirmado not in (None, "DESCONHECIDO"),
                            vida=vivo)

        distancia = ident.distancia if ident else None
        if confirmado == "DESCONHECIDO":
            self._finalizar(None, distancia)
        elif confirmado is not None and vivo:
            self._finalizar(confirmado, distancia)
        elif restante <= 0:
            if confirmado is not None:
                self._finalizar(confirmado, distancia, prova_vida_ok=False)
            else:
                self._finalizar(None, distancia, motivo_falha="Tempo esgotado sem identificação")
        else:
            self.lbl_instrucao.configure(
                text=problema or ("Pisque naturalmente para confirmar a prova de vida"
                                  if confirmado else "Mantenha o rosto parado..."))
        return quadro

    def _finalizar(self, usuario_id, distancia=None, prova_vida_ok=True, motivo_falha=None):
        decisao = self.controle.decidir(self.area_atual, usuario_id, distancia,
                                        prova_vida_ok, motivo_falha)
        self.modo = "RESULTADO"
        self.barra_tempo.set(0)
        nome = decisao.usuario["nome"] if decisao.usuario else "Desconhecido"
        nivel = NOMES_NIVEIS.get(decisao.usuario["nivel_id"], "—") if decisao.usuario else "—"
        if decisao.permitido:
            self._mostrar_resultado("ACESSO LIBERADO", f"Bem-vindo(a), {nome.split()[0]}", VERDE_ESCURO)
        else:
            self._mostrar_resultado("ACESSO NEGADO", decisao.motivo, "#991B1B")
        self._marcar_etapas(rosto=True, identidade=decisao.usuario is not None,
                            vida=prova_vida_ok and decisao.usuario is not None,
                            nivel=decisao.permitido)
        self.detalhes["Usuário"].configure(text=nome)
        self.detalhes["Permissão"].configure(text=nivel)
        self.detalhes["Área"].configure(text=self.area_atual["nome"])
        self.detalhes["Motivo"].configure(text=decisao.motivo)
        self.detalhes["Horário"].configure(text=datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
        self.lbl_instrucao.configure(text="Verificação concluída e registrada no histórico")
        if decisao.alerta_gerado:
            self.bell()
            messagebox.showwarning("ALERTA DE SEGURANÇA",
                                   "Várias tentativas de acesso negadas em sequência foram "
                                   "detectadas. O alerta foi registrado para a equipe de segurança.")
        self.after(4000, self._voltar_ocioso)

    def _mostrar_resultado(self, titulo, subtitulo, cor):
        self.cartao_resultado.configure(fg_color=cor)
        self.lbl_resultado.configure(text=titulo)
        self.lbl_resultado_sub.configure(text=subtitulo, wraplength=290)

    def _voltar_ocioso(self):
        self.modo = "OCIOSO"
        self.btn_solicitar.configure(state="normal", text="Solicitar acesso")
        self._mostrar_resultado("AGUARDANDO", "Nenhuma verificação em andamento", NEUTRO)
        self.lbl_instrucao.configure(text="Selecione a área e clique em Solicitar acesso")

    def _marcar_etapas(self, **estados):
        for chave, (marca, rotulo) in self.etapas.items():
            ok = estados.get(chave, False)
            marca.configure(text="●" if ok else "○", text_color=VERDE_UI if ok else SUAVE)
            rotulo.configure(text_color=TEXTO if ok else SUAVE)

    def _cancelar_modo(self, mensagem):
        if self.modo in ("VERIFICANDO", "CADASTRO"):
            messagebox.showerror("EcoLock", mensagem)
        self.modo = "OCIOSO"
        self.sessao += 1
        self.btn_solicitar.configure(state="normal", text="Solicitar acesso")
        self.btn_capturar.configure(state="normal", text="Capturar rosto e salvar")
        self.barra_tempo.set(0)

    # ============================================================== cadastro
    def iniciar_cadastro(self):
        nome = self.campos["nome"].get().strip()
        cargo = self.campos["cargo"].get().strip()
        nivel_id = int(self.seg_nivel.get()[-1])
        divisao = self.cmb_divisao.get()
        divisao = None if divisao == SEM_DIVISAO or nivel_id == 3 else divisao
        if len(nome) < 3 or not cargo:
            messagebox.showwarning("Cadastro", "Preencha o nome completo e o cargo.")
            return
        if nivel_id == 2 and divisao is None:
            messagebox.showwarning("Cadastro", "Diretores (nível 2) precisam ter a divisão definida: "
                                               "eles só entram na área da própria divisão.")
            return
        if nivel_id == 3 and self.banco.contar_ativos_no_nivel(3) > 0:
            messagebox.showwarning("Cadastro", "Já existe um ministro ativo. O nível 3 é exclusivo do "
                                               "ministro: desative o atual antes de cadastrar outro.")
            return
        if self.modo != "OCIOSO" or not self._garantir_camera():
            return
        self.dados_cadastro = (nome, cargo, divisao, nivel_id)
        self.sessao += 1
        self.amostras_cadastro = []
        self.ultima_amostra = 0.0
        self.detector_piscada.reiniciar()
        self.inicio_cadastro = time.time()
        self.modo = "CADASTRO"
        self.barra_amostras.set(0)
        self.btn_capturar.configure(state="disabled", text="Capturando...")
        self.lbl_progresso.configure(text="Olhe para a câmera e pisque uma vez...")

    def _passo_cadastro(self, quadro):
        q = preprocessar(quadro)
        problema = avaliar_qualidade(q)
        caixas = segmentar_rostos(q)

        for etiqueta, vetor in self.extrator.coletar():
            if etiqueta != self.sessao or vetor is None or self.modo != "CADASTRO":
                continue
            if not self.amostras_cadastro:
                existente = self.reconhecedor.identificar(vetor)
                if existente.usuario_id is not None:
                    usuario = self.banco.buscar_usuario(existente.usuario_id)
                    self._cancelar_modo(f"Este rosto já está cadastrado para: {usuario['nome']}.")
                    return quadro
            self.amostras_cadastro.append(vetor)
            total = len(self.amostras_cadastro)
            self.barra_amostras.set(total / config.AMOSTRAS_CADASTRO)
            self.lbl_progresso.configure(text=f"Amostra {total} de {config.AMOSTRAS_CADASTRO} capturada")
            if total >= config.AMOSTRAS_CADASTRO:
                self._salvar_cadastro()
                return quadro

        if time.time() - self.inicio_cadastro > config.TEMPO_MAXIMO_CADASTRO:
            self._cancelar_modo("Tempo esgotado: a prova de vida ou a captura não foi concluída. "
                                "Fotos não são aceitas no cadastro.")
            return quadro

        if len(caixas) != 1 or problema:
            self.lbl_progresso.configure(text=problema or "Deve haver exatamente um rosto na imagem")
            return quadro

        caixa = caixas[0]
        # Prova de vida também no cadastro: impede cadastrar alguém a partir de uma foto
        if not self.detector_piscada.atualizar(extrair_marcos(q, caixa)):
            desenhar_caixa(quadro, caixa_no_original(caixa), "Pisque para comecar", AMARELO)
            self.lbl_progresso.configure(text="Pisque uma vez para provar que é uma pessoa real")
            return quadro
        desenhar_caixa(quadro, caixa_no_original(caixa),
                       f"Amostra {len(self.amostras_cadastro)}/{config.AMOSTRAS_CADASTRO}", VERDE)
        if time.time() - self.ultima_amostra >= 0.7:            # intervalo para variar a pose
            if self.extrator.enviar(self.sessao, q.rgb, caixa):
                self.ultima_amostra = time.time()
        return quadro

    def _salvar_cadastro(self):
        nome, cargo, divisao, nivel_id = self.dados_cadastro
        usuario_id = self.banco.cadastrar_usuario(
            nome, cargo, divisao, nivel_id, self.amostras_cadastro[:config.AMOSTRAS_CADASTRO])
        self.reconhecedor.recarregar()
        self.modo = "OCIOSO"
        self.sessao += 1
        self.btn_capturar.configure(state="normal", text="Capturar rosto e salvar")
        for campo in self.campos.values():
            campo.delete(0, "end")
        self.cmb_divisao.set(SEM_DIVISAO)
        self.lbl_progresso.configure(text="Cadastro concluído")
        messagebox.showinfo("Cadastro", f"Usuário cadastrado com sucesso (ID {usuario_id}).")

    # ============================================================== usuários
    def carregar_usuarios(self):
        self.tabela_usuarios.delete(*self.tabela_usuarios.get_children())
        for u in self.banco.listar_usuarios():
            self.tabela_usuarios.insert("", "end", iid=u["id"],
                                        tags=() if u["ativo"] else ("inativo",), values=(
                u["id"], u["nome"], u["cargo"], u["divisao"] or "—",
                NOMES_NIVEIS.get(u["nivel_id"]), "Ativo" if u["ativo"] else "Inativo",
                u["amostras"], u["criado_em"].strftime("%d/%m/%Y %H:%M")))

    def _usuario_selecionado(self):
        selecao = self.tabela_usuarios.selection()
        if not selecao:
            messagebox.showinfo("Usuários", "Selecione um usuário na lista.")
            return None
        return int(selecao[0])

    def alternar_status(self):
        usuario_id = self._usuario_selecionado()
        if usuario_id is None:
            return
        usuario = self.banco.buscar_usuario(usuario_id)
        if (not usuario["ativo"] and usuario["nivel_id"] == 3
                and self.banco.contar_ativos_no_nivel(3, exceto_id=usuario_id) > 0):
            messagebox.showwarning("Usuários", "Já existe um ministro ativo. O nível 3 é exclusivo: "
                                               "desative o atual antes de reativar este.")
            return
        self.banco.alterar_status(usuario_id, not usuario["ativo"])
        self.reconhecedor.recarregar()
        self.carregar_usuarios()

    def excluir_usuario(self):
        usuario_id = self._usuario_selecionado()
        if usuario_id is None:
            return
        usuario = self.banco.buscar_usuario(usuario_id)
        if messagebox.askyesno("Excluir", f"Excluir {usuario['nome']} e todos os seus dados "
                                          "biométricos? Esta ação não pode ser desfeita."):
            self.banco.excluir_usuario(usuario_id)
            self.reconhecedor.recarregar()
            self.carregar_usuarios()

    # ============================================================ relatórios
    def _filtrar_logs(self):
        fim = datetime.now()
        periodo = self.cmb_periodo.get()
        if periodo == "Tudo":
            inicio = datetime(2000, 1, 1)
        elif periodo == "Hoje":
            inicio = fim.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            inicio = fim - timedelta(days=7 if "7" in periodo else 30)
        resultado = self.cmb_resultado.get()
        return self.banco.consultar_logs(inicio, fim, None if resultado == "Todos" else resultado)

    def carregar_relatorio(self):
        logs = self._filtrar_logs()
        self.tabela_logs.delete(*self.tabela_logs.get_children())
        for l in logs:
            self.tabela_logs.insert("", "end", tags=(l["resultado"],), values=(
                l["data_hora"].strftime("%d/%m/%Y %H:%M:%S"), l["usuario"], l["area"],
                l["resultado"], l["motivo"],
                "—" if l["distancia"] is None else f"{l['distancia']:.3f}"))
        r = relatorios.resumo(logs)
        self.kpis["total"].configure(text=str(r["total"]))
        self.kpis["permitidos"].configure(text=str(r["permitidos"]))
        self.kpis["negados"].configure(text=str(r["negados"]))
        self.kpis["taxa"].configure(text=f"{r['taxa_aprovacao']:.0f}%")

        self.tabela_alertas.delete(*self.tabela_alertas.get_children())
        for a in self.banco.listar_alertas():
            self.tabela_alertas.insert("", "end", iid=a["id"], values=(
                a["id"], a["data_hora"].strftime("%d/%m/%Y %H:%M:%S"), a["tipo"],
                a["descricao"], a["area"]))

    def exportar_relatorio(self):
        logs = self._filtrar_logs()
        if not logs:
            messagebox.showinfo("Relatórios", "Não há registros no período selecionado.")
            return
        arquivo = relatorios.exportar_csv(logs)
        messagebox.showinfo("Relatórios", f"Relatório exportado para:\n{arquivo}")

    def resolver_alerta(self):
        selecao = self.tabela_alertas.selection()
        if not selecao:
            messagebox.showinfo("Alertas", "Selecione um alerta na lista.")
            return
        self.banco.resolver_alerta(int(selecao[0]))
        self.carregar_relatorio()

    # ============================================================ encerramento
    def encerrar(self):
        for timer in (self._timer_camera, self._timer_status):
            try:
                self.after_cancel(timer)
            except Exception:
                pass
        if self.camera is not None:
            self.camera.liberar()
        self.extrator.encerrar()
        self.banco.fechar()
        self.destroy()