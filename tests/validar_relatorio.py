"""Confere se o relatório escrito pelo agente bate com os dados (antialucinação).

Verifica a tabela de anomalias do relatório:
  - todos os recursos citados existem nos dados;
  - estão todas as anomalias detectadas, sem faltar nem sobrar;
  - o custo extra de cada uma é o calculado pelas ferramentas.

Uso:  python tests/validar_relatorio.py [caminho do relatório]
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import cost_query  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # acentos corretos no Windows

path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "relatorios" / "relatorio-finops.md"
if not path.exists():
    print(f"Relatório não encontrado: {path}")
    sys.exit(1)
texto = path.read_text(encoding="utf-8")
idade_min = (time.time() - path.stat().st_mtime) / 60
print(f"Arquivo: {path.name} | salvo há {idade_min:.0f} min ({time.strftime('%d/%m %H:%M', time.localtime(path.stat().st_mtime))})")
if idade_min > 10:
    print("ATENÇÃO: o relatório é antigo. Se o agente disse que acabou de gerar, ele NÃO gerou nesta rodada.")

series, meta = cost_query.load()
achados = cost_query._estende_picos(series, cost_query.detectar(series, meta))
esperado = {a["recurso"]: cost_query.brl(cost_query.custo_extra(series, a)) for a in achados}

linhas = [l for l in texto.splitlines() if l.strip().startswith("|")]
citados = {}
for l in linhas:
    cols = [c.strip().strip("`*") for c in l.strip().strip("|").split("|")]
    if not cols or cols[0].lower() in ("recurso", "") or set(cols[0]) <= set("-: "):
        continue
    valor = next((c for c in cols if c.startswith("R$")), "")
    citados[cols[0]] = valor

erros = []
for nome in citados:
    if nome not in series:
        erros.append(f"INVENTADO   recurso '{nome}' não existe nos dados")
for nome, valor in esperado.items():
    if nome not in citados:
        erros.append(f"FALTOU      anomalia em '{nome}' não aparece na tabela")
    elif citados[nome] != valor:
        erros.append(f"VALOR ERRADO '{nome}': relatório diz '{citados[nome]}', o correto é '{valor}'")
for nome in citados:
    if nome in series and nome not in esperado:
        erros.append(f"SOBROU      '{nome}' está na tabela mas não tem anomalia")

for nome in esperado:
    if nome in citados and citados[nome] == esperado[nome]:
        print(f"OK          {nome}: {esperado[nome]}")
for e in erros:
    print(e)
print("\nRESULTADO:", "RELATÓRIO CONFIÁVEL" if not erros else f"REPROVADO ({len(erros)} problema(s))")
sys.exit(0 if not erros else 1)
