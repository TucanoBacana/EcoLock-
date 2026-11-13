"""
EcoLock - Sistema de Identificação e Autenticação Biométrica
Ponto de entrada da aplicação.

Uso:
    1. Inicie o MySQL pelo painel do XAMPP.
    2. Instale as dependências:  pip install -r requirements.txt
    3. Execute:                  python main.py
"""

import sys
import tkinter as tk
from tkinter import messagebox

import mysql.connector


def main():
    try:
        from database import BancoDeDados
        banco = BancoDeDados()
    except mysql.connector.Error as erro:
        raiz = tk.Tk()
        raiz.withdraw()
        messagebox.showerror(
            "EcoLock - Banco de dados indisponível",
            "Não foi possível conectar ao MySQL.\n\n"
            "Abra o painel do XAMPP e clique em 'Start' no módulo MySQL.\n\n"
            f"Detalhe técnico: {erro}")
        sys.exit(1)

    from interface import AplicacaoEcoLock
    app = AplicacaoEcoLock(banco)
    app.mainloop()


if __name__ == "__main__":
    main()