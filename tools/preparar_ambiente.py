"""Cria o arquivo .env com um segredo aleatório para assinar os alertas do Grafana (só se ainda não existir).

O docker compose lê o .env sozinho: o Grafana assina cada alerta com esse segredo (HMAC-SHA256) e o
receptor de chamados recusa alerta sem assinatura certa. O .env fica fora do Git (.gitignore).

Uso:  python tools/preparar_ambiente.py      e depois   docker compose up -d --build
"""
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
CHAVE = "PILOTO_WEBHOOK_SEGREDO"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    linhas = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    atual = next((l.split("=", 1)[1].strip() for l in linhas if l.startswith(CHAVE + "=")), "")
    if len(atual) >= 16 and "troque" not in atual:
        print(f".env já tem {CHAVE} (nada mudou).")
    else:
        linhas = [l for l in linhas if not l.startswith(CHAVE + "=")] + [f"{CHAVE}={secrets.token_hex(32)}"]
        ENV.write_text("\n".join(linhas) + "\n", encoding="utf-8")
        print(f".env criado com um {CHAVE} novo (64 caracteres aleatórios).")
    print("RESULTADO: AMBIENTE PREPARADO")
    return 0


if __name__ == "__main__":
    sys.exit(main())
