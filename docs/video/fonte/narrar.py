"""Narração do vídeo: gera um .wav por cena a partir de roteiro.json, com a voz pt-BR "faber" do Piper (licença CC0).

Uso (nesta pasta):  pip install piper-tts onnxruntime
                    baixe pt_BR-faber-medium.onnx e .onnx.json de huggingface.co/rhasspy/piper-voices para vozes/
                    python narrar.py            (outra voz: PIPER_VOZ=vozes/pt_BR-cadu-medium.onnx python narrar.py)
Grava voz/<cena>.wav e roteiro_tempos.json (duração de cada fala, usada pelo render.js para o tempo de cada cena).
"""
import json
import os
import wave
from pathlib import Path

from piper import PiperVoice, SynthesisConfig

voz = PiperVoice.load(os.environ.get("PIPER_VOZ", "vozes/pt_BR-faber-medium.onnx"))
cfg = SynthesisConfig(length_scale=1.07)  # um pouco mais devagar que o padrão: tom de apresentação
roteiro = json.loads(Path("roteiro.json").read_text(encoding="utf-8"))
Path("voz").mkdir(exist_ok=True)
for cena in roteiro:
    arq = f"voz/{cena['id']}.wav"
    with wave.open(arq, "wb") as w:
        voz.synthesize_wav(cena["fala"], w, syn_config=cfg)
    with wave.open(arq) as w:
        cena["dur_voz"] = round(w.getnframes() / w.getframerate(), 3)
    print(cena["id"], cena["dur_voz"], "s")
Path("roteiro_tempos.json").write_text(json.dumps(roteiro, ensure_ascii=False, indent=1), encoding="utf-8")
print("total de voz:", round(sum(c["dur_voz"] for c in roteiro), 1), "s")
