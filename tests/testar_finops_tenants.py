"""Testa a visão FinOps por tenant (tools/finops_tenants.py) contra o gabarito de data/tenants/.

  1. números de cada tenant iguais ao gabarito (calculado pelo gerador por outro caminho): custo, previsão,
     orçamento, cobertura de tags, cada oportunidade com o valor exato, economia realizada e a causa do estouro;
  2. nada além do gabarito: o que não é desperdício não vira oportunidade;
  3. ISOLAMENTO: o relatório de um tenant não cita recurso, nome ou ID de outro tenant, e o disco de mesmo nome
     (disk-backup-01) é órfão num tenant e não no outro;
  4. mudanças nos dados mudam o resultado do jeito certo (disco anexado, IP associado, VM com CPU alta, ação que não
     zerou o custo), numa cópia dos dados;
  5. achar o tenant pelo nome, sem acento, pela primeira palavra ou pelo ID; tenant inexistente não vira outro.

Uso:  python tests/testar_finops_tenants.py      Termina com "RESULTADO: FINOPS POR TENANT CORRETO".
"""
import csv
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import finops_tenants as ft  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
ok, falhas = 0, []


def confere(cond, msg):
    global ok
    if cond:
        ok += 1
    else:
        falhas.append(msg)


def perto(a, b, tol=0.011):
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


GAB = json.loads((ROOT / "data" / "tenants" / "gabarito.json").read_text(encoding="utf-8"))
dados = ft.carregar()
analises = {a["id"]: a for a in ft.analisar_todos(dados)}
confere(str(dados["corte"]) == GAB["corte"], f"data de corte {dados['corte']} × gabarito {GAB['corte']}")

# 1 e 2. números e oportunidades
for tid, g in GAB["tenants"].items():
    a = analises.get(tid)
    if not confere(a is not None, f"tenant {g['nome']} não analisado"):
        continue
    for campo in ("custo_ultimos_30_dias", "custo_mes_ate_corte", "previsao_mes", "orcamento_mensal",
                  "economia_potencial_mensal", "economia_realizada_mensal"):
        confere(perto(a[campo], g[campo]), f"{g['nome']}: {campo} = {a[campo]} (gabarito {g[campo]})")
    confere(perto(a["cobertura_tags_pct"], g["cobertura_tags_pct"], 0.051), f"{g['nome']}: cobertura de tags {a['cobertura_tags_pct']}")
    confere(a["estoura_orcamento"] == g["estoura_orcamento"], f"{g['nome']}: estoura orçamento = {a['estoura_orcamento']}")
    achou = {(o["recurso"], o["tipo"]): o["economia_mensal"] for o in a["oportunidades"]}
    esperado = {(o["recurso"], o["tipo"]): o["economia_mensal"] for o in g["oportunidades"]}
    confere(set(achou) == set(esperado), f"{g['nome']}: oportunidades {sorted(achou)} × gabarito {sorted(esperado)}")
    for k, v in esperado.items():
        confere(perto(achou.get(k), v), f"{g['nome']}: economia de {k[0]} = {achou.get(k)} (gabarito {v})")
    confere(sorted(a["nao_sao_oportunidades"]) == g["nao_sao_oportunidades"],
            f"{g['nome']}: conferidos sem desperdício {a['nao_sao_oportunidades']} × {g['nao_sao_oportunidades']}")
    causa = [(x["recurso"], x["desde"]) for x in a["aumentos"]]
    confere(causa == [(c["recurso"], c["desde"]) for c in g["causa_aumento"]], f"{g['nome']}: causa do aumento {causa}")
    confere(sorted(a["recursos"]) == g["recursos"], f"{g['nome']}: recursos do tenant {a['recursos']}")
    confere(all(r["comprovada"] for r in a["realizadas"]), f"{g['nome']}: economia realizada não comprovada nos dados")

# 3. isolamento
por_tenant = {tid: set(g["recursos"]) for tid, g in GAB["tenants"].items()}
for t in dados["tenants"]:
    a = analises[t["id"]]
    textos = {"tenant": ft.texto_tenant(a), "economia": ft.texto_economia(a), "executivo": ft.relatorio_executivo(a),
              "json": json.dumps(a, ensure_ascii=False, default=str)}
    outros = [x for x in dados["tenants"] if x["id"] != t["id"]]
    exclusivos = set().union(*(por_tenant[x["id"]] for x in outros)) - por_tenant[t["id"]]
    for qual, texto in textos.items():
        vazou = sorted(n for n in exclusivos if n in texto) + [x["nome"] for x in outros if x["nome"] in texto] \
            + [x["id"] for x in outros if x["id"] in texto]
        confere(not vazou, f"ISOLAMENTO: {qual} de {t['nome']} cita outro tenant: {vazou}")
contoso, fabrikam = (analises["11111111-1111-1111-1111-111111111111"], analises["22222222-2222-2222-2222-222222222222"])
confere(any(o["recurso"] == "disk-backup-01" for o in contoso["oportunidades"]), "disk-backup-01 da Contoso é órfão e sumiu")
confere("disk-backup-01" in fabrikam["nao_sao_oportunidades"], "disk-backup-01 da Fabrikam está anexado e virou oportunidade")

# 4. mudanças nos dados (numa cópia)
tmp = Path(tempfile.mkdtemp(prefix="tenants-"))
for f in ("tenants.json", "inventario.json", "acoes.json", "focus_tenants.csv"):
    shutil.copy(ROOT / "data" / "tenants" / f, tmp / f)
inv = json.loads((tmp / "inventario.json").read_text(encoding="utf-8"))
for item in inv:
    if item["tenantId"].startswith("1111") and item["name"] == "disk-backup-01":
        item["properties"] = {"diskState": "Attached", "managedBy": "vm-pdv-api-01"}
    if item["tenantId"].startswith("2222") and item["name"] == "disk-backup-01":
        item["properties"] = {"diskState": "Unattached", "managedBy": None}
    if item["name"] == "pip-sem-uso-03":
        item["properties"] = {"ipConfiguration": {"id": "nic-rotas"}}
    if item["name"] == "vm-relatorios-02":
        item["metricas"]["Percentage CPU"]["valor"] = 55.0
(tmp / "inventario.json").write_text(json.dumps(inv), encoding="utf-8")
acoes = json.loads((tmp / "acoes.json").read_text(encoding="utf-8"))
acoes.append({"id": "E-999", "tenant": "11111111-1111-1111-1111-111111111111", "recurso": "aks-loja",
              "acao": "Reduzir nós do AKS", "aprovada_em": "2026-11-01", "implementada_em": "2026-11-02"})
(tmp / "acoes.json").write_text(json.dumps(acoes), encoding="utf-8")
# exportação real tem várias linhas por recurso e dia (um medidor por linha): dividir sqldb-vendas em 2 medidores
with (tmp / "focus_tenants.csv").open(encoding="utf-8") as f:
    linhas = list(csv.DictReader(f))
divididas = []
for r in linhas:
    if r["ResourceName"] == "sqldb-vendas":
        for parte, medidor in ((0.7, "vCore"), (0.3, "Storage")):
            divididas.append({**r, "EffectiveCost": str(float(r["EffectiveCost"]) * parte), "ChargeDescription": medidor})
    else:
        divididas.append(r)
with (tmp / "focus_tenants.csv").open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(linhas[0]))
    w.writeheader()
    w.writerows(divididas)
ft.PASTA = tmp
d2 = ft.carregar()
m = {a["id"]: a for a in ft.analisar_todos(d2)}
c2, f2, n2 = (m["11111111-1111-1111-1111-111111111111"], m["22222222-2222-2222-2222-222222222222"],
              m["33333333-3333-3333-3333-333333333333"])
tipos_c2 = {o["recurso"] for o in c2["oportunidades"]}
confere("disk-backup-01" not in tipos_c2 and "vm-relatorios-02" not in tipos_c2,
        f"Contoso com disco anexado e VM com CPU 55%: ainda aponta {tipos_c2}")
confere([o["recurso"] for o in f2["oportunidades"]] == ["disk-backup-01"], f"Fabrikam com disco solto: {f2['oportunidades']}")
confere(all(o["recurso"] != "pip-sem-uso-03" for o in n2["oportunidades"]), "IP associado continua como oportunidade")
aks = [r for r in c2["realizadas"] if r["recurso"] == "aks-loja"]
confere(len(aks) == 1 and not aks[0]["comprovada"] and abs(aks[0]["economia_mensal"]) < 200,
        f"ação que não zerou o custo tem que aparecer como não comprovada e quase sem economia: {aks}")
confere(not any(r["recurso"] == "aks-loja" for r in f2["realizadas"] + n2["realizadas"]), "ação da Contoso apareceu em outro tenant")
confere(perto(c2["custo_ultimos_30_dias"], contoso["custo_ultimos_30_dias"], 0.05),
        f"recurso com 2 medidores por dia: custo da Contoso mudou ({c2['custo_ultimos_30_dias']} × {contoso['custo_ultimos_30_dias']})")
ft.PASTA = ROOT / "data" / "tenants"

# 5. achar o tenant
for texto, esperado in (("fabrikam", "Fabrikam Saúde"), ("Fabrikam Saúde", "Fabrikam Saúde"), ("FABRIKAM SAUDE", "Fabrikam Saúde"),
                        ("33333333-3333-3333-3333-333333333333", "Northwind Logística"), ("contoso", "Contoso Varejo")):
    t = ft.achar_tenant(dados, texto)
    confere(t and t["nome"] == esperado, f"achar '{texto}': {t and t['nome']}")
for texto in ("Acme", "", "fab", "Contoso Saúde"):
    confere(ft.achar_tenant(dados, texto) is None, f"'{texto}' não devia achar nenhum tenant")

total = ok + len(falhas)
print(f"Teste FinOps por tenant: {ok}/{total} verificações")
for f in falhas:
    print("  FALHOU:", f)
print("\nRESULTADO:", "FINOPS POR TENANT CORRETO" if not falhas else f"REPROVADO ({len(falhas)} problema(s))")
sys.exit(0 if not falhas else 1)
