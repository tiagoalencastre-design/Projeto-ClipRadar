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

- `core/database.py` — esquema, conexão e configuração de produção:
  `journal_mode=WAL` (leitura não bloqueia escrita), `foreign_keys=ON` (o
  SQLite as ignora por padrão), `busy_timeout=5000` e `synchronous=NORMAL`.
  Doze índices, cada um cobrindo uma consulta que o código realmente faz.
- `core/repositories.py` — acesso por entidade, tolerante a falha
- `core/persistence.py` — liga o fluxo real ao banco
- `core/job_store.py` — dicionário que espelha jobs no banco automaticamente

Jobs sobrevivem a restart; os que estavam rodando quando o processo caiu
ficam marcados como `interrupted`.

## Segurança — IMPLEMENTADO

- **Escape de HTML no front** (`esc()` em `app.js`): transcrição, nome de
  arquivo e URLs passam por escape antes de entrar em `innerHTML`.
- **Lista de URLs permitidas** (`core/url_policy.py`): só domínios do
  YouTube. Bloqueia `file://`, rede interna e domínios parecidos.
- **Limite de tentativas por IP** (`core/rate_limit.py`): login, cadastro e
  reenvio de confirmação. Estado em memória — some no restart, o que é
  suficiente para um processo só.
- **Token de confirmação expira em 24h.**
- **Cookie de sessão** com `HttpOnly`, `SameSite=Lax` e `Secure` quando a
  URL base é https.

## Fila de jobs — IMPLEMENTADO

`core/queue.py` define `JobQueue` (interface) e `ThreadQueue` (implementação
atual: uma thread por job, com limite de simultâneos). `get_queue()` devolve
a instância compartilhada.

Todo trabalho de fundo — geração, análise e download do YouTube — passa por
`queue.submit()`. O servidor não cria threads nem conta vagas por conta
própria; até a integração da V2 havia dois mecanismos concorrentes, o que
era dívida técnica.

O plano Studio recebe uma vaga ALÉM do limite normal (`priority=True`), para
que um assinante não fique preso atrás de usuários do plano grátis. Trocar
por Redis ou Celery é implementar `JobQueue` — nenhuma rota muda.

## Entrega de arquivos — IMPLEMENTADO

`core/files.py`. Clipes e vídeos são servidos por rotas autenticadas
(`/files/clips/{path}`, `/files/vods/{path}`), não por `StaticFiles`. Cada
download exige sessão válida e confirma que o arquivo está dentro da pasta
do próprio usuário; caminho com `..` é recusado.

Suporte a Range implementado à mão — o `FileResponse` do Starlette usado
aqui não trata o cabeçalho, e sem ele o navegador não consegue arrastar a
barra do vídeo.

Apenas `/assets` continua público: CSS, JS e logo precisam carregar antes
do login.

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

O consumo é **reservado no início** do processamento (`persistence.reserve_usage`),
não no fim. Reservar na entrada fecha duas brechas: requisições simultâneas
que leriam a mesma cota livre, e processamento interrompido que não seria
cobrado. Um índice único em `usage_events(job_id)` torna a reserva
idempotente — retry e clique duplo não cobram duas vezes. Job que termina em
erro é estornado (`refund_usage`).

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
