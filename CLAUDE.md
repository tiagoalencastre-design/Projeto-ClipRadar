# ClipRadar — guia para trabalho assistido

SaaS que transforma VODs longos de gameplay em clipes verticais para
TikTok / Reels / Shorts. Público-alvo: criadores gamers brasileiros.

## Regras invioláveis

1. **Nenhuma IA nesta fase.** Sem OmniRoute, OpenAI, Claude, Gemini ou
   qualquer LLM tomando decisão editorial. O motor é determinístico. A
   camada `core/ai_providers/` existe e está desligada.
2. **Segredos só no `.env`.** Nunca em `settings.yaml`, nunca em comentário,
   nunca commitado. Uma chave já vazou assim antes.
3. **Rodar os testes antes de entregar:** `python -m unittest discover -s tests`
   (459 testes, ~14s). Nunca alterar um teste para fazê-lo passar.

## Pipeline real

```
VOD → sinais (áudio/cena) → transcrição (Whisper)
    → events → stories → candidates → editorial → dedup → diversity
    → clipes selecionados → edit plan → FFmpeg
```

Ponto de entrada único: `core/discovery.py :: discover_and_select()`.
Chamado por `core/pipeline.py`. **`core/scoring.py` é legado** — não usar.

## Quem manda em quê

| Módulo | Responsabilidade |
|---|---|
| `events.py` | sinais viram eventos tipados |
| `story.py` | agrupa eventos relacionados, separa independentes |
| `boundaries.py` | hook / payoff / exit pela transcrição |
| `candidates.py` | uma história gera vários candidatos |
| `editorial.py` | scoring heurístico (`EditorialAnalyzer` é o ponto de IA futura) |
| `dedup.py` | deduplicação por conteúdo + diversidade |
| `discovery.py` | **única autoridade de seleção** |
| `montage.py` | renderiza. Não decide nada |
| `api_server.py` | rotas FastAPI (26) |
| `plans.py` | grátis / pro / studio, limites e preços |

## Armadilhas conhecidas

- **Vírgula em filtro FFmpeg** precisa de `\,` — bug real já corrigido.
- **Sempre `-pix_fmt yuv420p`** e fps fixo. Sem isso o vídeo não abre no
  Windows. Use `VIDEO_OUTPUT_ARGS` do `montage.py`, nunca parâmetros soltos.
- **Nunca `concat -c copy`** com pedaços heterogêneos: gera timestamps
  quebrados.
- **`web/index.html` tem 1.827 linhas** com HTML+CSS+JS+3 idiomas. Editar
  por trecho, nunca reescrever inteiro. Confira o balanço de `<div>` depois
  (`tests/test_html_structure.py` cobre isso).
- **Textos de interface em 3 idiomas** (pt/en/es). Chave nova exige as três.
- **Duração de clipe é consequência do conteúdo**, não meta.

## O que não refatorar agora

`montage.py` na parte de FFmpeg, `subtitles.py`, `face_crop.py`. Cada string
de filtro ali custou depuração real.

## Testes como rede de segurança

- `test_pipeline_integration.py` — garante que o pipeline usa a V3, não o legado
- `test_v3_fixes.py` — cobertura de VOD longo, Edit Plan no corte, modo AUTO
- `test_html_structure.py` — pega HTML quebrado que nenhum teste Python pegaria
- `test_encoding_compat.py` — parâmetros de vídeo que abrem em qualquer player

## Ambiente

Windows, Python 3.12, venv, FFmpeg no PATH. `unittest` da biblioteca padrão
(sem pytest). Servidor: `python -m uvicorn core.api_server:app --reload`.
