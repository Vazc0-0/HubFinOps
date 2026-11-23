"""Roda as tarefas do piloto registrando tudo no histórico (relatorios/historico.jsonl).

Uso:
  python tools/rodar.py                 lista as tarefas
  python tools/rodar.py testes          roda uma tarefa
  python tools/rodar.py tudo            roda a sequência completa

O hub (tools/hub.py) usa este mesmo arquivo para os botões "Executar".
"""
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import historico  # noqa: E402

ROOT = historico.ROOT
PY = sys.executable

# id: (título, comando, o que faz, grupo)
TAREFAS = {
    "testes": ("Bateria de testes do leitor", [PY, "tests/testar_leitor_logicapps.py"],
               "Agendas, expressões, gatilhos, fluxos com gabarito, exemplos oficiais, 2.000 fluxos aleatórios, "
               "mutações e documentação. Deve terminar com LEITURA 100% CORRETA.", "Testes"),
    "gabarito_finops": ("Gabarito FinOps", [PY, "tests/validar_gabarito.py"],
                        "Confere se a detecção de anomalias encontra as 4 anomalias plantadas nos dados.", "Testes"),
    "chamados_teste": ("Teste do receptor de alertas", [PY, "tests/testar_chamados.py"],
                       "Envia alertas de exemplo (formato do Grafana) ao receptor e confere os chamados criados.",
                       "Testes"),
    "relatorio_finops": ("Relatório FinOps", [PY, "tools/gerar_relatorio.py"],
                         "Gera relatorios/relatorio-finops.md em código e valida contra os dados.", "Gerar"),
    "docs_logicapps": ("Documentação das Logic Apps", [PY, "tools/doc_logicapp.py", "gerar"],
                       "Gera docs/logicapps/*.md (passo a passo, diagrama, custo) e valida.", "Gerar"),
    "azure": ("Sincronizar com o Azure", [PY, "tools/azure_logicapp.py", "sincronizar"],
              "Só leitura: definição, execuções, métricas de cobrança e preços da Logic App real. "
              "Precisa de az login.", "Azure"),
    "grafana": ("Carregar dados no Grafana", [PY, "tools/carregar_grafana.py"],
                "Leva execuções do Azure, preços, histórico e chamados para o Postgres do Grafana "
                "(precisa do docker compose rodando).", "Grafana"),
}
SEQUENCIA_TUDO = ["testes", "gabarito_finops", "chamados_teste", "relatorio_finops", "docs_logicapps", "azure", "grafana"]
# o que roda sem Docker, sem Azure e sem modelo: é o que o GitHub Actions roda a cada push
SEQUENCIA_CI = ["testes", "gabarito_finops", "chamados_teste", "relatorio_finops", "docs_logicapps"]
SEQUENCIAS = {"tudo": SEQUENCIA_TUDO, "ci": SEQUENCIA_CI}


def resultado_de(saida):
    """Linha 'RESULTADO: ...' (padrão de todos os validadores) ou a última linha útil."""
    linhas = [l.strip() for l in saida.splitlines() if l.strip()]
    for l in reversed(linhas):
        if l.upper().startswith("RESULTADO"):
            return l.split(":", 1)[1].strip() if ":" in l else l
    for l in reversed(linhas):
        if l.startswith("ERRO"):
            return l
    return linhas[-1][:200] if linhas else ""


def rodar(tarefa, origem="terminal", ao_vivo=False):
    titulo, cmd, _, _ = TAREFAS[tarefa]
    exibicao = " ".join(["python" if c == PY else c for c in cmd])
    id_ = historico.iniciar(titulo, exibicao, origem)
    historico.LOGS.mkdir(parents=True, exist_ok=True)
    log = historico.LOGS / f"{id_}.log"
    t0 = time.time()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}  # log aparece ao vivo no hub
    with log.open("w", encoding="utf-8") as f:
        f.write(f"$ {exibicao}\n\n")
        f.flush()
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
        saida = []
        for bruto in p.stdout:  # grava linha a linha: o hub mostra o log enquanto roda
            linha = bruto.decode("utf-8", errors="replace")
            saida.append(linha)
            f.write(linha)
            f.flush()
            if ao_vivo:
                print(linha, end="")
        p.wait()
    texto = "".join(saida)
    resumo = resultado_de(texto)
    ok = p.returncode == 0 and not re.search(r"\b(REPROVAD|FALHOU|DIVERG|ERRO:)", resumo, re.I)
    historico.concluir(id_, "ok" if ok else "falhou", resumo, time.time() - t0,
                       log=log.relative_to(ROOT).as_posix(), extra={"codigo_saida": p.returncode, "tarefa_id": tarefa})
    return id_, ok, resumo


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if len(argv) < 2:
        print(__doc__)
        for k, (t, _, d, g) in TAREFAS.items():
            print(f"  {k:<16} [{g}] {t}: {d}")
        for nome, seq in SEQUENCIAS.items():
            print(f"  {nome:<16} roda: {', '.join(seq)}")
        return 1
    alvo = SEQUENCIAS.get(argv[1], [argv[1]])
    falhas = 0
    for t in alvo:
        if t not in TAREFAS:
            print(f"Tarefa desconhecida: {t}")
            return 1
        print(f"\n=== {TAREFAS[t][0]} ===")
        _, ok, resumo = rodar(t, ao_vivo=True)
        print(f"--> {'OK' if ok else 'FALHOU'}: {resumo}")
        falhas += not ok
    return 0 if not falhas else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
