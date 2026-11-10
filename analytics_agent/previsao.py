"""Previsão de faturamento diário com scikit-learn (o "SageMaker local").

Modelo: regressão Ridge com tendência linear + dia da semana + mês. Simples de
explicar e suficiente para a sazonalidade dos dados do restaurante.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
from sklearn.linear_model import Ridge

DIAS_VALIDACAO = 28
HISTORICO_MINIMO = 90


@dataclass
class Previsao:
    datas: list[date]
    valores: list[float]
    erro_medio_validacao: float  # MAPE nos últimos DIAS_VALIDACAO dias do histórico


def _atributos(datas: list[date], origem: date) -> np.ndarray:
    x = np.zeros((len(datas), 1 + 7 + 12))
    for i, d in enumerate(datas):
        x[i, 0] = (d - origem).days / 365
        x[i, 1 + d.weekday()] = 1
        x[i, 8 + d.month - 1] = 1
    return x


def prever_faturamento_diario(historico: dict[date, float], dias: int) -> Previsao:
    inicio, fim = min(historico), max(historico)
    datas = [inicio + timedelta(days=n) for n in range((fim - inicio).days + 1)]
    if len(datas) < HISTORICO_MINIMO:
        raise ValueError(f"São necessários pelo menos {HISTORICO_MINIMO} dias de histórico para prever.")

    y = np.array([historico.get(d, 0.0) for d in datas])
    x = _atributos(datas, inicio)
    aberto = y > 0  # dias fechados (feriados) ficam fora do treino
    treino = np.arange(len(datas)) < len(datas) - DIAS_VALIDACAO

    modelo = Ridge(alpha=1.0).fit(x[treino & aberto], y[treino & aberto])
    teste = ~treino & aberto
    erro = float(np.mean(np.abs(modelo.predict(x[teste]) - y[teste]) / y[teste]))

    modelo = Ridge(alpha=1.0).fit(x[aberto], y[aberto])
    futuras = [fim + timedelta(days=n) for n in range(1, dias + 1)]
    valores = np.clip(modelo.predict(_atributos(futuras, inicio)), 0, None)
    return Previsao(futuras, [float(v) for v in valores], erro)
