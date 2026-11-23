#!/usr/bin/env bash
# Trilha dos vídeos sem voz: "Motivating Mornings", Ahjay Stelino (Mixkit Stock Music Free License).
# Uso: ./musica.sh <video_mudo.mp4> <saida.mp4>
set -euo pipefail
VIDEO="$1"; SAIDA="$2"
[ -f trilha.mp3 ] || curl -sL -o trilha.mp3 https://assets.mixkit.co/music/33/33.mp3
# A faixa tem 1:36. Para chegar a ~1:52, repete 8 compassos (15,866 s, medidos por correlação do áudio)
# a partir de 38,22 s, numa batida, com 0,12 s de transição.
T1=38.220; OFF=15.866
ffmpeg -y -loglevel error -i trilha.mp3 -filter_complex \
  "[0:a]atrim=0:$(echo "$T1+0.06" | bc),asetpts=N/SR/TB[a];[0:a]atrim=$(echo "$T1-$OFF-0.06" | bc),asetpts=N/SR/TB[b];[a][b]acrossfade=d=0.12:c1=tri:c2=tri" \
  -ar 48000 -ac 2 trilha_longa.wav
TOTAL=$(ffprobe -v error -show_entries format=duration -of csv=p=0 trilha_longa.wav)
D=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$VIDEO")
# começa a trilha mais tarde para o final da música coincidir com o final do vídeo
INICIO=$(echo "x=$TOTAL-$D; if (x<0) x=0; scale=3; x/1" | bc | sed "s/^\./0./")
ffmpeg -y -loglevel error -ss "$INICIO" -i trilha_longa.wav \
  -af "atrim=0:$D,afade=t=in:st=0:d=0.8,afade=t=out:st=$(echo "$D-1.5" | bc):d=1.5,loudnorm=I=-18:TP=-1.5:LRA=11" \
  -ar 48000 -ac 2 trilha_final.wav
ffmpeg -y -loglevel error -i "$VIDEO" -i trilha_final.wav -map 0:v -map 1:a -c:v copy -c:a aac -b:a 160k -shortest -movflags +faststart "$SAIDA"
echo "ok: $SAIDA"
