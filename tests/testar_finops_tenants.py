"""Testa a visão FinOps por tenant (tools/finops_tenants.py) contra o gabarito de data/tenants/.

Cenário: uma empresa com um tenant por ambiente (Contoso Produção, Desenvolvimento e Integração).

  1. números de cada tenant iguais ao gabarito (calculado pelo gerador por outro caminho): custo, previsão,
     orçamento, cobertura de tags, cada oportunidade com o valor exato, economia realizada e a causa do estouro;
  2. nada além do gabarito: o que não é desperdício não vira oportunidade (VM de teste com auto-shutdown, VM de
     produção ligada 24x7, disco de produção anexado);
  3. visão da empresa: custo por ambiente, custo fora de produção ÷ produção e apps caros fora de produção;
  4. ISOLAMENTO: o relatório de um ambiente não cita recurso, nome ou ID de outro, e o disco de mesmo nome
     (disk-dados-01) está anexado em produção e órfão em desenvolvimento;
  5. mudanças nos dados mudam o resultado do jeito certo (disco anexado/solto, IP associado, VM com CPU alta, VM que
     passou a desligar no fim de semana, ação que não zerou o custo, recurso com 2 medidores, tenant sem ambiente);
  6. achar o tenant pelo nome, sem acento, pelo ambiente, por apelido (prod, dev, hml) ou pelo ID; "contoso" sozinho é
     ambíguo e não vira nenhum.

Uso:  python tests/testar_finops_tenants.py      Termina com "RESULTADO: FINOPS POR TENANT CORRETO".
"""
import csv
import json
import shutil
import sys
import tempfile
from datetime import date
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
    return cond


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
    causa = [(x["recurso"], x["desde"], x["recurso_novo"]) for x in a["aumentos"]]
    confere(causa == [(c["recurso"], c["desde"], c["recurso_novo"]) for c in g["causa_aumento"]],
            f"{g['nome']}: causa do aumento {causa}")
    confere(a["ambiente"] == g["ambiente"], f"{g['nome']}: ambiente {a['ambiente']}")
    confere(sorted(a["recursos"]) == g["recursos"], f"{g['nome']}: recursos do tenant {a['recursos']}")
    confere(all(r["comprovada"] for r in a["realizadas"]), f"{g['nome']}: economia realizada não comprovada nos dados")

# 3. visão da empresa
E, GE = ft.analisar_empresa(list(analises.values())), GAB["empresa"]
for amb, v in GE["custo_por_ambiente"].items():
    confere(perto(E["custo_por_ambiente"].get(amb), v), f"custo de {amb}: {E['custo_por_ambiente'].get(amb)} (gabarito {v})")
confere(perto(E["custo_nao_produtivo_pct"], GE["custo_nao_produtivo_pct"], 0.051),
        f"custo não produtivo ÷ produção {E['custo_nao_produtivo_pct']}% (gabarito {GE['custo_nao_produtivo_pct']}%)")
for app, v in GE["apps"].items():
    e = E["apps"].get(app, {})
    confere(perto(e.get("producao"), v["producao"], 0.05) and perto(e.get("nao_producao"), v["nao_producao"], 0.05),
            f"app {app}: {e} (gabarito {v})")
confere(E["apps_nao_prod_alto"] == GE["apps_nao_prod_alto"], f"apps caros fora de produção {E['apps_nao_prod_alto']}")
cons = ft.texto_consolidado(list(analises.values()))
confere("85,5% do custo de produção" in cons and "pedidos (165,1%" in cons, "consolidado sem o custo fora de produção")

# 4. isolamento
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
PRD, DEV, HML = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222", "33333333-3333-3333-3333-333333333333"
prd, dev, hml = analises[PRD], analises[DEV], analises[HML]
confere(any(o["recurso"] == "disk-dados-01" for o in dev["oportunidades"]), "disk-dados-01 de desenvolvimento é órfão e sumiu")
confere("disk-dados-01" in prd["nao_sao_oportunidades"], "disk-dados-01 de produção está anexado e virou oportunidade")
confere("vm-teste-dev" in dev["nao_sao_oportunidades"], "vm-teste-dev já desliga à noite e no fim de semana e virou oportunidade")
confere([o["tipo"] for o in prd["oportunidades"]] == ["vm_superdimensionada"], "VM de produção ligada 24x7 não é desperdício")

# 5. mudanças nos dados (numa cópia)
tmp = Path(tempfile.mkdtemp(prefix="tenants-"))
for f in ("tenants.json", "inventario.json", "acoes.json", "focus_tenants.csv"):
    shutil.copy(ROOT / "data" / "tenants" / f, tmp / f)
inv = json.loads((tmp / "inventario.json").read_text(encoding="utf-8"))
for item in inv:
    if item["tenantId"] == PRD and item["name"] == "disk-dados-01":
        item["properties"] = {"diskState": "Unattached", "managedBy": None}
    if item["tenantId"] == DEV and item["name"] == "disk-dados-01":
        item["properties"] = {"diskState": "Attached", "managedBy": "vm-teste-dev"}
    if item["name"] == "pip-teste-dev":
        item["properties"] = {"ipConfiguration": {"id": "nic-teste"}}
    if item["name"] == "vm-erp-conector-prd":
        item["metricas"]["Percentage CPU"]["valor"] = 55.0
(tmp / "inventario.json").write_text(json.dumps(inv), encoding="utf-8")
acoes = json.loads((tmp / "acoes.json").read_text(encoding="utf-8"))
acoes.append({"id": "E-999", "tenant": HML, "recurso": "sqldb-pedidos-hml",
              "acao": "Reduzir o banco de integração", "aprovada_em": "2026-11-01", "implementada_em": "2026-11-02"})
(tmp / "acoes.json").write_text(json.dumps(acoes), encoding="utf-8")
with (tmp / "focus_tenants.csv").open(encoding="utf-8") as f:
    linhas = list(csv.DictReader(f))
novas = []
for r in linhas:
    dia = date.fromisoformat(r["ChargePeriodStart"][:10])
    if r["ResourceName"] == "vm-hml-01" and dia.weekday() >= 5:
        continue  # passou a desligar no fim de semana (auto-shutdown / Start/Stop VMs v2)
    if r["ResourceName"] == "sqldb-pedidos-dev":  # exportação real: um medidor por linha, várias linhas por dia
        for parte, medidor in ((0.7, "vCore"), (0.3, "Storage")):
            novas.append({**r, "EffectiveCost": str(float(r["EffectiveCost"]) * parte), "ChargeDescription": medidor})
    else:
        novas.append(r)
with (tmp / "focus_tenants.csv").open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(linhas[0]))
    w.writeheader()
    w.writerows(novas)
ft.PASTA = tmp
d2 = ft.carregar()
m = {a["id"]: a for a in ft.analisar_todos(d2)}
p2, v2, h2 = m[PRD], m[DEV], m[HML]
confere([o["recurso"] for o in p2["oportunidades"]] == ["disk-dados-01"],
        f"produção com disco solto e VM com CPU 55%: {[o['recurso'] for o in p2['oportunidades']]}")
rec_v2 = {o["recurso"] for o in v2["oportunidades"]}
confere("disk-dados-01" not in rec_v2 and "pip-teste-dev" not in rec_v2,
        f"desenvolvimento com disco anexado e IP associado: ainda aponta {sorted(rec_v2)}")
confere(not h2["oportunidades"] and "vm-hml-01" in h2["nao_sao_oportunidades"],
        f"vm-hml-01 passou a desligar no fim de semana e continua como oportunidade: {h2['oportunidades']}")
red = [r for r in h2["realizadas"] if r["recurso"] == "sqldb-pedidos-hml"]
confere(len(red) == 1 and not red[0]["comprovada"] and abs(red[0]["economia_mensal"]) < 60,
        f"ação que não zerou o custo tem que aparecer como não comprovada e quase sem economia: {red}")
confere(not any(r["recurso"] == "sqldb-pedidos-hml" for r in p2["realizadas"] + v2["realizadas"]),
        "ação de integração apareceu em outro tenant")
confere(perto(v2["custo_ultimos_30_dias"], dev["custo_ultimos_30_dias"], 0.05),
        f"recurso com 2 medidores por dia: custo de desenvolvimento mudou ({v2['custo_ultimos_30_dias']} × {dev['custo_ultimos_30_dias']})")
ten = json.loads((tmp / "tenants.json").read_text(encoding="utf-8"))
for t in ten:
    t.pop("ambiente", None)
(tmp / "tenants.json").write_text(json.dumps(ten), encoding="utf-8")
shutil.copy(ROOT / "data" / "tenants" / "focus_tenants.csv", tmp / "focus_tenants.csv")
d3 = ft.carregar()
sem_amb = ft.analisar(d3, d3["tenants"][2])
confere(not any(o["tipo"] == "vm_ligada_24x7" for o in sem_amb["oportunidades"]),
        "tenant sem ambiente informado tem que ser tratado como produção (sem a regra de VM 24x7)")
ft.PASTA = ROOT / "data" / "tenants"

# 6. achar o tenant
for texto, esperado in (("dev", "Contoso Desenvolvimento"), ("desenvolvimento", "Contoso Desenvolvimento"),
                        ("Contoso Integração", "Contoso Integração"), ("CONTOSO INTEGRACAO", "Contoso Integração"),
                        ("hml", "Contoso Integração"), ("prod", "Contoso Produção"), ("producao", "Contoso Produção"),
                        ("33333333-3333-3333-3333-333333333333", "Contoso Integração")):
    t = ft.achar_tenant(dados, texto)
    confere(t and t["nome"] == esperado, f"achar '{texto}': {t and t['nome']}")
for texto in ("Acme", "", "contoso", "qa", "Contoso Homologação", "de"):
    confere(ft.achar_tenant(dados, texto) is None, f"'{texto}' não devia achar nenhum tenant")

# 7. o painel do hub (/api/finops) mostra os mesmos números do gabarito, separados por ambiente
import hub  # noqa: E402

P = hub.painel_finops()
confere(P["corte"] == GAB["corte"] and len(P["dias"]) == 30 and P["dias"][-1] == GAB["corte"], f"painel: dias {P['dias'][:1]}…")
por_id = {t["ambiente"]: t["id"] for t in dados["tenants"]}
for amb in P["ambientes"]:
    g = GAB["tenants"][por_id[amb["id"]]]
    for campo, chave in (("previsao", "previsao_mes"), ("orcamento", "orcamento_mensal"), ("custo30", "custo_ultimos_30_dias"),
                         ("realizada", "economia_realizada_mensal")):
        confere(perto(amb[campo], g[chave]), f"painel {amb['nome']}: {campo} = {amb[campo]} (gabarito {g[chave]})")
    confere(perto(sum(amb["serie"]), g["custo_ultimos_30_dias"], 0.05), f"painel {amb['nome']}: soma da série {sum(amb['serie'])}")
    confere({(o["recurso"], o["valor"]) for o in amb["acoes"]} == {(o["recurso"], o["economia_mensal"]) for o in g["oportunidades"]},
            f"painel {amb['nome']}: ações {amb['acoes']}")
    confere(set(amb["recursos"]) <= set(g["recursos"]), f"ISOLAMENTO no painel: {amb['nome']} mostra recurso de outro ambiente")
    for nome_app, v in amb["app"].items():
        confere(v >= 0 and nome_app, f"painel {amb['nome']}: app {nome_app}")
confere(perto(sum(sum(a["app"].values()) for a in P["ambientes"]), sum(g["custo_ultimos_30_dias"] for g in GAB["tenants"].values()), 0.1),
        "painel: soma por app = custo total")

# 8. página de um ambiente: o hub só manda os dados daquele tenant
for t in dados["tenants"]:
    so = hub.painel_finops(t["ambiente"])
    confere([a["id"] for a in so["ambientes"]] == [t["ambiente"]], f"página {t['ambiente']}: recebeu {[a['id'] for a in so['ambientes']]}")
    texto = json.dumps(so["ambientes"], ensure_ascii=False)
    outros = [x for x in dados["tenants"] if x["id"] != t["id"]]
    exclusivos = set().union(*(por_tenant[x["id"]] for x in outros)) - por_tenant[t["id"]]
    vazou = (sorted(n for n in exclusivos if n in texto) + [x["nome"] for x in outros if x["nome"] in texto]
             + [x["id"] for x in outros if x["id"] in texto])
    confere(not vazou, f"ISOLAMENTO na página {t['ambiente']}: {vazou}")
confere(hub.ambientes_validos() == {"producao", "desenvolvimento", "integracao"}, f"ambientes do hub: {hub.ambientes_validos()}")

total = ok + len(falhas)
print(f"Teste FinOps por tenant: {ok}/{total} verificações")
for f in falhas:
    print("  FALHOU:", f)
print("\nRESULTADO:", "FINOPS POR TENANT CORRETO" if not falhas else f"REPROVADO ({len(falhas)} problema(s))")
sys.exit(0 if not falhas else 1)
