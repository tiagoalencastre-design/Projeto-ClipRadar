# ClipRadar — arquitetura real

Documento escrito a partir do código, não de planos. Tudo marcado como
**IMPLEMENTADO** foi verificado no fonte e nos testes. O que está em
**PLANEJADO** ainda não existe e não deve ser tratado como se existisse.

---

## Visão geral

VOD longo de gameplay entra; clipes verticais saem. FFmpeg, Whisper e
PySceneDetect rodam na máquina do usuário. Nenhuma decisão editorial passa
por IA.

## Fluxo — IMPLEMENTADO

```
vídeo
  ↓ core/detection.py       picos de áudio (librosa) + cortes de cena (PySceneDetect)
  ↓ core/transcription.py   faster-whisper, timestamps por palavra
  ↓ core/events.py          sinais agrupados em eventos com categoria e confiança
  ↓ core/story.py           eventos relacionados viram história; independentes separam
  ↓ core/candidates.py      cada história gera vários candidatos (6 tipos)
  ↓ core/boundaries.py      hook / payoff / exit derivados da transcrição
  ↓ core/editorial.py       scoring heurístico em 8 componentes
  ↓ core/dedup.py           deduplicação por conteúdo + diversidade
  ↓ core/discovery.py       seleção final (única autoridade)
  ↓ core/edit_plan.py       plano editorial — só roda com chave de IA configurada
  ↓ core/montage.py         renderização FFmpeg
clipes + analysis.json
```

`core/pipeline.py :: run_pipeline()` orquestra e grava o `analysis.json`.

## Camada de renderização — IMPLEMENTADO

- `core/render/filters.py` — filtros de vídeo como funções puras: zoom
  punch-in, empilhamento de facecam, fundo borrado, marca d'água.
- `core/render/ffmpeg.py` — executa o binário, sonda duração e fps, e define
  `VIDEO_OUTPUT_ARGS` (parâmetros de saída padronizados).
- `core/montage.py` — corta, aplica filtros, concatena e exporta. Reexporta
  os nomes acima para não quebrar quem importa de `core.montage`.

Layouts verticais disponíveis: `gameplay_full`, `gameplay_facecam`,
`facecam_focus`, `blur_background`.

## Scoring — IMPLEMENTADO

`core/editorial.py` calcula oito componentes: standalone, context, hook,
payoff, ending, emotion, narrative_completeness, short_form_fit, mais
originality. Pesos em `settings.yaml`, seção `editorial`.

O peso mais alto é `standalone` — "quem assistir só este clipe entende o que
aconteceu?". Inclui detecção heurística de referência órfã (clipe que começa
com "ele fez isso" perde pontos).

`core/scoring_signals.py` declara 16 sinais. Os sem base real
(`share_potential`, `vertical_suitability`, `viral_potential`) ficam com peso
zero de propósito.

## Banco e persistência — IMPLEMENTADO

SQLite com nove tabelas: `users`, `sessions`, `projects`, `videos`, `jobs`,
`clips`, `usage_events`, `clip_feedback`, `plan_migration_marker`.

- `core/database.py` — esquema e conexão
- `core/repositories.py` — acesso por entidade, tolerante a falha
- `core/persistence.py` — liga o fluxo real ao banco
- `core/job_store.py` — dicionário que espelha jobs no banco automaticamente

Jobs sobrevivem a restart; os que estavam rodando quando o processo caiu
ficam marcados como `interrupted`.

## API — IMPLEMENTADO

FastAPI com 26 rotas. Autenticação por e-mail e senha (PBKDF2), sessão por
cookie, confirmação por e-mail via Resend.

Grupos: `/api/auth/*` (router próprio), `/api/videos/*`, `/api/generate`,
`/api/analyze`, `/api/render-clip`, `/api/clips`, `/api/clips/feedback`,
`/api/plans`, `/api/usage`, `/api/brand-kit`, `/api/history`,
`/api/system/config`, e as três páginas.

## Planos — IMPLEMENTADO (sem cobrança)

`core/plans.py` define grátis, pro e studio, com limite mensal de minutos,
retenção de clipes, marca d'água, fila prioritária e Brand Kit. Preços por
região (BRL, USD, GBP, EUR).

**Não há integração de pagamento.** Nenhum gateway, nenhuma cobrança.

## Camada de IA — IMPLEMENTADA, DESLIGADA

`core/ai_providers/` define `TextProvider` (interface), `OpenAITextProvider`
(única implementação) e um registry que escolhe por tarefa.

Usada apenas por `core/ai_title.py` e `core/edit_plan.py`, ambos opcionais:
sem chave configurada devolvem `None` e o pipeline segue pelo caminho
gratuito.

`core/editorial.py` define `EditorialAnalyzer`, com
`HeuristicEditorialAnalyzer` como implementação atual.

**Nenhuma chamada de IA participa da descoberta ou seleção de clipes.**

## MCP — ESTRUTURA APENAS

`core/mcp/` contém um catálogo de sete ferramentas que o ClipRadar *poderia*
expor. Nada é executado, nada é servido. `mcp_enabled` é `False` em todos os
modos.

## Testes — IMPLEMENTADO

465 testes em 24 arquivos, `unittest` da biblioteca padrão, ~12 segundos.
Não dependem de IA nem de internet. Os que precisam de FFmpeg são pulados
quando ele não está disponível.

Cobertura notável: motor de clipping, integração do pipeline, estrutura do
HTML, compatibilidade de codificação de vídeo, planos e limites, feedback.

## Benchmark — IMPLEMENTADO, SEM DADOS

`core/benchmark.py` e `run_benchmark.py` medem recall e precisão contra
momentos marcados à mão. A ferramenta funciona, mas **nenhum gabarito foi
criado ainda** — a qualidade editorial do sistema não foi medida.

---

## Limitações reconhecidas

- Sinais visuais são apenas cortes de cena: não há leitura de HUD, kill feed
  ou placar.
- Não há detecção automática de facecam.
- Sem cache entre execuções — reanalisar refaz a transcrição.
- Capacidade limitada pelo processamento local (Whisper na CPU).
- `core/legacy/scoring.py` é o motor antigo, mantido só como referência.

## PLANEJADO — não existe hoje

- Integração com OmniRoute ou qualquer LLM
- MCP funcional
- Cobrança e créditos
- Detectores por jogo (Valorant, Warzone)
- Armazenamento em nuvem
- Fila distribuída (Redis/Celery)
