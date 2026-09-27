"""Carteiras virtuais ('sombra'): roda varias estrategias em paralelo sobre os mesmos dados diarios,
sem enviar ordens. Cada uma tem patrimonio proprio (base 100.000), custos de 0,08% por giro.
Estado em PASTA_ESTADO/sombra.json; historico em sombra.csv. Chamado pelo robo.py uma vez por dia."""
import os, json
import numpy as np, pandas as pd

CUSTO = 0.0008
BASE = 100000.0


def _atr(d, n=14):
    tr = pd.concat([d.high - d.low, (d.high - d.close.shift()).abs(), (d.low - d.close.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def _maq(d, e, s):
    p = 0.0; out = np.zeros(len(d)); e = e.fillna(False).values; s = s.fillna(False).values
    for i in range(len(d)):
        if p == 0 and e[i]: p = 1.0
        elif p == 1 and s[i]: p = 0.0
        out[i] = p
    return pd.Series(out, index=d.index)


def _segura(d, gat, dias):
    out = np.zeros(len(d)); g = gat.fillna(False).values; r = 0
    for i in range(len(d)):
        if g[i]: r = dias
        if r > 0: out[i] = 1.0; r -= 1
    return pd.Series(out, index=d.index)


def _onda(d):
    return (d.high.ewm(span=34, adjust=False).mean(), d.close.ewm(span=34, adjust=False).mean(), d.low.ewm(span=34, adjust=False).mean())


def _ang(d):
    _, m, _ = _onda(d); return (m - m.shift(5)) / (5 * _atr(d))


def raghee(d, a=0.17):
    hi, _, lo = _onda(d); g = _ang(d)
    return _maq(d, (g > a) & (d.close > hi) & (d.close > d.high.rolling(10).max().shift(1)), (d.close < lo) | (g < -a))


def raghee_swing(d):
    hi, _, lo = _onda(d); g = _ang(d)
    corr = (d.close.rolling(5).min().shift(1) <= hi.shift(1)) & (d.close.rolling(5).min().shift(1) >= lo.shift(1) * 0.98)
    return _maq(d, (g > 0.05) & corr & (d.close > hi) & (d.close.shift(1) <= hi.shift(1)), (d.close < lo) | (g < -0.05))


def donchian(d):
    c = d.close
    return _maq(d, c > c.rolling(55).max().shift(1), c < c.rolling(20).min().shift(1))


def _adx(d, n=14):
    up = d.high.diff(); dn = -d.low.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=d.index)
    ndm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=d.index)
    a = _atr(d, n)
    pdi = 100 * pdm.ewm(alpha=1 / n, adjust=False).mean() / a; ndi = 100 * ndm.ewm(alpha=1 / n, adjust=False).mean() / a
    dx = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean(), pdi, ndi


def holy_grail(d):
    e = d.close.ewm(span=20, adjust=False).mean(); a, p, n = _adx(d)
    return _maq(d, (a > 30) & (p > n) & (d.low.rolling(3).min() <= e) & (d.close > d.high.shift(1)) & (d.close > e),
                (d.close < d.low.rolling(10).min().shift(1)) | (a < 20))


def oitenta_vinte(d):
    amp = (d.high - d.low).replace(0, np.nan)
    return _segura(d, ((d.open - d.low) / amp < 0.2) & ((d.close - d.low) / amp > 0.8) & (d.close > d.close.shift(1)), 3)


def anti(d):
    e20 = d.close.ewm(span=20, adjust=False).mean(); e50 = d.close.ewm(span=50, adjust=False).mean()
    o = d.close.ewm(span=3, adjust=False).mean() - d.close.ewm(span=10, adjust=False).mean(); s = o.ewm(span=16, adjust=False).mean()
    return _maq(d, (e20 > e50) & (o.shift(1) < s.shift(1)) & (o > s) & (o < 0), ((o < s) & (o.shift(1) >= s.shift(1))) | (e20 < e50))


ESTRATEGIAS = {
    "Raghee — onda 34 + relógio": (raghee, True),
    "Raghee — swing na onda": (raghee_swing, True),
    "Donchian 55/20": (donchian, True),
    "Raschke — Holy Grail": (holy_grail, True),
    "Raschke — 80-20": (oitenta_vinte, True),
    "Raschke — Anti": (anti, True),
}


def pesos(ohlc: dict, fn, filtro=True, filtro_dias=150, vol_alvo=0.35):
    fech = pd.DataFrame({s: ohlc[s].close for s in ohlc}).ffill()
    sinal = pd.DataFrame({s: fn(ohlc[s]) for s in ohlc}).reindex(fech.index).fillna(0.0)
    if filtro:
        b = fech["BTCUSDT"]; sinal = sinal.mul((b > b.rolling(filtro_dias).mean()).astype(float), axis=0)
    n = sinal.iloc[-1].sum()
    if n == 0:
        return pd.Series(0.0, index=fech.columns)
    w = sinal.iloc[-1] / n
    vol = fech.pct_change().rolling(30).std().iloc[-1] * np.sqrt(365)
    ve = float((w * vol).sum()) * 0.8
    return w * (min(1.0, vol_alvo / ve) if ve > 0 else 0.0)


def atualizar(ohlc: dict, pasta: str, dia: str, log=print):
    arq = os.path.join(pasta, "sombra.json")
    est = json.load(open(arq)) if os.path.exists(arq) else {}
    fech = pd.DataFrame({s: ohlc[s].close for s in ohlc}).ffill()
    precos = fech.iloc[-1].to_dict()
    todas = dict(ESTRATEGIAS)
    todas["BTC comprado e parado (régua)"] = (None, False)
    linhas = []
    for nome, (fn, filtro) in todas.items():
        e = est.get(nome, {"patrimonio": BASE, "pesos": {}, "precos": {}, "inicio": dia, "ultimo_dia": None})
        if e.get("ultimo_dia") == dia:  # ja processado hoje
            linhas.append((nome, e)); continue
        # 1) marca a mercado com os pesos de ontem
        ret = 0.0
        for s, w in e["pesos"].items():
            p0 = e["precos"].get(s); p1 = precos.get(s)
            if p0 and p1: ret += w * (p1 / p0 - 1)
        pat = e["patrimonio"] * (1 + ret)
        # 2) novos pesos
        novo = {"BTCUSDT": 1.0} if fn is None else {k: float(v) for k, v in pesos(ohlc, fn, filtro).items() if v > 0}
        giro = sum(abs(novo.get(k, 0) - e["pesos"].get(k, 0)) for k in set(novo) | set(e["pesos"]))
        pat *= (1 - giro * CUSTO)
        e.update(patrimonio=pat, pesos=novo, precos={k: precos[k] for k in novo}, ultimo_dia=dia)
        est[nome] = e; linhas.append((nome, e))
    json.dump(est, open(arq, "w"), indent=1, ensure_ascii=False)
    hist = os.path.join(pasta, "sombra.csv")
    pd.DataFrame([{"data": dia, "estrategia": n, "patrimonio": round(e["patrimonio"], 2),
                   "exposicao": round(sum(e["pesos"].values()), 4), "moedas": len(e["pesos"])} for n, e in linhas]
                 ).to_csv(hist, mode="a", header=not os.path.exists(hist), index=False)
    for n, e in linhas:
        log(f"sombra | {n}: {e['patrimonio']:,.0f} | exposicao {sum(e['pesos'].values()):.0%} | {len(e['pesos'])} moedas")
