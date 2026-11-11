"""Confere se a detecção encontra EXATAMENTE as anomalias plantadas.

Uso:  python tests/validar_gabarito.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import cost_query  # noqa: E402

gabarito = json.loads((ROOT / "data" / "anomalias_esperadas.json").read_text(encoding="utf-8"))
series, meta = cost_query.load()
achados = cost_query._estende_picos(series, cost_query.detectar(series, meta))

esperado = {(a["recurso"], a["tipo"], a["inicio"], a["fim"]) for a in gabarito}
obtido = {(a["recurso"], a["tipo"], a["inicio"].isoformat(), a["fim"].isoformat()) for a in achados}

for item in sorted(esperado & obtido):
    print("OK         ", *item)
for item in sorted(esperado - obtido):
    print("NÃO ACHOU  ", *item)
for item in sorted(obtido - esperado):
    print("FALSO ALARME", *item)

ok = esperado == obtido
print("\nRESULTADO:", "PASSOU" if ok else "FALHOU")
sys.exit(0 if ok else 1)
