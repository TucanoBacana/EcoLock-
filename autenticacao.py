"""
EcoLock - Proteção das senhas dos administradores.

A senha nunca é gravada no banco. Grava-se apenas um resumo (hash) gerado
pelo algoritmo PBKDF2 com SHA-256, um "sal" aleatório por administrador e
200 mil iterações, o que torna inviável descobrir a senha a partir do banco.
"""

import hashlib
import hmac
import secrets

ITERACOES = 200_000


def gerar_hash(senha: str):
    """Retorna (sal_hex, hash_hex) para uma senha nova."""
    sal = secrets.token_bytes(16)
    resumo = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), sal, ITERACOES)
    return sal.hex(), resumo.hex()


def conferir_senha(senha: str, sal_hex: str, hash_hex: str) -> bool:
    """Compara em tempo constante, evitando ataques por medição de tempo."""
    resumo = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), bytes.fromhex(sal_hex), ITERACOES)
    return hmac.compare_digest(resumo.hex(), hash_hex)


def validar_senha_nova(senha: str):
    """Retorna uma mensagem de problema ou None se a senha for aceitável."""
    if len(senha) < 8:
        return "A senha deve ter pelo menos 8 caracteres."
    if senha.isalpha() or senha.isdigit():
        return "A senha deve misturar letras e números."
    return None