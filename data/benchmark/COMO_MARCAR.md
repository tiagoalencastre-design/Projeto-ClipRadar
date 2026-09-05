# Como montar o gabarito de qualidade

Este é o único passo que só você pode dar. Os 523 testes provam que o
software funciona como especificado; **nenhum deles prova que o ClipRadar
escolhe os melhores momentos.** Isso depende do seu julgamento sobre os
seus VODs.

## O que fazer

Há 10 arquivos prontos em `data/benchmark/` — 3 Valorant, 2 CS2, 2 Fortnite,
2 Warzone e 1 GTA. Para cada um:

1. Escolha um VOD seu e coloque o nome do arquivo no campo `video`
2. Assista e anote os momentos que **você postaria de verdade**
3. Preencha `moments` com tempos em segundos (12:30 = 750)
4. Marque de 8 a 12 momentos por VOD

Exemplo preenchido:

```json
{
  "video": "live_ranked_2026-03-14.mp4",
  "game": "valorant",
  "moments": [
    {"start": 750,  "end": 778,  "label": "clutch 1v3 no site B"},
    {"start": 1420, "end": 1445, "label": "reação ao ace do time"},
    {"start": 2810, "end": 2860, "label": "história do banimento"}
  ]
}
```

## Depois

```bash
# 1. Gera a análise de cada VOD (não renderiza clipe, só analisa)
python -m core.pipeline --video "data/vods/SUA_CHAVE/live_ranked_2026-03-14.mp4" \
                       --output data/benchmark/analysis/valorant_01.json

# 2. Roda o benchmark
python run_benchmark.py
```

O nome do arquivo de análise precisa ser **igual** ao do gabarito.

## O que os números significam

```
@5    recall 60%   precisão 80%
@10   recall 85%   precisão 55%
@20   recall 95%   precisão 30%
```

**recall@5** — dos momentos que você marcou, quantos apareceram entre os 5
primeiros. É o número que mais importa: o criador olha os primeiros clipes.

**precisão@5** — dos 5 primeiros, quantos eram bons de verdade. Mede quanto
lixo aparece no topo.

**Recall@20 alto com recall@5 baixo** é o diagnóstico mais útil que este
relatório dá: significa que o sistema ACHA os bons momentos mas ORDENA mal.
É um problema de scoring, não de detecção — e se conserta ajustando pesos,
não reescrevendo o motor.

A lista de "PASSOU BATIDO" mostra o que o sistema não encontrou. É de lá que
saem as ideias de melhoria.

## Por que 10 VODs

Com 1 ou 2, qualquer ajuste "melhora" por sorte. Com 10 e vários jogos, uma
melhora consistente é melhora de verdade — e dá pra ver se o sistema vai bem
em FPS e mal em GTA, por exemplo.

Se 10 for muito, **comece com 3.** Três VODs medidos valem
infinitamente mais que dez planejados.
