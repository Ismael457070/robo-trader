"""
Robo de tendencia em cripto (spot Binance) — roda UMA vez por dia.

Estrategia (a mesma validada no backtest, carteira2.py):
  * Sinal por moeda: rompimento de maxima de N dias (Donchian) entra; minima de `SAIDA` dias sai.
  * Filtro de regime: so fica comprado se BTC > media de FILTRO_BTC dias.
  * Peso = 1/n_ativas, escalado por VOL_ALVO / vol_estimada (teto 1 = sem alavancagem).
  * Banda de rebalanceamento: so opera se o peso-alvo mudou mais de BANDA (ou zerou).

Modos (variavel MODO):
  * simulacao  -> le candles de um CSV local, nao fala com a Binance (validacao).
  * teste      -> dados do mercado real, ORDENS na conta de teste (testnet.binance.vision).
  * real       -> dados e ordens na Binance de verdade.
"""
import os, sys, time, hmac, hashlib, json, math, logging
from datetime import datetime, timezone
from urllib.parse import urlencode

import numpy as np
import pandas as pd

try:
    import requests
except ImportError:  # modo simulacao nao precisa
    requests = None

# ---------------- configuracao (variaveis de ambiente) ----------------
MODO = os.getenv("MODO", "simulacao")
SIMBOLOS = os.getenv("SIMBOLOS", "BTCUSDT,ETHUSDT,BNBUSDT,XRPUSDT,ADAUSDT,SOLUSDT,DOGEUSDT,LINKUSDT,LTCUSDT,AVAXUSDT,DOTUSDT,TRXUSDT").split(",")
MOEDA_CAIXA = os.getenv("MOEDA_CAIXA", "USDT")
SINAL = os.getenv("SINAL", "raghee")  # raghee (onda 34 EMA + relogio) | donchian
ANG_MIN = float(os.getenv("ANG_MIN", "0.17"))
ROMPE = int(os.getenv("ROMPE", "10"))
N = int(os.getenv("N", "55"))
SAIDA = int(os.getenv("SAIDA", "20"))
FILTRO_BTC = int(os.getenv("FILTRO_BTC", "150"))
VOL_ALVO = float(os.getenv("VOL_ALVO", "0.35"))
VOL_DIAS = int(os.getenv("VOL_DIAS", "30"))
BANDA = float(os.getenv("BANDA", "0.10"))
MAX_BRUTO = float(os.getenv("MAX_BRUTO", "1.0"))
CAPITAL_MAX = float(os.getenv("CAPITAL_MAX", "0"))  # 0 = usa tudo que tem na conta; >0 limita o valor operado
ORDEM_MINIMA = float(os.getenv("ORDEM_MINIMA", "12"))  # em USDT; abaixo disso nao vale a taxa
PASTA_ESTADO = os.getenv("PASTA_ESTADO", "./estado")
CSV_SIMULACAO = os.getenv("CSV_SIMULACAO", "")
DATA_SIMULACAO = os.getenv("DATA_SIMULACAO", "")  # ex. 2026-09-26 (dia "hoje" da simulacao)

DADOS_URL = "https://api.binance.com"
ORDENS_URL = {"teste": "https://testnet.binance.vision", "real": "https://api.binance.com"}.get(MODO, "")
API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")

os.makedirs(PASTA_ESTADO, exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout),
                              logging.FileHandler(os.path.join(PASTA_ESTADO, "robo.log"))])
log = logging.getLogger("robo")


# ---------------- cliente Binance minimo ----------------
class Binance:
    def __init__(self, base, key="", secret=""):
        self.base, self.key, self.secret = base, key, secret
        self.s = requests.Session()
        self.s.headers["X-MBX-APIKEY"] = key
        self.desvio = 0
        try:
            self.desvio = self.get("/api/v3/time")["serverTime"] - int(time.time() * 1000)
        except Exception as e:
            log.warning(f"nao sincronizou relogio: {e}")

    def _req(self, metodo, caminho, params=None, assinado=False):
        params = dict(params or {})
        if assinado:
            params["timestamp"] = int(time.time() * 1000) + self.desvio
            params["recvWindow"] = 10000
            q = urlencode(params, doseq=True)
            params["signature"] = hmac.new(self.secret.encode(), q.encode(), hashlib.sha256).hexdigest()
        for tentativa in range(4):
            r = self.s.request(metodo, self.base + caminho, params=params, timeout=30)
            if r.status_code in (418, 429):
                espera = int(r.headers.get("Retry-After", "10"))
                log.warning(f"limite de requisicoes; esperando {espera}s"); time.sleep(espera); continue
            if r.status_code >= 500 and tentativa < 3:
                time.sleep(3); continue
            if r.status_code != 200:
                raise RuntimeError(f"{metodo} {caminho} -> {r.status_code} {r.text[:300]}")
            return r.json()
        raise RuntimeError("esgotou tentativas")

    def get(self, caminho, params=None, assinado=False):
        return self._req("GET", caminho, params, assinado)

    def post(self, caminho, params=None):
        return self._req("POST", caminho, params, True)

    def klines_diarios(self, simbolo, dias=400):
        k = self.get("/api/v3/klines", {"symbol": simbolo, "interval": "1d", "limit": min(dias, 1000)})
        df = pd.DataFrame(k).iloc[:, :7]
        df.columns = ["open_time", "open", "high", "low", "close", "volume", "close_time"]
        df["ts"] = pd.to_datetime(df.open_time, unit="ms", utc=True)
        df = df.set_index("ts")[["open", "high", "low", "close", "close_time"]].astype(float)
        # descarta o candle do dia em curso (ainda nao fechou)
        agora = int(time.time() * 1000) + self.desvio
        df = df[df.close_time < agora]
        return df[["open", "high", "low", "close"]]


# ---------------- estrategia (identica ao backtest) ----------------
def sinal_donchian(serie, n, saida):
    alto = serie.rolling(n).max().shift(1)
    baixo = serie.rolling(saida).min().shift(1)
    p = 0.0; out = np.zeros(len(serie))
    pv, av, bv = serie.values, alto.values, baixo.values
    for i in range(len(pv)):
        if np.isnan(av[i]) or np.isnan(pv[i]):
            out[i] = 0.0; continue
        if p == 0 and pv[i] > av[i]:
            p = 1.0
        elif p > 0 and pv[i] < bv[i]:
            p = 0.0
        out[i] = p
    return pd.Series(out, index=serie.index)


def _atr(d, n=14):
    tr = pd.concat([d.high - d.low, (d.high - d.close.shift()).abs(), (d.low - d.close.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def sinal_raghee(d, ang_min=None, rompe=None):
    """Raghee Horner: onda de 3 EMAs de 34 (maxima, fechamento, minima). 'Relogio' = inclinacao da EMA do
    fechamento em 5 dias, em ATRs por dia; > ang_min equivale a '12 as 2 horas'. Entra quando a onda aponta
    para cima, o fechamento esta acima da onda e rompe a maxima de `rompe` dias; sai ao fechar abaixo da
    EMA da minima ou se a onda virar para baixo."""
    ang_min = ANG_MIN if ang_min is None else ang_min; rompe = ROMPE if rompe is None else rompe
    hi = d.high.ewm(span=34, adjust=False).mean(); mid = d.close.ewm(span=34, adjust=False).mean(); lo = d.low.ewm(span=34, adjust=False).mean()
    ang = (mid - mid.shift(5)) / (5 * _atr(d))
    entrar = ((ang > ang_min) & (d.close > hi) & (d.close > d.high.rolling(rompe).max().shift(1))).fillna(False).values
    sair = ((d.close < lo) | (ang < -ang_min)).fillna(False).values
    p = 0.0; out = np.zeros(len(d))
    for i in range(len(d)):
        if p == 0 and entrar[i]:
            p = 1.0
        elif p == 1 and sair[i]:
            p = 0.0
        out[i] = p
    return pd.Series(out, index=d.index)


def pesos_alvo(fechamentos: pd.DataFrame, ohlc: dict = None):
    """fechamentos: DataFrame diario (colunas = simbolos), ultimo dia = ultimo candle FECHADO.
    Devolve o peso-alvo bruto de cada moeda para o proximo dia (antes da banda)."""
    ret = fechamentos.pct_change()
    if SINAL == "raghee":
        sinal = pd.DataFrame({c: sinal_raghee(ohlc[c]) for c in fechamentos.columns}).reindex(fechamentos.index).fillna(0.0)
    else:
        sinal = pd.DataFrame({c: sinal_donchian(fechamentos[c], N, SAIDA) for c in fechamentos.columns})
    sinal = sinal.where(fechamentos.notna(), 0.0)
    if FILTRO_BTC:
        btc = fechamentos["BTCUSDT"]
        regime = (btc > btc.rolling(FILTRO_BTC).mean()).astype(float)
        sinal = sinal.mul(regime, axis=0)
    n_ativas = sinal.sum(axis=1).replace(0, np.nan)
    w = sinal.div(n_ativas, axis=0).fillna(0.0)
    vol_ativos = ret.rolling(VOL_DIAS).std() * np.sqrt(365)
    vol_est = (w * vol_ativos).sum(axis=1) * 0.8
    esc = (VOL_ALVO / vol_est).clip(upper=MAX_BRUTO).fillna(0.0)
    w = w.mul(esc, axis=0)
    return w.iloc[-1], {"n_ativas": float(sinal.iloc[-1].sum()), "escala": float(esc.iloc[-1])}


def aplicar_banda(alvo: pd.Series, atual: pd.Series):
    """Regra do backtest: so muda se |alvo-atual| > BANDA*max(atual, 0.02) ou se o alvo zerou."""
    novo = atual.copy()
    for c in alvo.index:
        a, p = float(alvo[c]), float(atual.get(c, 0.0))
        if (a == 0 and p != 0) or abs(a - p) > BANDA * max(p, 0.02):
            novo[c] = a
    return novo


# ---------------- estado local ----------------
ARQ_PESOS = os.path.join(PASTA_ESTADO, "pesos_atuais.json")


def ler_pesos_atuais():
    if os.path.exists(ARQ_PESOS):
        return pd.Series(json.load(open(ARQ_PESOS)), dtype=float)
    return pd.Series(dtype=float)


def gravar_pesos_atuais(w):
    json.dump({k: float(v) for k, v in w.items()}, open(ARQ_PESOS, "w"), indent=1)


def registrar_diario(linha: dict):
    arq = os.path.join(PASTA_ESTADO, "diario.csv")
    pd.DataFrame([linha]).to_csv(arq, mode="a", header=not os.path.exists(arq), index=False)


# ---------------- execucao ----------------
def arredondar_passo(qtd, passo):
    return math.floor(qtd / passo) * passo


def executar_na_binance(alvo_pesos: pd.Series, precos: dict):
    cli = Binance(ORDENS_URL, API_KEY, API_SECRET)
    info = cli.get("/api/v3/exchangeInfo", {"symbols": json.dumps([s for s in alvo_pesos.index], separators=(",", ":"))})
    filtros = {}
    for s in info["symbols"]:
        f = {x["filterType"]: x for x in s["filters"]}
        filtros[s["symbol"]] = dict(
            passo=float(f["LOT_SIZE"]["stepSize"]),
            min_qtd=float(f["LOT_SIZE"]["minQty"]),
            min_valor=float(f.get("NOTIONAL", f.get("MIN_NOTIONAL", {"minNotional": "5"}))["minNotional"]),
            ativo=s["status"] == "TRADING", base=s["baseAsset"])
    conta = cli.get("/api/v3/account", assinado=True)
    saldos = {b["asset"]: float(b["free"]) for b in conta["balances"]}
    caixa = saldos.get(MOEDA_CAIXA, 0.0)
    valor_pos = {}
    for s in alvo_pesos.index:
        base = filtros.get(s, {}).get("base", s.replace(MOEDA_CAIXA, ""))
        valor_pos[s] = saldos.get(base, 0.0) * precos[s]
    patrimonio = caixa + sum(valor_pos.values())
    capital = patrimonio if CAPITAL_MAX <= 0 else min(patrimonio, CAPITAL_MAX)
    log.info(f"patrimonio {patrimonio:.2f} {MOEDA_CAIXA} (caixa {caixa:.2f}); capital operado {capital:.2f}")

    ordens = []
    # 1) vendas primeiro (liberam caixa)
    for s in alvo_pesos.index:
        if s not in filtros or not filtros[s]["ativo"]:
            log.warning(f"{s} indisponivel neste ambiente; ignorado"); continue
        alvo_valor = capital * float(alvo_pesos[s])
        delta = alvo_valor - valor_pos[s]
        if delta < -ORDEM_MINIMA:
            qtd = arredondar_passo(min(-delta / precos[s], saldos.get(filtros[s]["base"], 0.0)), filtros[s]["passo"])
            if qtd >= filtros[s]["min_qtd"] and qtd * precos[s] >= filtros[s]["min_valor"]:
                ordens.append(("SELL", s, {"quantity": f"{qtd:.8f}".rstrip("0").rstrip(".")}))
    # 2) compras
    for s in alvo_pesos.index:
        if s not in filtros or not filtros[s]["ativo"]:
            continue
        alvo_valor = capital * float(alvo_pesos[s])
        delta = alvo_valor - valor_pos[s]
        if delta > ORDEM_MINIMA and delta >= filtros[s]["min_valor"]:
            ordens.append(("BUY", s, {"quoteOrderQty": f"{delta:.2f}"}))

    executadas = []
    for lado, s, p in ordens:
        try:
            r = cli.post("/api/v3/order", {"symbol": s, "side": lado, "type": "MARKET", **p})
            preenchido = float(r.get("cummulativeQuoteQty", 0))
            log.info(f"ORDEM {lado} {s} {p} -> {r.get('status')} {preenchido:.2f} {MOEDA_CAIXA}")
            executadas.append((lado, s, preenchido))
        except Exception as e:
            log.error(f"falhou {lado} {s} {p}: {e}")
    return patrimonio, executadas


def main():
    hoje = datetime.now(timezone.utc)
    log.info(f"=== robo iniciado | modo={MODO} | sinal={SINAL} ang_min={ANG_MIN} rompe={ROMPE} | N={N} saida={SAIDA} filtro={FILTRO_BTC} vol_alvo={VOL_ALVO} ===")

    if MODO == "simulacao":
        df = pd.read_csv(CSV_SIMULACAO)
        df["ts"] = pd.to_datetime(df.open_time, unit="ms", utc=True)
        ohlc = {}
        for s in SIMBOLOS:
            x = df[df.symbol == s].set_index("ts").sort_index()
            d = x.resample("1D").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")).dropna()
            if DATA_SIMULACAO:
                d = d[d.index <= pd.Timestamp(DATA_SIMULACAO, tz="UTC")]
            if len(d):
                ohlc[s] = d
        fech = pd.DataFrame({s: ohlc[s].close for s in ohlc}).ffill().tail(max(N, FILTRO_BTC, VOL_DIAS) + 50)
        ohlc = {s: ohlc[s].reindex(fech.index) for s in ohlc}
    else:
        if not API_KEY or not API_SECRET:
            log.error("faltam BINANCE_API_KEY / BINANCE_API_SECRET"); sys.exit(2)
        dados = Binance(DADOS_URL)
        ohlc = {}
        for s in SIMBOLOS:
            try:
                ohlc[s] = dados.klines_diarios(s, max(N, FILTRO_BTC, VOL_DIAS) + 60)
            except Exception as e:
                log.warning(f"sem dados para {s}: {e}")
        fech = pd.DataFrame({s: ohlc[s].close for s in ohlc}).ffill()
        ohlc = {s: ohlc[s].reindex(fech.index) for s in ohlc}

    ultimo_dia = fech.index[-1].date()
    alvo_bruto, extra = pesos_alvo(fech, ohlc)
    atual = ler_pesos_atuais().reindex(alvo_bruto.index).fillna(0.0)
    alvo = aplicar_banda(alvo_bruto, atual)
    precos = fech.iloc[-1].to_dict()

    log.info(f"ultimo candle fechado: {ultimo_dia} | moedas com sinal: {extra['n_ativas']:.0f} | escala vol: {extra['escala']:.2f}")
    log.info("pesos-alvo: " + ", ".join(f"{k} {v:.2%}" for k, v in alvo.items() if v > 0) or "pesos-alvo: 100% em caixa")
    mudou = (alvo - atual).abs() > 1e-9
    if not mudou.any():
        log.info("nada a fazer hoje (dentro da banda)")
    else:
        log.info("mudancas: " + ", ".join(f"{k} {atual[k]:.2%} -> {alvo[k]:.2%}" for k in alvo.index[mudou]))

    patrimonio, executadas = (float("nan"), [])
    if MODO in ("teste", "real") and mudou.any():
        patrimonio, executadas = executar_na_binance(alvo, precos)
    elif MODO in ("teste", "real"):
        cli = Binance(ORDENS_URL, API_KEY, API_SECRET)
        conta = cli.get("/api/v3/account", assinado=True)
        saldos = {b["asset"]: float(b["free"]) for b in conta["balances"]}
        patrimonio = saldos.get(MOEDA_CAIXA, 0.0) + sum(saldos.get(s.replace(MOEDA_CAIXA, ""), 0.0) * precos[s] for s in alvo.index)

    gravar_pesos_atuais(alvo)
    registrar_diario({"data": str(hoje.date()), "candle": str(ultimo_dia), "modo": MODO, "patrimonio": patrimonio,
                      "exposicao": float(alvo.sum()), "n_ativas": extra["n_ativas"],
                      "pesos": json.dumps({k: round(float(v), 4) for k, v in alvo.items() if v > 0}),
                      "ordens": json.dumps(executadas)})
    log.info(f"=== fim | patrimonio {patrimonio} | exposicao {alvo.sum():.0%} ===")


if __name__ == "__main__":
    main()
