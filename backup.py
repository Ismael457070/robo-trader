"""Segunda copia do estado do robo, fora do volume do Coolify.

O volume /app/estado morre se o servidor ou o recurso for recriado. Com
BACKUP_GITHUB_TOKEN (permissao de escrita no repositorio privado), cada
execucao publica os CSVs e o JSON de estado no ramo `arquivo`.

Sem o token, grava so manifesto.json dentro do proprio estado e segue.
Nunca imprime o token. Nunca envia .env nem chave de API.
"""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen

PASTA = os.getenv("PASTA_ESTADO", "./estado")
REPO = os.getenv("BACKUP_REPOSITORIO", "Ismael457070/robo-trader-arquivo")
RAMO = os.getenv("BACKUP_RAMO", "arquivo")
TOKEN = os.getenv("BACKUP_GITHUB_TOKEN", "")
ARQUIVOS = ("diario.csv", "pesos_atuais.json", "sombra.json", "sombra.csv", "sombra_hist.csv")
API = "https://api.github.com"


def api(metodo, caminho, corpo=None):
    dados = None if corpo is None else json.dumps(corpo).encode()
    req = Request(API + caminho, data=dados, method=metodo)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "robo-trader-backup")
    if dados:
        req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=60) as r:
            bruto = r.read()
            return r.status, json.loads(bruto.decode() or "null")
    except HTTPError as e:
        bruto = e.read().decode()
        try:
            parsed = json.loads(bruto) if bruto else {}
        except json.JSONDecodeError:
            parsed = {"message": bruto[:300]}
        return e.code, parsed


def manifesto(presentes):
    agora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    itens = []
    for nome in presentes:
        conteudo = open(os.path.join(PASTA, nome), "rb").read()
        itens.append({"arquivo": nome, "bytes": len(conteudo),
                      "sha256": hashlib.sha256(conteudo).hexdigest()})
    doc = {"quando": agora, "repositorio": REPO, "ramo": RAMO, "arquivos": itens}
    os.makedirs(PASTA, exist_ok=True)
    with open(os.path.join(PASTA, "manifesto.json"), "w") as f:
        json.dump(doc, f, indent=2)
    return doc


def blob(conteudo: bytes):
    codigo, resp = api("POST", f"/repos/{REPO}/git/blobs",
                       {"content": conteudo.decode("utf-8", "replace"), "encoding": "utf-8"})
    if codigo >= 300:
        raise RuntimeError(f"blob {codigo} {resp.get('message', resp)}")
    return resp["sha"]


def enviar(doc):
    codigo, repo = api("GET", f"/repos/{REPO}")
    if codigo == 404:
        print(f"[backup] repositorio {REPO} inacessivel ({codigo}). Estado ficou so no volume.", flush=True)
        return
    if codigo < 300 and not repo.get("private", True):
        print(f"[backup] {REPO} e publico; nao envio patrimonio para repositorio publico.", flush=True)
        return

    nomes = [n for n in (*ARQUIVOS, "manifesto.json") if os.path.exists(os.path.join(PASTA, n))]
    codigo, ref = api("GET", f"/repos/{REPO}/git/ref/heads/{RAMO}")
    base = ref["object"]["sha"] if codigo == 200 else None
    arvore_base = None
    pais = []
    if base:
        codigo, commit = api("GET", f"/repos/{REPO}/git/commits/{base}")
        if codigo >= 300:
            raise RuntimeError(f"commit {codigo}")
        arvore_base = commit["tree"]["sha"]
        pais = [base]

    tree = []
    for nome in nomes:
        conteudo = open(os.path.join(PASTA, nome), "rb").read()
        tree.append({"path": f"estado/{nome}", "mode": "100644", "type": "blob", "sha": blob(conteudo)})
    corpo_arvore = {"tree": tree}
    if arvore_base:
        corpo_arvore["base_tree"] = arvore_base
    codigo, nova = api("POST", f"/repos/{REPO}/git/trees", corpo_arvore)
    if codigo >= 300:
        raise RuntimeError(f"tree {codigo} {nova.get('message', nova)}")
    codigo, commit = api("POST", f"/repos/{REPO}/git/commits", {
        "message": f"espelho do estado {doc['quando']}",
        "tree": nova["sha"],
        "parents": pais,
    })
    if codigo >= 300:
        raise RuntimeError(f"commit {codigo} {commit.get('message', commit)}")
    if base:
        codigo, resp = api("PATCH", f"/repos/{REPO}/git/refs/heads/{RAMO}", {"sha": commit["sha"]})
    else:
        codigo, resp = api("POST", f"/repos/{REPO}/git/refs",
                           {"ref": f"refs/heads/{RAMO}", "sha": commit["sha"]})
    if codigo >= 300:
        raise RuntimeError(f"ref {codigo} {resp.get('message', resp)}")
    print(f"[backup] {len(nomes)} arquivos em {REPO}@{RAMO} {commit['sha'][:8]}", flush=True)


def main():
    os.makedirs(PASTA, exist_ok=True)
    presentes = [n for n in ARQUIVOS if os.path.exists(os.path.join(PASTA, n))]
    doc = manifesto(presentes)
    if not TOKEN:
        print("[backup] sem BACKUP_GITHUB_TOKEN; copia remota nao feita", flush=True)
        return
    if not presentes:
        print("[backup] estado ainda vazio; nada para enviar", flush=True)
        return
    try:
        enviar(doc)
    except Exception as e:
        print(f"[backup] falhou: {e}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
