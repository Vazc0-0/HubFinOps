"""Roda as tarefas do piloto registrando tudo no histórico (relatorios/historico.jsonl).

Uso:
  python tools/rodar.py                 lista as tarefas
  python tools/rodar.py testes          roda uma tarefa
  python tools/rodar.py tudo            roda a sequência completa

O hub (tools/hub.py) usa este mesmo arquivo para os botões "Executar".
"""
import os
import re
import shutil
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
    "avaliador_teste": ("Teste do corretor da avaliação", [PY, "tests/testar_avaliador.py"],
                        "Confere o corretor das respostas dos agentes com respostas boas e ruins conhecidas "
                        "(inclusive valores e recursos inventados).", "Testes"),
    "agendador_teste": ("Teste do agendador", [PY, "tests/testar_agendador.py"],
                        "Confere o comando do Agendador de Tarefas, a rodada (para no primeiro erro) e que a carga no "
                        "Postgres guarda o histórico das execuções e sincronizações.", "Testes"),
    "comparacao_teste": ("Teste da comparação de versões", [PY, "tests/testar_comparacao.py"],
                         "Aplica mudanças conhecidas (gatilho, ação nova/removida/alterada, retentativa, conector, "
                         "tratamento de erro, segredo) e confere que a comparação aponta exatamente cada uma.", "Testes"),
    "relatorio_finops": ("Relatório FinOps", [PY, "tools/gerar_relatorio.py"],
                         "Gera relatorios/relatorio-finops.md em código e valida contra os dados.", "Gerar"),
    "docs_logicapps": ("Documentação das Logic Apps", [PY, "tools/doc_logicapp.py", "gerar"],
                       "Gera docs/logicapps/*.md (passo a passo, diagrama, custo) e valida.", "Gerar"),
    "comparar_versoes": ("Comparar versões (exemplo)", [PY, "tools/comparar_logicapp.py", "exemplo"],
                         "Versão anterior × atual da lgc-desvios-processo: o que mudou no fluxo, no custo previsto e nos "
                         "riscos. Gera docs/comparacoes/. Para a Logic App real: python tools/comparar_logicapp.py azure.",
                         "Gerar"),
    "azure": ("Sincronizar com o Azure", [PY, "tools/azure_logicapp.py", "sincronizar"],
              "Só leitura: definição, execuções, métricas de cobrança e preços da Logic App real. "
              "Precisa de az login.", "Azure"),
    "agendador": ("Sincronização agendada (uma rodada)", [PY, "tools/agendador.py", "--uma-vez"],
                  "Sincroniza com o Azure e carrega no Grafana, como o agendador faz a cada N horas. Para agendar: "
                  "python tools/agendador.py --instalar --a-cada 6 (Agendador de Tarefas do Windows).", "Azure"),
    "grafana": ("Carregar dados no Grafana", [PY, "tools/carregar_grafana.py"],
                "Leva execuções do Azure, preços, histórico e chamados para o Postgres do Grafana "
                "(precisa do docker compose rodando).", "Grafana"),
    "avaliar_agentes": ("Avaliação dos agentes", [PY, "evals/avaliar.py"],
                        "Faz as 14 perguntas com resposta conhecida às duas equipes e mede acertos e invenções. "
                        "Precisa do Docker Desktop e do modelo local; demora alguns minutos.", "IA"),
}
# tarefas que dependem de um programa da máquina (no hub em Docker eles não existem: rode no terminal do PC)
REQUER = {"azure": ("az", "a Azure CLI (az login)"), "agendador": ("az", "a Azure CLI (az login)"),
          "avaliar_agentes": ("docker", "o Docker Desktop com o modelo local")}


def falta(tarefa):
    """Motivo para a tarefa não rodar aqui (programa ausente) ou None."""
    if tarefa not in REQUER:
        return None
    prog, nome = REQUER[tarefa]
    if shutil.which(prog):
        return None
    cmd = " ".join("python" if c == PY else c for c in TAREFAS[tarefa][1])
    return f"Precisa de {nome}, que não existe aqui. Rode no terminal do PC: {cmd}"


# o que roda sem Docker, sem Azure e sem modelo: é o que o GitHub Actions roda a cada push
SEQUENCIA_CI = ["testes", "gabarito_finops", "chamados_teste", "avaliador_teste", "agendador_teste", "comparacao_teste",
               "relatorio_finops", "docs_logicapps", "comparar_versoes"]
SEQUENCIA_TUDO = SEQUENCIA_CI + ["azure", "grafana"]
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
