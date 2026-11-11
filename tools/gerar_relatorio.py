"""Gera e SALVA o relatório FinOps a partir dos dados, e já valida o resultado.

Motivo: nos testes, o modelo local (qwen3) inventou números e chegou a dizer que
tinha salvo o arquivo sem salvar. Por isso, fatos, números e gravação do arquivo
ficam no código; o agente coordena, conversa e explica.

Uso:  python tools/gerar_relatorio.py          (ferramenta do agente relator)
      python tools/gerar_relatorio.py --hook   (hook "stop" do orquestrador: saída curta + log)
Saída: relatorios/relatorio-finops.md + resultado da validação (+ relatorios/hook.log no modo --hook)
"""
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import cost_query as cq  # noqa: E402

OUT = ROOT / "relatorios" / "relatorio-finops.md"

ACAO = {
    "pico": ("algo ficou ligado ou executando além do normal nesses dias",
             "verificar o que mudou no período, desligar ou redimensionar o recurso e criar um alerta de orçamento"),
    "mudanca_de_patamar": ("uma configuração mudou e o custo ficou mais alto de forma permanente",
                           "confirmar se a mudança foi intencional (ex.: recorrência mais frequente) e, se não for, reverter"),
    "recurso_orfao": ("o recurso não tem responsável (sem tag owner) e o custo cresce todo dia",
                      "identificar o dono, aplicar a tag owner e avaliar se o recurso pode ser excluído"),
}


def fmt(d):
    return d.strftime("%d/%m/%Y")


def main():
    hook = "--hook" in sys.argv
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # acentos corretos no Windows
    series, meta = cq.load()
    achados = cq._estende_picos(series, cq.detectar(series, meta))
    achados.sort(key=lambda a: -cq.custo_extra(series, a))
    total_extra = sum(cq.custo_extra(series, a) for a in achados)

    mes = {}
    for s in series.values():
        for d, c in s.items():
            mes[d.strftime("%m/%Y")] = mes.get(d.strftime("%m/%Y"), 0.0) + c
    meses = sorted(mes, key=lambda m: (m[3:], m[:2]))
    var = (mes[meses[-1]] / mes[meses[-2]] - 1) * 100 if len(meses) > 1 else 0
    altas = [a["recurso"] for a in achados if cq.prioridade(cq.custo_extra(series, a)) == "Alta"]

    L = [f"# Relatório FinOps — {fmt(date.today())}",
         "> Dados sintéticos de demonstração. Números calculados em código e validados automaticamente.",
         f"> Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
         "", "## Resumo",
         "Custo por mês: " + " | ".join(f"{m}: {cq.brl(mes[m])}" for m in meses) + ".",
         f"O último mês variou {var:+.0f}% em relação ao anterior.",
         f"Foram encontradas {len(achados)} anomalias, que somam {cq.brl(total_extra)} de custo extra"
         + (f"; prioridade alta: {', '.join(altas)}." if altas else "."),
         "", "## Anomalias encontradas", cq.tabela(series, meta).split("\n\nTotal")[0],
         "", "## O que aconteceu e o que fazer"]
    for a in achados:
        v = cq.custo_extra(series, a)
        causa, acao = ACAO[a["tipo"]]
        m = meta[a["recurso"]]
        L.append(f"**{a['recurso']}** ({m['servico']}, {m['rg']}) — {cq.TIPO_PT[a['tipo']]}, "
                 f"de {fmt(a['inicio'])} a {fmt(a['fim'])}, custo extra de {cq.brl(v)} "
                 f"(prioridade {cq.prioridade(v).lower()}). O que os dados mostram: {a['detalhe']}. "
                 f"Causa provável: {causa}. O que fazer: {acao}.")
        L.append("")
    L += ["## Próximos passos",
          "1. Atacar primeiro as anomalias de prioridade alta.",
          "2. Exigir a tag owner em todos os recursos (Azure Policy) para não surgirem recursos órfãos.",
          "3. Criar alertas de orçamento por resource group para pegar picos no mesmo dia."]

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "tests" / "validar_relatorio.py"), str(OUT)],
                       capture_output=True, text=True, encoding="utf-8", env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    resultado = (r.stdout.strip().splitlines() or ["RESULTADO: sem saída"])[-1]
    if hook:
        linha = (f"{datetime.now().strftime('%d/%m/%Y %H:%M:%S')} | hook stop | relatorios/{OUT.name} | "
                 f"{len(achados)} anomalias | {cq.brl(total_extra)} | {resultado}")
        with (OUT.parent / "hook.log").open("a", encoding="utf-8") as f:
            f.write(linha + "\n")
        import historico  # registra no histórico do hub
        historico.evento("Relatório FinOps", "ok" if "CONFIÁVEL" in resultado else "falhou",
                         resultado.split(":", 1)[-1].strip(), origem="hook do agente FinOps")
        print(f"[hook] Relatório gerado por código e validado: {resultado}")
        return 0  # hook nunca derruba a sessão
    print(f"Relatório salvo em: relatorios/{OUT.name}\n")
    print("\n".join(L))
    print("\n--- Validação automática ---")
    print(r.stdout.strip())
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
