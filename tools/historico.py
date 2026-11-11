"""Histórico único de tudo o que roda no piloto (testes, relatórios, docs, Azure, alertas, chamados).

Cada execução vira duas linhas em relatorios/historico.jsonl: uma quando começa ("em andamento")
e outra quando termina ("ok" ou "falhou"). O hub e o Grafana leem este arquivo.

Uso em código:
    import historico
    with historico.registrar("Bateria de testes", "python tests/...", origem="terminal") as h:
        ...
        h["resumo"] = "LEITURA 100% CORRETA"
"""
import json
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARQ = Path(os.environ.get("PILOTO_HISTORICO", ROOT / "relatorios" / "historico.jsonl"))  # trocado só nos testes
LOGS = ROOT / "relatorios" / "execucoes"


def agora():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _grava(evento):
    ARQ.parent.mkdir(parents=True, exist_ok=True)
    with ARQ.open("a", encoding="utf-8") as f:
        f.write(json.dumps(evento, ensure_ascii=False) + "\n")


def iniciar(tarefa, comando="", origem="terminal", id_=None):
    id_ = id_ or datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    _grava({"id": id_, "tarefa": tarefa, "comando": comando, "origem": origem,
            "status": "em andamento", "inicio": agora(), "pid": os.getpid()})
    return id_


def concluir(id_, status, resumo="", duracao_s=None, log=None, extra=None):
    ev = {"id": id_, "status": status, "fim": agora(), "resumo": resumo}
    if duracao_s is not None:
        ev["duracao_s"] = round(duracao_s, 1)
    if log:
        ev["log"] = log
    if extra:
        ev["extra"] = extra
    _grava(ev)


@contextmanager
def registrar(tarefa, comando="", origem="terminal"):
    id_ = iniciar(tarefa, comando, origem)
    t0 = time.time()
    h = {"id": id_, "resumo": "", "status": "ok"}
    try:
        yield h
    except Exception as e:  # registra a falha e repassa o erro
        concluir(id_, "falhou", f"{type(e).__name__}: {e}", time.time() - t0)
        raise
    concluir(id_, h.get("status", "ok"), h.get("resumo", ""), time.time() - t0, h.get("log"), h.get("extra"))


def evento(tarefa, status, resumo="", origem="automático", extra=None):
    """Registra algo instantâneo (ex.: alerta recebido) numa chamada só."""
    id_ = iniciar(tarefa, "", origem)
    concluir(id_, status, resumo, 0, extra=extra)
    return id_


def ler(limite=None):
    """Junta início e fim de cada execução; mais recentes primeiro."""
    if not ARQ.exists():
        return []
    por_id = {}
    with ARQ.open(encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            try:
                ev = json.loads(linha)
            except ValueError:
                continue
            por_id.setdefault(ev["id"], {}).update(ev)
    itens = sorted(por_id.values(), key=lambda e: e.get("inicio", ""), reverse=True)
    return itens[:limite] if limite else itens
