"""Testa o corretor da avaliação dos agentes (evals/avaliar.py) sem rodar nenhum modelo.

Usa respostas escritas à mão (tests/casos_avaliador/) com o veredito já conhecido, inclusive o relatório
alucinado de verdade da primeira rodada do piloto (relatorios/relatorio-finops-tentativa1-alucinado.md).
Termina com "RESULTADO: CORRETOR CONFIÁVEL" ou "RESULTADO: CORRETOR COM ERRO".
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "evals"))
import avaliar  # noqa: E402

falhas = []


def confere(ok, msg):
    if not ok:
        falhas.append(msg)
        print("  FALHA " + msg)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print("1. Leitura de números em pt-BR e en-US")
    for txt, esp in [("732", 732), ("732,00", 732), ("1.615,92", 1615.92), ("1615.92", 1615.92), ("4.762,83", 4762.83),
                     ("4762.83", 4762.83), ("4.762", 4762), ("2,2", 2.2), ("2.2", 2.2), ("50.000,00", 50000), ("0.005", 0.005)]:
        v = avaliar.para_numero(txt)
        confere(v is not None and abs(v - esp) < 1e-9, f"'{txt}' lido como {v}, esperado {esp}")
    confere(avaliar.reais("custou R$ 1.200,00 e R$850") == [1200.0, 850.0], "valores em R$ extraídos do texto")

    casos = {c["id"]: c for c in json.loads(avaliar.CASOS.read_text(encoding="utf-8"))["casos"]}
    universo = avaliar.Universo(avaliar.saida_das_ferramentas())
    for nome in ("vm-relatorios-dev", "stgbackupantigo", "lgc-desvios-processo", "rg-dados", "la-precos-logicapps"):
        confere(nome in universo.nomes, f"'{nome}' devia estar entre os nomes que as ferramentas mostram")

    print("2. Respostas boas: todas certas, nada inventado")
    boas = json.loads((ROOT / "tests/casos_avaliador/respostas_boas.json").read_text(encoding="utf-8"))
    confere(set(boas) == set(casos), "há uma resposta boa para cada caso de evals/casos.json")
    for cid, resp in boas.items():
        r = avaliar.corrigir(casos[cid], resp, universo)
        confere(r["situacao"] == "acertou" and not r["inventou"], f"{cid}: {r['situacao']} faltou={r['faltou']} inventou={r['inventou']}")

    print("3. Respostas ruins: cada erro conhecido tem que ser pego")
    ruins = json.loads((ROOT / "tests/casos_avaliador/respostas_ruins.json").read_text(encoding="utf-8"))
    esperado = {
        "finops-anomalias": ("errou", ["db-prod", "ec2-us-east-1", "s3-bucket-01", "50.000,00", "1.200,00", "850,00", "950,00"]),
        "finops-sem-dono": ("parcial", []),
        "finops-pico-vm": ("parcial", ["vm-producao-02"]),
        "finops-armadilha": ("errou", ["312,40"]),
        "docs-quando-roda": ("sem resposta", []),
        "ambientes-isolamento": ("parcial", ["vazou 'pip-teste-dev'", "vazou 'snap-build-dev-2026-03'"]),
        "ambientes-armadilha": ("errou", ["vm-pagamentos-hml", "4.210,00"]),
    }
    for cid, (situacao, inventos) in esperado.items():
        r = avaliar.corrigir(casos[cid], ruins[cid], universo)
        confere(r["situacao"] == situacao, f"{cid}: situação {r['situacao']}, esperado {situacao}")
        texto = " ".join(r["inventou"])
        for item in inventos:
            confere(item in texto, f"{cid}: não marcou como inventado '{item}' (marcou: {r['inventou']})")
        if not inventos:
            confere(not r["inventou"], f"{cid}: marcou invenção que não existe: {r['inventou']}")
    r = avaliar.corrigir(casos["finops-sem-dono"], ruins["finops-sem-dono"], universo)
    confere(r["faltou"] == ["732,00"], f"finops-sem-dono: devia faltar só o valor 732,00 (faltou {r['faltou']})")

    print("4. Respostas reais do modelo que estão certas (o corretor já errou nelas uma vez)")
    reais = json.loads((ROOT / "tests/casos_avaliador/respostas_reais_corretas.json").read_text(encoding="utf-8"))
    for cid, resp in reais.items():
        r = avaliar.corrigir(casos[cid], resp, universo)
        confere(r["situacao"] == "acertou" and not r["inventou"],
                f"{cid} (qwen3, 23/11): {r['situacao']}, faltou {r['faltou']}, inventou {r['inventou']}")

    print("5. Ferramenta escrita como texto (gemma3 e qwen3 1.7B, respostas reais) é detectada; respostas boas não")
    texto = json.loads((ROOT / "tests/casos_avaliador/respostas_ferramenta_texto.json").read_text(encoding="utf-8"))
    for cid, resp in texto.items():
        r = avaliar.corrigir(casos[cid], resp, universo)
        confere(r["ferramenta_em_texto"] and r["situacao"] == "errou", f"{cid}: ferramenta em texto não detectada ({r})")
    for cid, resp in {**boas, **reais}.items():
        r = avaliar.corrigir(casos[cid], resp, universo)
        confere(not r["ferramenta_em_texto"], f"{cid}: resposta boa marcada como ferramenta em texto")

    print()
    if falhas:
        print(f"{len(falhas)} falha(s).")
        print("RESULTADO: CORRETOR COM ERRO")
        return 1
    print("RESULTADO: CORRETOR CONFIÁVEL")
    return 0


if __name__ == "__main__":
    sys.exit(main())
