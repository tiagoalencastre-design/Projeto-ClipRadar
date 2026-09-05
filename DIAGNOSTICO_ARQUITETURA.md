# ClipRadar — arquitetura real (V3)

> Este documento foi **reescrito** para refletir o estado real do projeto.
> A versão anterior descrevia o sistema antes das reestruturações e afirmava
> coisas que deixaram de ser verdade (2 tabelas no banco, 7 sinais de score,
> jobs vivendo só em memória). Um mapa errado é pior que nenhum mapa.

## Visão geral

VOD longo de gameplay entra; clipes verticais prontos para publicação saem.
Tudo roda localmente: FFmpeg, Whisper e PySceneDetect na máquina do usuário.
**Nenhuma IA participa das decisões editoriais nesta fase.**

## Fluxo de processamento

```
vídeo
  ↓ core/detection.py      picos de áudio (librosa) + cortes de cena (PySceneDetect)
  ↓ core/transcription.py  faster-whisper, CPU, modelo medium, timestamps por palavra
  ↓ core/events.py         sinais viram eventos tipados, com categoria e confiança
  ↓ core/story.py          agrupa eventos relacionados; separa os independentes
  ↓ core/candidates.py     cada história gera vários candidatos (6 tipos)
  ↓ core/boundaries.py     hook / payoff / exit derivados da transcrição
  ↓ core/editorial.py      scoring heurístico por 8 componentes
  ↓ core/dedup.py          deduplicação por conteúdo + diversidade
  ↓ core/discovery.py      ÚNICA autoridade de seleção
  ↓ core/edit_plan.py      plano editorial (opcional, só com chave de IA)
  ↓ core/montage.py        renderização FFmpeg
clipes
```

`core/pipeline.py :: run_pipeline()` orquestra e grava `analysis.json`.

## Estado do banco

Oito tabelas em SQLite: `users`, `sessions`, `projects`, `videos`, `clips`,
`jobs`, `usage_events`, `clip_feedback`.

Todas são preenchidas durante o uso real. Jobs sobrevivem a restart; os que
estavam rodando quando o processo caiu ficam marcados como `interrupted`
em vez de desaparecer.

## Camada de IA (desligada)

`core/ai_providers/` define `TextProvider` como interface e
`OpenAITextProvider` como única implementação. `registry.py` decide qual
usar por tarefa. Sem chave configurada — ou em modo `mock` — devolve `None`
e o pipeline segue pelo caminho gratuito.

`core/editorial.py` define `EditorialAnalyzer`, com
`HeuristicEditorialAnalyzer` como implementação atual. É o ponto onde uma
IA futura entra sem que eventos, histórias, candidatos, seleção ou
renderização precisem mudar.

## Scoring

Dezesseis sinais declarados. Os implementados usam dado real que o pipeline
já extrai. Os que não têm base (`share_potential`, `vertical_suitability`,
`viral_potential`) ficam com peso zero — número inventado desloca a escolha
sem ninguém perceber.

O peso mais alto é `standalone`: *"quem assistir só este clipe entende o que
aconteceu?"*

## Planos

`core/plans.py` — grátis (90 min/mês, 7 dias, marca d'água), Pro (400 min,
30 dias) e Studio (1.200 min, 90 dias, fila prioritária, Brand Kit). Preços
por região. **Sem integração de pagamento.**

## Código legado

- `core/legacy/scoring.py` — motor antigo, 1 candidato por história. Não é usado
  pelo pipeline. Mantido só como referência de comparação.
- `core/v2_adapter.py` — converte `ClipCandidate` para o formato antigo do
  `analysis.json`, para não quebrar o front-end.
- `montage.select_moments_automatically` — camada de compatibilidade que
  não decide mais nada.

## Limitações reconhecidas

- Sem leitura de HUD, kill feed ou placar: os sinais visuais são apenas
  cortes de cena.
- Sem detecção automática de facecam.
- Sem cache entre execuções — reanalisar refaz a transcrição.
- Capacidade limitada pelo processamento local (Whisper na CPU).
- **A qualidade editorial não foi medida contra VODs reais.** O benchmark
  (`run_benchmark.py`) existe e está vazio.

## Testes

459 testes, `unittest` da biblioteca padrão, ~14 segundos. Não dependem de
IA nem de internet; os que precisam de FFmpeg são pulados se ele faltar.
