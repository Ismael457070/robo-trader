"""Reconstrucao do laboratorio perdido (rodar_setups / carteira2).

Os scripts originais nunca foram enviados ao Git. As regras abaixo sao as que
sobreviveram em robo.py e sombra.py: mesmas funcoes de sinal, custo de 0,08%
por giro, filtro de BTC de 150 dias, alvo de volatilidade 35% e banda de 10%.

Nao afirma que os numeros batem com o estudo antigo. Grava o que esta conta
produz hoje, para nao depender de memoria.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
import sombra  # noqa: E402

DADOS = Path(__file__).resolve().parent / "dados"
SAIDA = Path(__file__).resolve().parent / "resultados"
FILTRO_DIAS = 150
VOL_ALVO = 0.35
BANDA = 0.10


def carregar():
    ohlc = {}
    for arq in sorted(DADOS.glob("*.csv")):
        d = pd.read_csv(arq)
        d["ts"] = pd.to_datetime(d.open_time, unit="ms", utc=True)
        d = d.set_index("ts").sort_index()[["open", "high", "low", "close"]].astype(float)
        d = d.resample("1D").agg(open=("open", "first"), high=("high", "max"),
                                 low=("low", "min"), close=("close", "last")).dropna()
        if len(d):
            ohlc[arq.stem] = d
    if "BTCUSDT" not in ohlc:
        raise SystemExit(f"faltam candles em {DADOS}; rode baixar_dados.py")
    return ohlc


def equity(ohlc, fn, filtro=True):
    """Mesma conta de sombra.historico, devolvendo a curva em vez de so gravar CSV."""
    fech = pd.DataFrame({s: ohlc[s].close for s in ohlc}).ffill()
    ret = fech.pct_change().fillna(0.0)
    vol = fech.pct_change().rolling(30).std() * np.sqrt(365)
    btc = fech["BTCUSDT"]
    reg = (btc > btc.rolling(FILTRO_DIAS).mean()).astype(float)
    if fn is None:
        w = pd.DataFrame(0.0, index=fech.index, columns=fech.columns)
        w["BTCUSDT"] = 1.0
    else:
        sinal = pd.DataFrame({s: fn(ohlc[s]) for s in ohlc}).reindex(fech.index).fillna(0.0)
        if filtro:
            sinal = sinal.mul(reg, axis=0)
        n = sinal.sum(axis=1).replace(0, np.nan)
        w = sinal.div(n, axis=0).fillna(0.0)
        esc = (VOL_ALVO / ((w * vol).sum(axis=1) * 0.8)).clip(upper=1.0).fillna(0.0)
        w = w.mul(esc, axis=0)
        vals = w.values
        out = np.zeros_like(vals)
        prev = np.zeros(vals.shape[1])
        for i in range(len(vals)):
            cur = vals[i]
            mud = np.abs(cur - prev) > BANDA * np.maximum(prev, 0.02)
            zer = (cur == 0) & (prev != 0)
            prev = np.where(mud | zer, cur, prev)
            out[i] = prev
        w = pd.DataFrame(out, index=fech.index, columns=fech.columns)
    pos = w.shift(1).fillna(0.0)
    r = (pos * ret).sum(axis=1) - pos.diff().abs().fillna(pos.abs()).sum(axis=1) * sombra.CUSTO
    r = r.iloc[FILTRO_DIAS:]
    eq = sombra.BASE * (1 + r).cumprod()
    eq.index = eq.index.tz_convert("UTC")
    return eq


def metricas(eq):
    r = eq.pct_change().dropna()
    anos = len(r) / 365.0
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / anos) - 1 if anos > 0 else 0.0
    queda = float((eq / eq.cummax() - 1).min())
    sharpe = float(r.mean() / r.std() * np.sqrt(365)) if r.std() > 0 else 0.0
    return {
        "inicio": str(eq.index[0].date()),
        "fim": str(eq.index[-1].date()),
        "dias": int(len(eq)),
        "patrimonio_final": round(float(eq.iloc[-1]), 2),
        "cagr": round(float(cagr), 4),
        "queda_maxima": round(queda, 4),
        "sharpe": round(sharpe, 4),
    }


def fatia(eq, inicio):
    pedaco = eq[eq.index >= pd.Timestamp(inicio, tz="UTC")]
    if len(pedaco) < 30:
        return None
    return metricas(pedaco)


def main():
    ohlc = carregar()
    SAIDA.mkdir(parents=True, exist_ok=True)
    estrategias = dict(sombra.ESTRATEGIAS)
    estrategias["BTC comprado e parado (régua)"] = (None, False)

    curvas = []
    resumo = []
    for nome, (fn, filtro) in estrategias.items():
        eq = equity(ohlc, fn, filtro)
        m = metricas(eq)
        m["estrategia"] = nome
        m["fora_da_amostra_2023"] = fatia(eq, "2023-01-01")
        resumo.append(m)
        curvas.append(pd.DataFrame({
            "data": [str(x.date()) for x in eq.index],
            "estrategia": nome,
            "patrimonio": eq.round(2).values,
        }))
        fora = m["fora_da_amostra_2023"] or {}
        print(f"{nome}: Sharpe {m['sharpe']:.2f}  CAGR {m['cagr']:.0%}  queda {m['queda_maxima']:.0%}"
              f"  | 2023+ Sharpe {fora.get('sharpe', float('nan')):.2f}")

    pd.concat(curvas).to_csv(SAIDA / "curvas.csv", index=False)

    plato = []
    for ang in [round(x, 2) for x in np.arange(0.10, 0.27, 0.01)]:
        fn = lambda d, a=ang: sombra.raghee(d, a=a)
        m = metricas(equity(ohlc, fn, True))
        m["ang_min"] = ang
        plato.append(m)
        print(f"plato ang={ang:.2f}: Sharpe {m['sharpe']:.2f}  CAGR {m['cagr']:.0%}  queda {m['queda_maxima']:.0%}")
    pd.DataFrame(plato).to_csv(SAIDA / "plato_angulo.csv", index=False)

    doc = {
        "nota": "Reconstruido a partir de robo.py e sombra.py. O laboratorio original (2018-2026) nao estava no Git.",
        "custo_por_giro": sombra.CUSTO,
        "base": sombra.BASE,
        "filtro_btc_dias": FILTRO_DIAS,
        "vol_alvo": VOL_ALVO,
        "banda": BANDA,
        "moedas": sorted(ohlc),
        "estrategias": resumo,
        "plato_ang_min": plato,
        "numeros_lembrados_do_estudo_perdido": {
            "Raghee — onda 34 + relógio": "Sharpe 1,55 · CAGR 40% · queda -26% · fora da amostra 2023-26 Sharpe 1,25",
            "fonte": "README.md e painel.py, escritos antes desta reconstrucao",
        },
    }
    (SAIDA / "metricas.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"gravado em {SAIDA}")


if __name__ == "__main__":
    main()
