"""Gráficos em PNG com matplotlib (o "QuickSight local")."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def _salvar(fig, pasta: Path, nome_base: str) -> str:
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{nome_base}_{datetime.now():%Y%m%d_%H%M%S_%f}.png"
    fig.tight_layout()
    fig.savefig(caminho, dpi=120)
    plt.close(fig)
    return str(caminho)


def grafico_serie(pasta: Path, nome_base: str, titulo: str, rotulos: list[str],
                  valores: list[float], rotulo_y: str, linha: bool) -> str:
    fig, ax = plt.subplots(figsize=(10, 5))
    if linha:
        ax.plot(rotulos, valores, marker="o" if len(valores) <= 40 else None, color="#2f6db5")
    else:
        ax.bar(rotulos, valores, color="#2f6db5")
    ax.set_title(titulo)
    ax.set_ylabel(rotulo_y)
    ax.grid(axis="y", alpha=0.3)
    passo = max(1, len(rotulos) // 15)
    ax.set_xticks(range(0, len(rotulos), passo), [rotulos[i] for i in range(0, len(rotulos), passo)],
                  rotation=45, ha="right")
    return _salvar(fig, pasta, nome_base)


def grafico_previsao(pasta: Path, datas_hist: list[date], valores_hist: list[float],
                     datas_prev: list[date], valores_prev: list[float]) -> str:
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(datas_hist, valores_hist, color="#2f6db5", label="Histórico")
    ax.plot(datas_prev, valores_prev, color="#d9822b", linestyle="--", label="Previsão")
    ax.set_title("Faturamento diário: histórico e previsão")
    ax.set_ylabel("R$")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.autofmt_xdate()
    return _salvar(fig, pasta, "previsao_faturamento")
