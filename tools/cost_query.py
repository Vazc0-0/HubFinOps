"""Ferramentas de consulta de custos para os agentes (somente leitura).

Lê o CSV no formato FOCUS e devolve respostas curtas em texto, pensadas para
caber no contexto de um modelo local. Só usa a biblioteca padrão do Python.

Comandos:
  python tools/cost_query.py resumo
  python tools/cost_query.py anomalias
  python tools/cost_query.py tabela
  python tools/cost_query.py recurso <nome-do-recurso>
"""
import csv
import json
import os
import statistics
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "focus_costs.csv"

PICO_FATOR = 2.5          # dia > 2,5x a mediana dos 14 dias anteriores
PATAMAR_FATOR = 1.5       # média dos últimos 30 dias > 1,5x a dos 30 anteriores
JANELA = 14


def load():
    series = defaultdict(dict)   # recurso -> {data: custo}
    meta = {}
    with CSV_PATH.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            d = date.fromisoformat(r["ChargePeriodStart"][:10])
            name = r["ResourceName"]
            series[name][d] = series[name].get(d, 0.0) + float(r["BilledCost"])
            meta[name] = {"rg": r["x_ResourceGroupName"], "servico": r["ServiceName"],
                          "tags": json.loads(r["Tags"] or "{}"), "moeda": r["BillingCurrency"]}
    return series, meta


def brl(v):
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def resumo(series, meta):
    last = max(max(s) for s in series.values())
    mes = defaultdict(float)
    rg = defaultdict(float)
    ult30 = defaultdict(float)
    for name, s in series.items():
        for d, c in s.items():
            mes[d.strftime("%Y-%m")] += c
            if d > last - timedelta(days=30):
                rg[meta[name]["rg"]] += c
                ult30[name] += c
    out = [f"Período dos dados: até {last.isoformat()}", "Custo por mês:"]
    out += [f"  {m}: {brl(v)}" for m, v in sorted(mes.items())]
    out.append("Últimos 30 dias por resource group:")
    out += [f"  {k}: {brl(v)}" for k, v in sorted(rg.items(), key=lambda x: -x[1])]
    out.append("Top 5 recursos (últimos 30 dias):")
    out += [f"  {k} ({meta[k]['servico']}): {brl(v)}" for k, v in sorted(ult30.items(), key=lambda x: -x[1])[:5]]
    return "\n".join(out)


def detectar(series, meta):
    achados = []
    for name, s in series.items():
        dias = sorted(s)
        first, last = dias[0], dias[-1]
        # 1) recurso sem dono (sem tag owner)
        if "owner" not in meta[name]["tags"]:
            achados.append({"recurso": name, "tipo": "recurso_orfao", "inicio": first, "fim": last,
                            "detalhe": f"sem tag 'owner'; custo foi de {brl(s[first])}/dia para {brl(s[last])}/dia"})
            continue
        # 2) mudança de patamar: mediana dos últimos 30 dias vs mediana dos
        #    primeiros 30 dias (mediana para um pico curto não parecer patamar)
        recent = [s[d] for d in dias if d > last - timedelta(days=30)]
        baseline = [s[d] for d in dias if d < first + timedelta(days=30)]
        base = statistics.median(baseline)
        if len(baseline) >= 28 and statistics.median(recent) > PATAMAR_FATOR * base:
            def semana(d):
                return [s[x] for x in dias if d <= x < d + timedelta(days=7)]
            inicio = next(d for d in dias if s[d] > PATAMAR_FATOR * base
                          and statistics.median(semana(d)) > PATAMAR_FATOR * base)
            achados.append({"recurso": name, "tipo": "mudanca_de_patamar", "inicio": inicio, "fim": last,
                            "detalhe": f"custo diário típico subiu de {brl(base)} para {brl(statistics.median(recent))} "
                                       f"({statistics.median(recent) / base:.1f}x) e não voltou"})
            continue
        # 3) picos (dia muito acima da mediana recente), agrupando dias seguidos
        flagged = []
        for i, d in enumerate(dias):
            prev = [s[x] for x in dias[max(0, i - JANELA):i]]
            if len(prev) >= 7 and s[d] > PICO_FATOR * statistics.median(prev):
                # mediana sem os próprios dias de pico, para não "contaminar" a base
                flagged.append(d)
        grupos = []
        for d in flagged:
            if grupos and d - grupos[-1][-1] == timedelta(days=1):
                grupos[-1].append(d)
            else:
                grupos.append([d])
        for g in grupos:
            base = statistics.median([s[x] for x in dias if g[0] - timedelta(days=JANELA) <= x < g[0]])
            pico = max(s[x] for x in g)
            extra = sum(s[x] - base for x in g)
            achados.append({"recurso": name, "tipo": "pico", "inicio": g[0], "fim": g[-1],
                            "detalhe": f"até {brl(pico)}/dia contra base de {brl(base)}/dia ({pico / base:.1f}x)"})
    return achados


def _estende_picos(series, achados):
    """Um pico longo eleva a mediana móvel e esconde os últimos dias; estende
    o intervalo enquanto o custo seguir acima do limiar da base original."""
    for a in achados:
        if a["tipo"] != "pico":
            continue
        s = series[a["recurso"]]
        dias = sorted(s)
        base = statistics.median([s[x] for x in dias if a["inicio"] - timedelta(days=JANELA) <= x < a["inicio"]])
        d = a["fim"] + timedelta(days=1)
        while d in s and s[d] > PICO_FATOR * base:
            a["fim"] = d
            d += timedelta(days=1)
    return achados


def anomalias(series, meta):
    achados = _estende_picos(series, detectar(series, meta))
    if not achados:
        return "Nenhuma anomalia encontrada."
    out = [f"{len(achados)} anomalia(s) encontrada(s):"]
    for a in achados:
        m = meta[a["recurso"]]
        v = custo_extra(series, a)
        out.append(f"- [{a['tipo']}] {a['recurso']} ({m['servico']}, {m['rg']}) de {a['inicio']} a {a['fim']}: {a['detalhe']} "
                   f"| CUSTO EXTRA DESTA ANOMALIA: {brl(v)} | PRIORIDADE: {prioridade(v)}")
    total = sum(custo_extra(series, a) for a in achados)
    out.append(f"(Total somando TODAS as anomalias: {brl(total)} — não atribuir este total a um recurso só.)")
    return "\n".join(out)


TIPO_PT = {"pico": "Pico", "mudanca_de_patamar": "Mudança de patamar", "recurso_orfao": "Recurso sem dono"}


def custo_extra(series, a):
    """Custo acima do normal causado pela anomalia (calculado, nunca estimado pelo modelo)."""
    s = series[a["recurso"]]
    dias = sorted(s)
    periodo = [d for d in dias if a["inicio"] <= d <= a["fim"]]
    if a["tipo"] == "recurso_orfao":
        return sum(s[d] for d in periodo)
    if a["tipo"] == "mudanca_de_patamar":
        base = statistics.median([s[d] for d in dias if d < dias[0] + timedelta(days=30)])
    else:
        base = statistics.median([s[d] for d in dias if a["inicio"] - timedelta(days=JANELA) <= d < a["inicio"]])
    return sum(max(0.0, s[d] - base) for d in periodo)


def prioridade(valor):
    return "Alta" if valor >= 400 else "Média" if valor >= 150 else "Baixa"


def tabela(series, meta):
    """Tabela Markdown pronta para o relatório: o relator copia, não recalcula."""
    achados = _estende_picos(series, detectar(series, meta))
    linhas = ["| Recurso | Tipo | Período | Custo extra | Prioridade |",
              "|---|---|---|---|---|"]
    for a in sorted(achados, key=lambda x: -custo_extra(series, x)):
        v = custo_extra(series, a)
        periodo = f"{a['inicio'].strftime('%d/%m')} a {a['fim'].strftime('%d/%m')}"
        linhas.append(f"| {a['recurso']} | {TIPO_PT[a['tipo']]} | {periodo} | {brl(v)} | {prioridade(v)} |")
    total = sum(custo_extra(series, a) for a in achados)
    linhas.append(f"\nTotal de custo extra causado pelas anomalias: {brl(total)}")
    return "\n".join(linhas)


def recurso(series, meta, name):
    if name not in series:
        return f"Recurso '{name}' não encontrado. Disponíveis: {', '.join(sorted(series))}"
    s = series[name]
    last = max(s)
    m = meta[name]
    out = [f"{name} | serviço: {m['servico']} | rg: {m['rg']} | tags: {json.dumps(m['tags'], ensure_ascii=False)}",
           "Custo diário (últimos 30 dias):"]
    out += [f"  {d}: {brl(s[d])}" for d in sorted(s) if d > last - timedelta(days=30)]
    return "\n".join(out)


def main(argv):
    if len(argv) < 2 or argv[1] not in ("resumo", "anomalias", "tabela", "recurso"):
        print(__doc__)
        return 1
    series, meta = load()
    if argv[1] == "resumo":
        print(resumo(series, meta))
    elif argv[1] == "anomalias":
        print(anomalias(series, meta))
    elif argv[1] == "tabela":
        print(tabela(series, meta))
    else:
        # O Docker Agent passa os argumentos da ferramenta como variáveis de ambiente.
        # Ler a variável direto funciona no Windows (cmd/PowerShell) e no Linux/macOS.
        nome = argv[2] if len(argv) > 2 and argv[2] else os.environ.get("nome", "")
        print(recurso(series, meta, nome.strip()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
