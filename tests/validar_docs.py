"""Confere se a documentação gerada bate com os JSONs das Logic Apps (antialucinação).

Para cada Logic App:
  - a tabela "Ações" tem exatamente as ações do JSON (nenhuma inventada, nenhuma faltando);
  - o gatilho documentado é o do JSON;
  - toda ação aparece no "Passo a passo";
  - os achados batem com o gabarito (logicapps/achados_esperados.json) nos exemplos,
    ou com a leitura do JSON numa Logic App real;
  - a seção "Conexões" tem exatamente as conexões do JSON ($connections);
  - "Dependências" e o runbook só citam Logic Apps e ações que existem;
  - o arquivo não é antigo (gerado há menos de 10 minutos).

Uso:  python tests/validar_docs.py
"""
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import doc_logicapp as dl  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def todas_acoes(actions):
    out = set()
    for n, a in (actions or {}).items():
        out.add(n)
        out |= todas_acoes(a.get("actions"))
        out |= todas_acoes((a.get("else") or {}).get("actions"))
        for c in (a.get("cases") or {}).values():
            out |= todas_acoes(c.get("actions"))
        out |= todas_acoes((a.get("default") or {}).get("actions"))
    return out


def secao(texto, titulo):
    partes = texto.split(f"## {titulo}\n", 1)
    return partes[1].split("\n## ", 1)[0] if len(partes) > 1 else ""


def linhas_tabela(bloco, col):
    out = []
    for l in bloco.splitlines():
        if l.startswith("|") and not set(l.replace("|", "").strip()) <= set("-: "):
            cols = [c.strip() for c in l.strip().strip("|").split("|")]
            if len(cols) > col:
                out.append(cols[col])
    return out[1:]  # sem cabeçalho


gabarito = json.loads((ROOT / "logicapps" / "achados_esperados.json").read_text(encoding="utf-8"))
erros, oks = [], 0
for nome in dl.nomes():
    doc = dl.OUT / f"{nome}.md"
    if not doc.exists():
        erros.append(f"FALTOU      documentação de '{nome}' não existe")
        continue
    texto = doc.read_text(encoding="utf-8")
    if (time.time() - doc.stat().st_mtime) / 60 > 10:
        print(f"ATENÇÃO     {doc.name} foi gerado há mais de 10 min (se o agente disse que acabou de gerar, não gerou)")
    d, _, _ = dl.carregar(nome)
    reais = todas_acoes(d.get("actions"))
    documentadas = set(linhas_tabela(secao(texto, "Ações"), 1))
    for a in sorted(documentadas - reais):
        erros.append(f"INVENTADO   {nome}: ação '{a}' não existe no JSON")
    for a in sorted(reais - documentadas):
        erros.append(f"FALTOU      {nome}: ação '{a}' não foi documentada")
    gat_real = next(iter(d.get("triggers") or {}), "")
    if gat_real not in linhas_tabela(secao(texto, "Gatilho"), 0):
        erros.append(f"GATILHO     {nome}: gatilho '{gat_real}' não aparece na documentação")
    achados_doc = set(linhas_tabela(secao(texto, "Achados de boas práticas"), 1))
    if any(g["logicapp"] == nome for g in gabarito):  # exemplos: compara com o gabarito escrito à mão
        esperados = {g["regra"] for g in gabarito if g["logicapp"] == nome}
    else:  # Logic App real: compara com a leitura do JSON (a página não pode inventar nem esconder achado)
        esperados = {r for r, _, _ in dl.analisar(nome)["achados"]}
    passos = set(re.findall(r"^#{3,6} \S+\. (\S+) — ", secao(texto, "Passo a passo") or texto, re.M))
    for a in sorted(reais - passos):
        erros.append(f"FALTOU      {nome}: ação '{a}' não aparece no passo a passo")
    _, params, _ = dl.carregar(nome)
    conns = set(((params or {}).get("$connections") or {}).get("value") or {})
    conns_doc = set(linhas_tabela(secao(texto, "Conexões"), 0))
    for c in sorted(conns_doc - conns):
        erros.append(f"INVENTADO   {nome}: conexão '{c}' não existe no JSON")
    for c in sorted(conns - conns_doc):
        erros.append(f"FALTOU      {nome}: conexão '{c}' não foi documentada")
    citadas = set(re.findall(r"\[\[([^\]]+)\]\]", secao(texto, "Dependências") + secao(texto, "Runbook: quando falhar")))
    for la in sorted(citadas - set(dl.nomes())):
        erros.append(f"INVENTADO   {nome}: cita a Logic App '{la}', que não existe")
    repete = re.search(r"reenviar repete:\*\* (.+)", texto)
    for a in sorted(set(re.findall(r"`([^`]+)` \(", repete.group(1))) - reais if repete else []):
        erros.append(f"INVENTADO   {nome}: o runbook cita a ação '{a}', que não existe")
    for r in sorted(esperados - achados_doc):
        erros.append(f"ACHADO      {nome}: faltou o achado {r}")
    for r in sorted(achados_doc - esperados):
        erros.append(f"ACHADO      {nome}: achado {r} não está no gabarito (falso alarme)")
    if not any(e.split()[1].rstrip(":") == nome for e in erros if len(e.split()) > 1):
        print(f"OK          {nome}: {len(reais)} ações, gatilho '{gat_real}', {len(esperados)} achado(s)")
        oks += 1

for e in erros:
    print(e)
print("\nRESULTADO:", "DOCUMENTAÇÃO CONFIÁVEL" if not erros else f"REPROVADA ({len(erros)} problema(s))")
sys.exit(0 if not erros else 1)
