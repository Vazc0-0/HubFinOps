"""Trilha de áudio e legendas .srt do vídeo, com os mesmos tempos das cenas (roteiro_final.json, gerado pelo render.js).

Cada fala começa 0,35 s depois do início da sua cena e é completada com silêncio até o fim da cena; o volume final é
normalizado em -16 LUFS. As legendas usam a mesma divisão em pedaços das legendas queimadas no vídeo (palco.html).
Uso (nesta pasta, depois de narrar.py e render.js):  python audio.py   -> narracao.wav e legendas.srt
"""
import json
import re
import subprocess
from pathlib import Path

LIMITE = 78  # caracteres por pedaço de legenda


def pedacos(texto):
    """Divide a legenda por frase e, se a frase for longa, por vírgula (sem quebrar números como 18,6 ou 2.300)."""
    out = []
    for frase in [x.strip() for x in re.split(r"(?<=[.!?:])\s+", texto) if x.strip()]:
        if len(frase) <= LIMITE:
            out.append(frase)
            continue
        partes = re.split(r",\s+", frase)
        atual = ""
        for i, parte in enumerate(partes):
            pedaco = parte + ("," if i < len(partes) - 1 else "")
            if len((atual + " " + pedaco).strip()) > LIMITE and atual:
                out.append(atual.strip())
                atual = pedaco
            else:
                atual += " " + pedaco
        if atual.strip():
            out.append(atual.strip())
    return out


def tempo_srt(t):
    h, resto = divmod(t, 3600)
    m, s = divmod(resto, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{round((s - int(s)) * 1000):03d}"


def main():
    roteiro = json.loads(Path("roteiro_final.json").read_text(encoding="utf-8"))
    arquivos = []
    for cena in roteiro:
        saida = f"voz/{cena['id']}.cena.wav"
        filtro = f"aresample=48000,adelay={int(cena['voz_ini'] * 1000)}:all=1,apad,atrim=0:{cena['dur']}"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", f"voz/{cena['id']}.wav", "-af", filtro,
                        "-ac", "2", "-ar", "48000", saida], check=True)
        arquivos.append(Path(saida).name)
    Path("voz/lista.txt").write_text("".join(f"file '{a}'\n" for a in arquivos), encoding="utf-8")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "voz/lista.txt",
                    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000", "-c:a", "pcm_s16le", "narracao.wav"], check=True)

    linhas, n, base = [], 1, 0.0
    for cena in roteiro:
        pcs = pedacos(cena["legenda"])
        total = sum(len(p) for p in pcs)
        inicio = base + cena["voz_ini"]
        for p in pcs:
            dur = cena["dur_voz"] * len(p) / total
            linhas.append(f"{n}\n{tempo_srt(inicio)} --> {tempo_srt(inicio + dur)}\n{p}\n")
            n += 1
            inicio += dur
        base += cena["dur"]
    Path("legendas.srt").write_text("\n".join(linhas), encoding="utf-8")
    print(f"narracao.wav e legendas.srt: {base:.2f} s, {n - 1} legendas")


if __name__ == "__main__":
    main()
