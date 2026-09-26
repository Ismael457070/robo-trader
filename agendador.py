"""Mantem o contêiner vivo e roda o robo todo dia as HORA_UTC:MINUTO_UTC (padrao 00:05 UTC).
Tambem roda uma vez ao subir, se RODAR_AO_SUBIR=1 (padrao 1) — a banda/estado impede giro repetido."""
import os, time, subprocess, sys
from datetime import datetime, timezone, timedelta
import painel
painel.iniciar_em_segundo_plano()  # painel web na porta 3000

HORA = int(os.getenv("HORA_UTC", "0"))
MINUTO = int(os.getenv("MINUTO_UTC", "5"))


def rodar():
    print(f"[agendador] {datetime.now(timezone.utc):%Y-%m-%d %H:%M} executando robo.py", flush=True)
    subprocess.run([sys.executable, "/app/robo.py"])


if os.getenv("RODAR_AO_SUBIR", "1") == "1":
    rodar()
while True:
    agora = datetime.now(timezone.utc)
    prox = agora.replace(hour=HORA, minute=MINUTO, second=0, microsecond=0)
    if prox <= agora:
        prox += timedelta(days=1)
    espera = (prox - agora).total_seconds()
    print(f"[agendador] proxima execucao {prox:%Y-%m-%d %H:%M} UTC (em {espera/3600:.1f} h)", flush=True)
    time.sleep(espera)
    rodar()
