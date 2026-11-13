"""
EcoLock - Relatórios de auditoria.

Gera estatísticas dos acessos e exporta o histórico para CSV, que pode
ser aberto no Excel para auditoria.
"""

import csv
from collections import Counter
from datetime import datetime
from pathlib import Path

import config


def resumo(logs):
    """Calcula os indicadores exibidos na página de relatórios."""
    total = len(logs)
    permitidos = sum(1 for l in logs if l["resultado"] == "PERMITIDO")
    negados = total - permitidos
    motivos = Counter(l["motivo"] for l in logs if l["resultado"] == "NEGADO")
    por_area = Counter(l["area"] for l in logs)
    return {
        "total": total,
        "permitidos": permitidos,
        "negados": negados,
        "taxa_aprovacao": (permitidos / total * 100) if total else 0.0,
        "principais_motivos": motivos.most_common(3),
        "por_area": dict(por_area),
    }


def exportar_csv(logs, pasta=config.PASTA_RELATORIOS) -> Path:
    """Salva os registros em um arquivo CSV com data e hora no nome."""
    destino = Path(pasta)
    destino.mkdir(parents=True, exist_ok=True)
    arquivo = destino / f"relatorio_acessos_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with arquivo.open("w", newline="", encoding="utf-8-sig") as f:
        escritor = csv.writer(f, delimiter=";")
        escritor.writerow(["Data/Hora", "Usuário", "Área", "Nível exigido",
                           "Resultado", "Motivo", "Distância"])
        for l in logs:
            escritor.writerow([
                l["data_hora"].strftime("%d/%m/%Y %H:%M:%S"), l["usuario"], l["area"],
                l["nivel_minimo"], l["resultado"], l["motivo"],
                "" if l["distancia"] is None else f"{l['distancia']:.3f}",
            ])
    return arquivo.resolve()