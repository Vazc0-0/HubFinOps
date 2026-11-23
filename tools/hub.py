"""Hub do Piloto Agentes de IA: uma página local com tudo junto.

  - Visão geral: último resultado de cada coisa (testes, FinOps, Logic Apps, Azure, chamados, serviços)
  - Executar: botões que rodam as tarefas (as mesmas de tools/rodar.py) com o log ao vivo
  - Histórico: tudo o que rodou, de onde veio (hub, terminal, hook do agente, alerta do Grafana) e o resultado
  - Resultados: anomalias de custo, documentação das Logic Apps, Logic App real (previsto × medido)
  - Chamados: abertos pelos alertas do Grafana, com o diagnóstico
  - Grafana: os painéis dentro da página
  - Métodos de teste: como cada coisa é conferida
  - Documentos: relatórios, docs geradas e PDFs

Uso (na raiz do projeto):  python tools/hub.py          -> abre http://localhost:8090 no navegador
                           python tools/hub.py --sem-abrir
Só escuta em 127.0.0.1 (esta máquina). Os botões só rodam as tarefas da lista de tools/rodar.py.
No docker compose ele roda num container (HUB_HOST=0.0.0.0), mas a porta só é publicada em 127.0.0.1.
Pedidos para executar tarefas só valem vindos da própria página (cabeçalho X-Piloto-Hub e Host local):
outro site aberto no navegador não consegue disparar tarefas.
"""
import html
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import historico  # noqa: E402
import rodar  # noqa: E402

ROOT = historico.ROOT
PORTA = 8090
GRAFANA = os.environ.get("GRAFANA_URL", "http://localhost:3000")  # usado pelo hub (no compose: http://grafana:3000)
GRAFANA_NAVEGADOR = os.environ.get("GRAFANA_URL_NAVEGADOR", "http://localhost:3000")  # usado pela página no navegador
RECEPTOR = os.environ.get("RECEPTOR_URL_HUB", "http://localhost:8088")
HOSTS_LOCAIS = {"localhost", "127.0.0.1", "[::1]"}
EXTENSOES = {".md": "text/markdown", ".pdf": "application/pdf", ".json": "application/json", ".log": "text/plain",
             ".png": "image/png", ".csv": "text/csv"}
RODANDO = {}  # tarefa -> id da execução em andamento (iniciada pelo hub)
TRAVA = threading.Lock()


# ------------------------------------------------------------------ dados
def _seguro(f, padrao=None):
    try:
        return f()
    except Exception as e:  # noqa: BLE001  (o hub nunca cai por causa de um bloco)
        return padrao if padrao is not None else {"erro": f"{type(e).__name__}: {e}"}


def servico(url):
    try:
        with urllib.request.urlopen(url, timeout=1.5) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def ultimo(hist, tarefa):
    return next((h for h in hist if h.get("tarefa") == tarefa and h.get("status") != "em andamento"), None)


def finops():
    import cost_query as cq
    series, meta = cq.load()
    ach = cq._estende_picos(series, cq.detectar(series, meta))
    itens = sorted(({"recurso": a["recurso"], "tipo": cq.TIPO_PT[a["tipo"]], "servico": meta[a["recurso"]]["servico"],
                     "inicio": a["inicio"].strftime("%d/%m/%Y"), "fim": a["fim"].strftime("%d/%m/%Y"),
                     "custo_extra": round(cq.custo_extra(series, a), 2),
                     "prioridade": cq.prioridade(cq.custo_extra(series, a)), "detalhe": a["detalhe"]} for a in ach),
                   key=lambda x: -x["custo_extra"])
    rel = ROOT / "relatorios" / "relatorio-finops.md"
    return {"anomalias": itens, "total": round(sum(i["custo_extra"] for i in itens), 2),
            "relatorio": "relatorios/relatorio-finops.md" if rel.exists() else None,
            "relatorio_em": (datetime.fromtimestamp(rel.stat().st_mtime).astimezone().isoformat(timespec="seconds")
                             if rel.exists() else None)}


def logicapps():
    import doc_logicapp as dl
    out = []
    for n in dl.nomes():
        i = dl.analisar(n)
        doc = ROOT / "docs" / "logicapps" / f"{n}.md"
        out.append({"nome": n, "real": not i.get("ficticio"), "gatilho": i["gatilho"]["texto"] if i["gatilho"] else "-",
                    "acoes": len(i["acoes"]), "trata_erro": i["trata_erro"],
                    "conectores": [dl.con_pt(c) for c in i["conectores"]],
                    "achados": [{"regra": r, "onde": o, "severidade": dl.lp.REGRAS[r][0]} for r, o, _ in i["achados"]],
                    "doc": f"docs/logicapps/{n}.md" if doc.exists() else None})
    return out


def ranking_logicapps():
    """Logic Apps que mais custam: custo diário de cada uma nos dados de custo (formato FOCUS) + a real medida no Azure."""
    import cost_query as cq
    series, meta = cq.load()
    fim = max(d for s in series.values() for d in s)
    out = []
    for nome, dias in series.items():
        if meta[nome]["servico"] != "Logic Apps":
            continue
        ult = sum(v for d, v in dias.items() if (fim - d).days < 30)
        ant = sum(v for d, v in dias.items() if 30 <= (fim - d).days < 60)
        out.append({"nome": nome, "origem": "dados de custo (fictícios)", "real": False,
                    "custo_30d": round(ult, 2), "custo_30d_anteriores": round(ant, 2),
                    "variacao_pct": round((ult / ant - 1) * 100, 1) if ant else None,
                    "custo_periodo": round(sum(dias.values()), 2), "grupo": meta[nome]["rg"],
                    "dono": meta[nome]["tags"].get("owner")})
    try:  # Logic App real: custo do mês calculado com as ações medidas pelo Azure Monitor e os preços oficiais
        import carregar_grafana as cg
        for arq in sorted((ROOT / "relatorios" / "azure").glob("*-execucoes.json")):
            la = arq.name[:-len("-execucoes.json")]
            p = cg.previsto_x_medido(la)
            out.append({"nome": la, "origem": "medido no Azure", "real": True, "custo_30d": round(p.get("custo_mes_brl") or 0, 2),
                        "custo_30d_anteriores": None, "variacao_pct": None, "custo_periodo": None, "grupo": None, "dono": None,
                        "acoes_mes": round((p.get("medido_por_execucao") or p.get("previsto_por_execucao") or 0)
                                           * p.get("execucoes_mes", 0))})
    except Exception:  # noqa: BLE001  (sem Azure sincronizado, o ranking mostra só os dados de custo)
        pass
    out.sort(key=lambda x: -x["custo_30d"])
    return {"itens": out, "ate": fim.strftime("%d/%m/%Y")}


def azure():
    import carregar_grafana as cg
    az = ROOT / "relatorios" / "azure"
    out = []
    for arq in sorted(az.glob("*-execucoes.json")):
        la = arq.name[:-len("-execucoes.json")]
        execs = json.loads(arq.read_text(encoding="utf-8"))
        sim = json.loads((az / "simulacao_falha.json").read_text(encoding="utf-8")) if (az / "simulacao_falha.json").exists() else []
        out.append({"logic_app": la, "previsto": cg.previsto_x_medido(la),
                    "execucoes": [{"execucao": e["execucao"], "status": e["status"], "inicio": e["inicio"],
                                   "rodaram": sum(1 for s in e["acoes"].values() if s != "Skipped"),
                                   "total": len(e["acoes"])} for e in execs][:10],
                    "simuladas": len([s for s in sim if s["logic_app"] == la]),
                    "sincronizado_em": datetime.fromtimestamp(arq.stat().st_mtime).astimezone().isoformat(timespec="seconds")})
    precos = az / "precos_logicapps.json"
    return {"logic_apps": out, "precos": json.loads(precos.read_text(encoding="utf-8")) if precos.exists() else None,
            "configurado": (ROOT / "config" / "azure.json").exists()}


def agendador():
    arq = ROOT / "relatorios" / "agendador.json"
    e = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
    atrasado = None
    if e.get("a_cada_h") and e.get("ultima_rodada"):
        horas = (time.time() - datetime.fromisoformat(e["ultima_rodada"]).timestamp()) / 3600
        atrasado = horas > 2 * float(e["a_cada_h"])
    return {**e, "atrasado": atrasado}


def chamados():
    pasta = ROOT / "chamados"
    out = []
    for arq in sorted(pasta.glob("CH-*.json"), reverse=True):
        c = json.loads(arq.read_text(encoding="utf-8"))
        c["md"] = f"chamados/{arq.stem}.md"
        out.append(c)
    return out


def documentos():
    grupos = {"PDFs": sorted(ROOT.glob("docs/pdf/*.pdf")),
              "Relatórios FinOps": sorted(ROOT.glob("relatorios/relatorio-finops*.md")),
              "Documentação das Logic Apps": sorted(ROOT.glob("docs/logicapps/*.md")),
              "Comparações de versões": sorted(ROOT.glob("docs/comparacoes/*.md")),
              "Guias": [p for p in (ROOT / "README.md", ROOT / "azure" / "LEIA-ME.md", ROOT / "logicapps" / "reais" / "LEIA-ME.md")
                        if p.exists()]}
    return {g: [{"nome": p.name, "caminho": p.relative_to(ROOT).as_posix(),
                 "alterado_em": datetime.fromtimestamp(p.stat().st_mtime).astimezone().isoformat(timespec="seconds")} for p in ps]
            for g, ps in grupos.items()}


def estado():
    hist = historico.ler(300)
    andamento = [h for h in hist if h.get("status") == "em andamento"]
    agora = time.time()
    for h in andamento:  # execução que não terminou há mais de 2 h (ex.: terminal fechado) não fica "rodando" para sempre
        try:
            if agora - datetime.fromisoformat(h["inicio"]).timestamp() > 7200:
                h["status"] = "sem resposta"
        except (KeyError, ValueError):
            pass
    tarefas = [{"id": k, "titulo": t, "descricao": d, "grupo": g, "comando": " ".join("python" if c == rodar.PY else c for c in cmd),
                "rodando": k in RODANDO, "ultimo": ultimo(hist, t), "indisponivel": rodar.falta(k)}
               for k, (t, cmd, d, g) in rodar.TAREFAS.items()]
    return {"gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
            "servicos": {"grafana": servico(f"{GRAFANA}/api/health"), "receptor": servico(f"{RECEPTOR}/")},
            "tarefas": tarefas, "historico": hist, "em_andamento": [h for h in hist if h.get("status") == "em andamento"],
            "finops": _seguro(finops), "logicapps": _seguro(logicapps, []), "azure": _seguro(azure),
            "ranking_logicapps": _seguro(ranking_logicapps, {"itens": []}), "chamados": _seguro(chamados, []),
            "documentos": _seguro(documentos, {}), "agendador": _seguro(agendador, {}),
            "grafana": {"url": GRAFANA_NAVEGADOR, "paineis": [
                {"uid": "piloto-operacao", "titulo": "Logic App real e operação do piloto"},
                {"uid": "finops-custos-demo", "titulo": "FinOps: custos Azure (dados sintéticos)"}]}}


# ------------------------------------------------------------------ execução pelos botões
def executar(tarefa):
    with TRAVA:
        if tarefa in RODANDO:
            return False
        RODANDO[tarefa] = True

    def alvo():
        try:
            for t in (rodar.SEQUENCIA_TUDO if tarefa == "tudo" else [tarefa]):
                if rodar.falta(t):  # ex.: Azure no hub em Docker: registra o motivo e segue
                    historico.evento(rodar.TAREFAS[t][0], "pulada", rodar.falta(t), origem="hub")
                    continue
                rodar.rodar(t, origem="hub")
        finally:
            with TRAVA:
                RODANDO.pop(tarefa, None)
    threading.Thread(target=alvo, daemon=True).start()
    return True


# ------------------------------------------------------------------ markdown -> HTML (docs, relatórios, chamados)
def _inline(t):
    t = html.escape(t, quote=False)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\*)\*([^*\s][^*]*)\*(?!\*)", r"<em>\1</em>", t)
    t = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", lambda m: _wikilink(m.group(1), m.group(2)), t)
    t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', t)
    return t


def _wikilink(nome, rotulo):
    for pasta in ("docs/logicapps", "chamados", "relatorios"):
        if (ROOT / pasta / f"{nome}.md").exists():
            return f'<a href="/ver?arquivo={urllib.parse.quote(f"{pasta}/{nome}.md")}">{rotulo or nome}</a>'
    return rotulo or nome


def markdown(texto):
    linhas = texto.splitlines()
    if linhas and linhas[0].strip() == "---":  # tira o frontmatter do Obsidian
        fim = next((i for i, l in enumerate(linhas[1:], 1) if l.strip() == "---"), 0)
        linhas = linhas[fim + 1:]
    out, i = [], 0
    while i < len(linhas):
        l = linhas[i]
        if l.startswith("```"):
            lang, bloco = l[3:].strip(), []
            i += 1
            while i < len(linhas) and not linhas[i].startswith("```"):
                bloco.append(linhas[i])
                i += 1
            corpo = html.escape("\n".join(bloco))
            out.append(f'<pre class="mermaid">{corpo}</pre>' if lang == "mermaid" else f"<pre><code>{corpo}</code></pre>")
        elif re.match(r"^#{1,6} ", l):
            n = len(l) - len(l.lstrip("#"))
            out.append(f"<h{n}>{_inline(l[n + 1:])}</h{n}>")
        elif l.startswith("|"):
            tab = []
            while i < len(linhas) and linhas[i].startswith("|"):
                tab.append([c.strip() for c in linhas[i].strip().strip("|").split("|")])
                i += 1
            i -= 1
            cab, corpo = tab[0], [r for r in tab[1:] if not set("".join(r)) <= set("-: ")]
            out.append("<div class='tabela'><table><thead><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in cab)
                       + "</tr></thead><tbody>" + "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>"
                                                          for r in corpo) + "</tbody></table></div>")
        elif re.match(r"^\s*([-*]|\d+\.) ", l):
            ordenada = bool(re.match(r"^\s*\d+\. ", l))
            itens = []
            while i < len(linhas) and re.match(r"^\s*([-*]|\d+\.) ", linhas[i]):
                itens.append(re.sub(r"^\s*([-*]|\d+\.) ", "", linhas[i]))
                i += 1
            i -= 1
            tag = "ol" if ordenada else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{_inline(x)}</li>" for x in itens) + f"</{tag}>")
        elif l.startswith(">"):
            out.append(f"<blockquote>{_inline(l.lstrip('> '))}</blockquote>")
        elif l.strip() == "---":
            out.append("<hr>")
        elif l.strip():
            out.append(f"<p>{_inline(l)}</p>")
        i += 1
    return "\n".join(out)


def arquivo_seguro(rel):
    p = (ROOT / rel).resolve()
    if ROOT.resolve() not in p.parents or p.suffix.lower() not in EXTENSOES or not p.is_file():
        return None
    return p


# ------------------------------------------------------------------ HTTP
class Hub(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _envia(self, codigo, corpo, tipo):
        b = corpo if isinstance(corpo, bytes) else corpo.encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/":
            return self._envia(200, _pagina("hub_pagina.html", "<h1>hub_pagina.html não encontrado</h1>"), "text/html; charset=utf-8")
        if u.path == "/api/estado":
            return self._envia(200, json.dumps(estado(), ensure_ascii=False, default=str), "application/json; charset=utf-8")
        if u.path.startswith("/api/log/"):
            id_ = re.sub(r"[^\w\-]", "", u.path.rsplit("/", 1)[-1])
            p = historico.LOGS / f"{id_}.log"
            return self._envia(200, p.read_text(encoding="utf-8", errors="replace") if p.exists() else "(sem log)",
                               "text/plain; charset=utf-8")
        if u.path in ("/ver", "/arquivo"):
            p = arquivo_seguro((q.get("arquivo") or [""])[0])
            if not p:
                return self._envia(404, "Arquivo não encontrado ou não permitido.", "text/plain; charset=utf-8")
            if u.path == "/arquivo" or p.suffix.lower() != ".md":
                return self._envia(200, p.read_bytes(), EXTENSOES[p.suffix.lower()]
                                   + ("; charset=utf-8" if p.suffix.lower() in (".json", ".log", ".csv") else ""))
            corpo = markdown(p.read_text(encoding="utf-8", errors="replace"))
            return self._envia(200, _pagina("hub_documento.html", "{{corpo}}").replace("{{titulo}}", html.escape(p.name))
                               .replace("{{caminho}}", html.escape(p.relative_to(ROOT).as_posix()))
                               .replace("{{corpo}}", corpo), "text/html; charset=utf-8")
        return self._envia(404, "Não encontrado", "text/plain; charset=utf-8")

    def _pedido_local(self):
        """Só a própria página pode executar: Host local (contra DNS rebinding) e cabeçalho próprio.
        Um site qualquer não consegue mandar esse cabeçalho sem a permissão de CORS, que o hub nunca dá."""
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].lower()
        return host in HOSTS_LOCAIS and self.headers.get("X-Piloto-Hub") == "1"

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path.startswith("/api/executar/"):
            if not self._pedido_local():
                return self._envia(403, json.dumps({"erro": "pedido fora da página do hub"}), "application/json")
            t = u.path.rsplit("/", 1)[-1]
            if t != "tudo" and t not in rodar.TAREFAS:
                return self._envia(400, json.dumps({"erro": "tarefa desconhecida"}), "application/json")
            if t != "tudo" and rodar.falta(t):
                return self._envia(409, json.dumps({"erro": rodar.falta(t)}, ensure_ascii=False), "application/json; charset=utf-8")
            iniciou = executar(t)
            return self._envia(200, json.dumps({"iniciou": iniciou}), "application/json")
        return self._envia(404, "Não encontrado", "text/plain; charset=utf-8")


def _pagina(nome, padrao):
    """Lê a página a cada pedido: ao atualizar o HTML, basta recarregar o navegador."""
    arq = Path(__file__).resolve().parent / nome
    return arq.read_text(encoding="utf-8") if arq.exists() else padrao


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    porta = int(argv[argv.index("--porta") + 1]) if "--porta" in argv else PORTA
    srv = ThreadingHTTPServer((os.environ.get("HUB_HOST", "127.0.0.1"), porta), Hub)
    url = f"http://localhost:{porta}"
    print(f"Hub do piloto no ar: {url}   (Ctrl+C para parar)")
    if "--sem-abrir" not in argv:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nHub encerrado.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
