"""Sincronização agendada: traz os dados do Azure e carrega no Grafana sozinho, a cada N horas.

Cada rodada executa, em ordem, as tarefas "azure" (só leitura, via az login) e "grafana" (carrega no Postgres)
de tools/rodar.py, com origem "agendador" no histórico. Como o Postgres agora guarda as execuções e as
sincronizações sem apagar as antigas, o Grafana passa a mostrar a tendência ao longo dos dias.

Roda no PC, não no container: precisa da Azure CLI com login (az login) e do docker compose no ar.

Uso:
  python tools/agendador.py --uma-vez                 roda uma sincronização agora
  python tools/agendador.py --a-cada 6                fica rodando a cada 6 h (enquanto o terminal estiver aberto)
  python tools/agendador.py --instalar --a-cada 6     cria uma tarefa no Agendador de Tarefas do Windows (schtasks)
  python tools/agendador.py --status                  mostra a tarefa do Windows e a última rodada
  python tools/agendador.py --remover                 apaga a tarefa do Windows

A tarefa do Windows roda só com você logado (/it), com as suas permissões e o seu az login: não guarda senha.
Doc oficial: https://learn.microsoft.com/windows-server/administration/windows-commands/schtasks-create
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import historico  # noqa: E402
import rodar  # noqa: E402

ROOT = historico.ROOT
ESTADO = Path(os.environ.get("PILOTO_AGENDADOR_ESTADO", ROOT / "relatorios" / "agendador.json"))
LOG = ROOT / "relatorios" / "agendador.log"
NOME_TAREFA = r"Piloto Agentes IA\Sincronizar Azure"
SEQUENCIA = ["azure", "grafana"]


def ler_estado():
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def grava_estado(**mudancas):
    e = {**ler_estado(), **mudancas}
    if e.get("a_cada_h") and e.get("ultima_rodada"):
        ultima = datetime.fromisoformat(e["ultima_rodada"])
        e["proxima_estimada"] = (ultima + timedelta(hours=e["a_cada_h"])).isoformat(timespec="seconds")
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    ESTADO.write_text(json.dumps(e, ensure_ascii=False, indent=2), encoding="utf-8")
    return e


def uma_rodada(a_cada_h=None):
    """Sincroniza com o Azure e carrega no Grafana. Para no primeiro passo que falhar (não carrega dado velho)."""
    resultados = []
    for t in SEQUENCIA:
        _, ok, resumo = rodar.rodar(t, origem="agendador")
        resultados.append({"tarefa": t, "ok": ok, "resumo": resumo})
        print(f"  {'OK    ' if ok else 'FALHOU'} {rodar.TAREFAS[t][0]}: {resumo}", flush=True)
        if not ok:
            break
    ok = all(r["ok"] for r in resultados) and len(resultados) == len(SEQUENCIA)
    estado = {"ultima_rodada": historico.agora(), "ultimo_resultado": "ok" if ok else "falhou", "passos": resultados}
    if a_cada_h:
        estado["a_cada_h"] = a_cada_h
    grava_estado(**estado)
    return ok


def comando_tarefa(python=None, script=None):
    """Linha que o Agendador de Tarefas executa. Usa pythonw.exe (sem janela piscando) quando existe."""
    python = Path(python or sys.executable)
    sem_janela = python.with_name("pythonw.exe")
    if python.name.lower() == "python.exe" and sem_janela.exists():
        python = sem_janela
    script = script or Path(__file__).resolve()
    return f'"{python}" "{script}" --uma-vez --registrar-log'


def args_schtasks_criar(a_cada_h, comando):
    """Argumentos do schtasks /create (doc oficial: /sc HOURLY /mo 1-23, ou DAILY /mo dias; /it = só com o usuário logado)."""
    if a_cada_h < 1 or (a_cada_h > 23 and a_cada_h % 24):
        raise ValueError("use de 1 a 23 horas, ou múltiplos de 24 (dias)")
    agenda = ["/sc", "hourly", "/mo", str(a_cada_h)] if a_cada_h <= 23 else ["/sc", "daily", "/mo", str(a_cada_h // 24)]
    return ["schtasks", "/create", "/tn", NOME_TAREFA, "/tr", comando, *agenda, "/it", "/f"]


def instalar(a_cada_h):
    if os.name != "nt":
        print("O agendamento automático usa o Agendador de Tarefas do Windows. Em Linux/macOS use cron com:")
        print(f"  0 */{a_cada_h} * * *  cd {ROOT} && {sys.executable} tools/agendador.py --uma-vez --registrar-log")
        print("Ou deixe um terminal aberto com: python tools/agendador.py --a-cada", a_cada_h)
        return 1
    r = subprocess.run(args_schtasks_criar(a_cada_h, comando_tarefa()), capture_output=True, text=True, errors="replace")
    print((r.stdout or r.stderr).strip())
    if r.returncode != 0:
        print("RESULTADO: ERRO ao criar a tarefa no Agendador de Tarefas")
        return 1
    grava_estado(a_cada_h=a_cada_h, instalado_em=historico.agora(), tarefa_windows=NOME_TAREFA)
    print(f"Tarefa '{NOME_TAREFA}' criada: roda a cada {a_cada_h} h enquanto você estiver logado.")
    print("A primeira rodada acontece daqui a", a_cada_h, "h. Para rodar já: python tools/agendador.py --uma-vez")
    print("RESULTADO: AGENDAMENTO INSTALADO")
    return 0


def remover():
    if os.name != "nt":
        print("Nada a remover fora do Windows (se usou cron, apague a linha com: crontab -e).")
        return 0
    r = subprocess.run(["schtasks", "/delete", "/tn", NOME_TAREFA, "/f"], capture_output=True, text=True, errors="replace")
    print((r.stdout or r.stderr).strip())
    e = ler_estado()
    for k in ("instalado_em", "tarefa_windows", "a_cada_h", "proxima_estimada"):
        e.pop(k, None)
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    ESTADO.write_text(json.dumps(e, ensure_ascii=False, indent=2), encoding="utf-8")
    print("RESULTADO: AGENDAMENTO REMOVIDO" if r.returncode == 0 else "RESULTADO: TAREFA NÃO ENCONTRADA")
    return 0


def status():
    e = ler_estado()
    if os.name == "nt":
        r = subprocess.run(["schtasks", "/query", "/tn", NOME_TAREFA, "/fo", "LIST", "/v"], capture_output=True, text=True,
                           errors="replace")
        print((r.stdout or r.stderr).strip() or "Tarefa não encontrada.")
    print()
    print(f"A cada: {e.get('a_cada_h', '-')} h · última rodada: {e.get('ultima_rodada', 'nunca')} "
          f"({e.get('ultimo_resultado', '-')}) · próxima estimada: {e.get('proxima_estimada', '-')}")
    for p in e.get("passos", []):
        print(f"  {'OK    ' if p['ok'] else 'FALHOU'} {p['tarefa']}: {p['resumo']}")
    return 0


def main(argv):
    if "--registrar-log" in argv or sys.stdout is None:  # pythonw.exe (tarefa do Windows) não tem console
        LOG.parent.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(LOG, "a", encoding="utf-8")  # noqa: SIM115
        print(f"\n=== {historico.agora()} ===", flush=True)
    elif hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    a_cada = int(argv[argv.index("--a-cada") + 1]) if "--a-cada" in argv else None
    if "--instalar" in argv:
        return instalar(a_cada or 6)
    if "--remover" in argv:
        return remover()
    if "--status" in argv:
        return status()
    if "--uma-vez" in argv:
        ok = uma_rodada(a_cada or ler_estado().get("a_cada_h"))
        print("RESULTADO: SINCRONIZAÇÃO OK" if ok else "RESULTADO: SINCRONIZAÇÃO FALHOU")
        return 0 if ok else 1
    if a_cada:
        print(f"Sincronizando a cada {a_cada} h (Ctrl+C para parar).", flush=True)
        while True:
            print(f"\n{datetime.now():%d/%m %H:%M}", flush=True)
            uma_rodada(a_cada)
            time.sleep(a_cada * 3600)
    print(__doc__)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        print("\nAgendador encerrado.")
