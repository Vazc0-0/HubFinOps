"""Confere que as páginas do hub têm a mesma cara e se navegam entre si (sem abrir navegador).

  1. painel FinOps (tools/hub_painel.html), operação (tools/hub_pagina.html) e documentos (tools/hub_documento.html)
     usam exatamente os mesmos tokens de cor do modo escuro e do modo claro;
  2. as três leem e gravam o tema no mesmo lugar (localStorage 'hub-tema') antes de desenhar a página;
  3. a barra de ícones é a mesma no painel e na operação: mesmos destinos, mesmos nomes e mesmos desenhos;
  4. cada ícone da operação abre uma seção que existe, e cada seção tem o seu ícone;
  5. nenhuma cor fixa da identidade antiga (azul-marinho e laranja) sobrou nas páginas.

Uso:  python tests/testar_paginas_hub.py      Termina com "RESULTADO: PÁGINAS DO HUB CONSISTENTES".
"""
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
PAGINAS = {nome: (TOOLS / f"{nome}.html").read_text(encoding="utf-8") for nome in ("hub_painel", "hub_pagina", "hub_documento")}

ok, falhas = 0, []


def confere(cond, msg):
    global ok
    if cond:
        ok += 1
    else:
        falhas.append(msg)
    return cond


def tokens(html, seletor):
    m = re.search(re.escape(seletor) + r"\{([^}]*)\}", html)
    return dict(re.findall(r"(--[\w-]+):\s*([^;]+);", m.group(1))) if m else {}


def trilho(html):
    m = re.search(r'<nav class="icones".*?</nav>', html, re.S)
    if not m:
        return []
    return [(a.group(1), a.group(2), re.sub(r"\s+", " ", a.group(3)))
            for a in re.finditer(r'<a class="ico" href="([^"]+)" data-s="(\w+)"[^>]*>(.*?)</a>', m.group(0), re.S)]


# 1. mesmos tokens
for seletor in (':root, [data-tema="escuro"]', '[data-tema="claro"]'):
    base = tokens(PAGINAS["hub_painel"], seletor)
    confere(len(base) > 20, f"painel tem os tokens de {seletor}")
    for nome, html in PAGINAS.items():
        t = tokens(html, seletor)
        diferentes = sorted(k for k in base if t.get(k) != base[k])
        confere(not diferentes, f"{nome}: tokens de {seletor} diferentes do painel: {diferentes}")

# 2. mesmo tema salvo
for nome, html in PAGINAS.items():
    head = html.split("</head>")[0]
    confere("localStorage.getItem('hub-tema')" in head, f"{nome} aplica o tema salvo antes de desenhar")
    confere("localStorage.setItem('hub-tema'" in html, f"{nome} grava a troca de tema")
    confere('data-tema="escuro"' in html.split(">", 2)[1] + ">", f"{nome} começa no modo escuro")

# 3. mesma barra de ícones
t_painel, t_operacao = trilho(PAGINAS["hub_painel"]), trilho(PAGINAS["hub_pagina"])
confere(len(t_painel) >= 9, f"barra do painel com todos os ícones: {len(t_painel)}")
confere(t_painel == t_operacao, "barra de ícones igual no painel e na operação")
desenhos = [d for _, _, d in t_painel]
confere(len(set(desenhos)) == len(desenhos), "cada ícone tem um desenho diferente")
confere(len(re.findall(r'class="ico tema"', PAGINAS["hub_pagina"])) == 1, "operação tem o botão de tema na barra")

# 4. ícone ↔ seção
secoes = set(re.findall(r'<section id="s-(\w+)"', PAGINAS["hub_pagina"]))
alvos = {s for href, s, _ in t_operacao if href.startswith("/operacao#")}
confere(all(href == f"/operacao#{s}" for href, s, _ in t_operacao if s != "finops"), "cada ícone leva à seção do mesmo nome")
confere(alvos == secoes, f"ícones × seções: sem ícone {sorted(secoes - alvos)}, sem seção {sorted(alvos - secoes)}")
confere(any(href == "/" for href, _, _ in t_operacao), "a operação tem o ícone de volta ao painel FinOps")
nav = (re.search(r'<nav class="icones".*?</nav>', PAGINAS["hub_pagina"], re.S) or re.search("", "")).group(0)
confere(nav and len(re.findall(r'class="ico[ "]', nav)) == nav.count("data-rotulo="), "todo ícone mostra o nome ao passar o mouse")

# 5. nada da identidade antiga
for nome, html in PAGINAS.items():
    velhas = [c for c in ("#14213D", "#2F6FEB", "#E8833A", "#F4F5F2", "Rubik", "IBM Plex") if c.lower() in html.lower()]
    confere(not velhas, f"{nome}: sobrou estilo antigo {velhas}")
confere("theme=${" in PAGINAS["hub_pagina"], "painéis do Grafana seguem o tema do hub")

total = ok + len(falhas)
print(f"Páginas do hub: {ok}/{total} verificações")
for f in falhas:
    print("  FALHOU:", f)
print("\nRESULTADO:", "PÁGINAS DO HUB CONSISTENTES" if not falhas else f"REPROVADO ({len(falhas)} problema(s))")
sys.exit(0 if not falhas else 1)
