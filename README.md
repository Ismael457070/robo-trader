# Robô de tendência — cripto spot (Binance)

Estratégia validada em backtest 2018–2026 (ver pasta `laboratorio/`): rompimento de máxima de 55 dias,
saída na mínima de 20 dias, só comprado, só quando o BTC está acima da média de 150 dias,
tamanho por volatilidade (alvo 35% a.a.), sem alavancagem. Roda **uma vez por dia** às 00:05 UTC.

## Arquivos
- `robo.py` — o robô (cálculo dos pesos + ordens). Idêntico ao backtest (validado dia a dia, diferença zero).
- `agendador.py` — mantém o contêiner vivo e dispara o robô diariamente.
- `Dockerfile` — para o Coolify.
- `.env.example` — variáveis de ambiente.
- `estado/` (volume) — `robo.log`, `diario.csv` (uma linha por dia: patrimônio, exposição, pesos, ordens) e `pesos_atuais.json`.

## Como colocar no ar (Coolify)
1. Criar chaves de API da **conta de teste** em https://testnet.binance.vision (entra com GitHub; "Generate HMAC_SHA256 Key").
   A conta de teste já vem com saldo fictício.
2. Subir esta pasta num repositório GitHub (privado).
3. Coolify → New Resource → Public/Private Repository → Build Pack: **Dockerfile**.
4. Environment Variables: copiar de `.env.example` e preencher `BINANCE_API_KEY` / `BINANCE_API_SECRET` (marcar como secretas).
5. Storage: volume `/app/estado`.
6. Deploy. Nos logs deve aparecer `=== robo iniciado | modo=teste ...` e os pesos-alvo.

## Passar para dinheiro real (depois de ≥30 dias de teste)
- Criar chave na Binance real com permissão **apenas "Enable Spot & Margin Trading"** (sem saque), restrita ao IP do servidor.
- Trocar `MODO=real`, colocar as chaves reais, definir `CAPITAL_MAX` com valor pequeno no início.
- Deixar a carteira spot só com USDT (o robô compra o resto).

## Modo simulação (sem Binance)
`MODO=simulacao CSV_SIMULACAO=dados.csv DATA_SIMULACAO=2026-09-25 python robo.py` — calcula os pesos-alvo a partir do CSV.

## Riscos (leia)
Backtest não é garantia. Espere anos negativos (−10 a −20%) e uma queda de 40–50% em algum momento.
A conta de teste tem liquidez e preços diferentes da real; os resultados de 30 dias servem para provar
que o robô executa direito, não para provar lucro.
