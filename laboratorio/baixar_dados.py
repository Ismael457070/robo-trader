"""Baixa candles diarios publicos da Binance para laboratorio/dados/.

Nao usa chave. Os arquivos originais do laboratorio nao estavam no Git;
isto reconstroi a materia-prima do backtest (2017 em diante, o que a Binance tiver).
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SIMBOLOS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT",
    "DOGEUSDT", "LINKUSDT", "LTCUSDT", "AVAXUSDT", "DOTUSDT", "TRXUSDT",
]
INICIO = int(datetime(2017, 8, 17, tzinfo=timezone.utc).timestamp() * 1000)
PASTA = Path(__file__).resolve().parent / "dados"
URL = "https://api.binance.com/api/v3/klines"


def klines(simbolo, inicio):
    q = urlencode({"symbol": simbolo, "interval": "1d", "startTime": inicio, "limit": 1000})
    req = Request(URL + "?" + q, headers={"User-Agent": "robo-trader-laboratorio"})
    with urlopen(req, timeout=30) as r:
        return json.load(r)


def baixar(simbolo):
    linhas = []
    inicio = INICIO
    while True:
        try:
            lote = klines(simbolo, inicio)
        except HTTPError as e:
            detalhe = e.read().decode()[:180]
            print(f"{simbolo}: HTTP {e.code} {detalhe}")
            return 0
        if not lote:
            break
        linhas.extend(lote)
        if len(lote) < 1000:
            break
        inicio = int(lote[-1][0]) + 1
        time.sleep(0.15)
    if not linhas:
        print(f"{simbolo}: sem candles")
        return 0
    # descarta o candle do dia em curso (close_time ainda no futuro)
    agora = int(time.time() * 1000)
    linhas = [k for k in linhas if int(k[6]) < agora]
    arq = PASTA / f"{simbolo}.csv"
    with arq.open("w") as f:
        f.write("open_time,open,high,low,close,volume\n")
        for k in linhas:
            f.write(f"{int(k[0])},{k[1]},{k[2]},{k[3]},{k[4]},{k[5]}\n")
    primeiro = datetime.fromtimestamp(linhas[0][0] / 1000, timezone.utc).date()
    ultimo = datetime.fromtimestamp(linhas[-1][0] / 1000, timezone.utc).date()
    print(f"{simbolo}: {len(linhas)} dias ({primeiro} a {ultimo})")
    return len(linhas)


def main():
    PASTA.mkdir(parents=True, exist_ok=True)
    total = 0
    for s in SIMBOLOS:
        total += baixar(s)
        time.sleep(0.15)
    print(f"total: {total} candles em {PASTA}")


if __name__ == "__main__":
    main()
