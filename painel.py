"""Painel web do robo — serve na porta 3000, so biblioteca padrao.
Protegido por senha simples (variavel SENHA_PAINEL; usuario qualquer, ex. 'ismael')."""
import os, json, base64, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen, Request
import pandas as pd

PASTA = os.getenv("PASTA_ESTADO", "/app/estado")
SENHA = os.getenv("SENHA_PAINEL", "")
MODO = os.getenv("MODO", "teste")
MOEDA = os.getenv("MOEDA_CAIXA", "USDT")
DADOS_URL = "https://api.binance.com"
_cache = {"t": 0, "precos": {}}


def precos_agora(simbolos):
    if time.time() - _cache["t"] < 60 and _cache["precos"]:
        return _cache["precos"]
    try:
        q = json.dumps(sorted(simbolos), separators=(",", ":"))
        with urlopen(Request(DADOS_URL + "/api/v3/ticker/price?symbols=" + q), timeout=10) as r:
            _cache["precos"] = {x["symbol"]: float(x["price"]) for x in json.load(r)}
            _cache["t"] = time.time()
    except Exception:
        pass
    return _cache["precos"]


def fmt_preco(v):
    return f"{v:,.4f}" if v is not None else "—"


def dados():
    arq = os.path.join(PASTA, "diario.csv")
    d = pd.read_csv(arq) if os.path.exists(arq) else pd.DataFrame()
    pesos = {}
    p = os.path.join(PASTA, "pesos_atuais.json")
    if os.path.exists(p):
        pesos = {k: v for k, v in json.load(open(p)).items() if v > 0}
    log = ""
    l = os.path.join(PASTA, "robo.log")
    if os.path.exists(l):
        with open(l, "rb") as f:
            f.seek(0, 2); tam = f.tell(); f.seek(max(0, tam - 20000))
            log = f.read().decode("utf-8", "ignore")
    return d, pesos, log


def html():
    d, pesos, log = dados()
    if len(d):
        d = d[d.patrimonio.notna()]
    serie = [(str(r.data), float(r.patrimonio)) for r in d.itertuples()] if len(d) else []
    inicial = serie[0][1] if serie else None
    atual = serie[-1][1] if serie else None
    var = (atual / inicial - 1) * 100 if serie and inicial else 0.0
    ordens = []
    for r in d.tail(15).itertuples():
        for o in json.loads(r.ordens or "[]"):
            ordens.append((r.data, o[0], o[1], o[2]))
    ordens = ordens[::-1][:30]
    precos = precos_agora(list(pesos.keys())) if pesos else {}
    # curva SVG
    W, H = 720, 220
    path = ""
    if len(serie) >= 2:
        ys = [v for _, v in serie]; lo, hi = min(ys), max(ys)
        if hi == lo: hi = lo + 1
        pts = [(20 + i * (W - 40) / (len(serie) - 1), H - 20 - (v - lo) * (H - 40) / (hi - lo)) for i, (_, v) in enumerate(serie)]
        path = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    linhas_pos = "".join(
        f"<tr><td>{s}</td><td class=num>{w*100:.1f}%</td><td class=num>{fmt_preco(precos.get(s))}</td></tr>"
        for s, w in sorted(pesos.items(), key=lambda x: -x[1]))
    linhas_ord = "".join(
        f"<tr><td>{dt}</td><td>{'Compra' if lado=='BUY' else 'Venda'}</td><td>{s}</td><td class=num>{v:,.2f}</td></tr>"
        for dt, lado, s, v in ordens)
    linhas_dia = "".join(
        f"<tr><td>{r.data}</td><td class=num>{r.patrimonio:,.2f}</td><td class=num>{r.exposicao*100:.0f}%</td><td class=num>{int(r.n_ativas)}</td><td>{len(json.loads(r.ordens or '[]'))}</td></tr>"
        for r in d.tail(31).iloc[::-1].itertuples()) if len(d) else ""
    cor_var = "#0ca30c" if var >= 0 else "#d03b3b"
    return f"""<!doctype html><html lang=pt-BR><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Robô Trader</title>
<style>
:root{{--bg:#fcfcfb;--card:#fff;--tx:#0b0b0b;--tx2:#52514e;--linha:#e6e5e1;--s1:#2a78d6}}
@media(prefers-color-scheme:dark){{:root{{--bg:#1a1a19;--card:#242422;--tx:#fff;--tx2:#c3c2b7;--linha:#383835;--s1:#3987e5}}}}
body{{margin:0;background:var(--bg);color:var(--tx);font:15px/1.45 system-ui,Segoe UI,Roboto,sans-serif}}
main{{max-width:960px;margin:0 auto;padding:16px}}
h1{{font-size:20px;margin:8px 0 16px}} h2{{font-size:15px;color:var(--tx2);font-weight:600;margin:0 0 8px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:16px}}
.card{{background:var(--card);border:1px solid var(--linha);border-radius:10px;padding:14px}}
.big{{font-size:28px;font-weight:700;letter-spacing:-.5px}} .sub{{color:var(--tx2);font-size:13px}}
table{{width:100%;border-collapse:collapse;font-size:14px}} td,th{{padding:6px 8px;border-bottom:1px solid var(--linha);text-align:left}}
th{{color:var(--tx2);font-weight:600;font-size:12px;text-transform:uppercase}} .num{{text-align:right;font-variant-numeric:tabular-nums}}
pre{{font-size:12px;overflow:auto;max-height:320px;background:var(--bg);padding:10px;border-radius:8px;white-space:pre-wrap}}
.tag{{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;background:var(--linha);color:var(--tx2)}}
svg text{{fill:var(--tx2);font-size:11px}}
</style></head><body><main>
<h1>Robô Trader <span class=tag>{'CONTA DE TESTE' if MODO=='teste' else 'CONTA REAL'}</span></h1>
<div class=grid>
 <div class=card><h2>Patrimônio</h2><div class=big>{(atual or 0):,.0f} <small>{MOEDA}</small></div><div class=sub>início {(inicial or 0):,.0f}</div></div>
 <div class=card><h2>Resultado desde o início</h2><div class=big style="color:{cor_var}">{var:+.2f}%</div><div class=sub>{len(serie)} dias registrados</div></div>
 <div class=card><h2>Exposição</h2><div class=big>{sum(pesos.values())*100:.0f}%</div><div class=sub>{len(pesos)} moedas compradas · resto em {MOEDA}</div></div>
</div>
<div class=card style="margin-bottom:16px"><h2>Curva de patrimônio</h2>
<svg viewBox="0 0 {W} {H}" width="100%" preserveAspectRatio="none" style="height:220px">
<line x1=20 y1={H-20} x2={W-20} y2={H-20} stroke="var(--linha)"/>
{f'<path d="{path}" fill="none" stroke="var(--s1)" stroke-width="2" stroke-linejoin="round"/>' if path else f'<text x="{W/2}" y="{H/2}" text-anchor="middle">Ainda sem dias suficientes (a curva aparece a partir do 2º dia)</text>'}
{f'<text x=20 y={H-4}>{serie[0][0]}</text><text x={W-20} y={H-4} text-anchor="end">{serie[-1][0]}</text>' if serie else ''}
</svg></div>
<div class=grid style="grid-template-columns:1fr 1fr">
 <div class=card><h2>Posições atuais</h2><table><tr><th>Moeda</th><th class=num>Peso</th><th class=num>Preço agora</th></tr>{linhas_pos or '<tr><td colspan=3>100% em caixa</td></tr>'}</table></div>
 <div class=card><h2>Últimas ordens</h2><table><tr><th>Dia</th><th>Lado</th><th>Moeda</th><th class=num>{MOEDA}</th></tr>{linhas_ord or '<tr><td colspan=4>Nenhuma ainda</td></tr>'}</table></div>
</div>
<div class=card style="margin:16px 0"><h2>Dia a dia (últimos 31)</h2><table><tr><th>Dia</th><th class=num>Patrimônio</th><th class=num>Exposição</th><th class=num>Moedas c/ sinal</th><th>Ordens</th></tr>{linhas_dia}</table></div>
<div class=card><h2>Log do robô (fim)</h2><pre>{log.replace('<','&lt;')}</pre></div>
<p class=sub>Estratégia: Onda 34 EMA de Raghee Horner (relógio ≥ 0,17) + rompimento de 10 dias, só comprado, filtro BTC &gt; média 150d, alvo de volatilidade 35%, sem alavancagem. Roda 1×/dia às 00:05 UTC. Backtest não é garantia de resultado.</p>
</main></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silencia
        pass

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok"); return
        if SENHA:
            auth = self.headers.get("Authorization", "")
            ok = False
            if auth.startswith("Basic "):
                try:
                    ok = base64.b64decode(auth[6:]).decode().split(":", 1)[1] == SENHA
                except Exception:
                    ok = False
            if not ok:
                self.send_response(401); self.send_header("WWW-Authenticate", 'Basic realm="robo"'); self.end_headers(); return
        try:
            corpo = html().encode()
        except Exception as e:
            corpo = f"<pre>erro no painel: {e}</pre>".encode()
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(corpo)


def servir(porta=3000):
    ThreadingHTTPServer(("0.0.0.0", porta), H).serve_forever()


def iniciar_em_segundo_plano():
    threading.Thread(target=servir, daemon=True).start()


if __name__ == "__main__":
    servir()
