# ClipRadar

Transforma VODs longos de gameplay em clipes verticais 9:16 para TikTok,
Reels e Shorts. Público: criadores gamers brasileiros. Todo o processamento
roda localmente.

## Stack

Python 3.12 · FastAPI · SQLite · FFmpeg (via `subprocess`, não biblioteca)
faster-whisper (CPU) · PySceneDetect · librosa · Pillow
Front-end: HTML + CSS + JS puro, sem framework
Testes: `unittest` da biblioteca padrão — **sem pytest**

## Regras invioláveis

1. **Nenhuma IA no pipeline.** O motor é 100% determinístico. Existe uma
   camada `core/ai_providers/` pronta e DESLIGADA; não integrar OmniRoute,
   OpenAI ou qualquer LLM nesta fase.
2. **Segredos só no `.env`.** Nunca em `settings.yaml`, nunca em comentário.
   Já houve vazamento de chave neste projeto.
3. **Nunca alterar um teste para fazê-lo passar.** Se falhou, ou o código
   está errado ou o teste mede a coisa errada — investigue antes.
4. **Não inventar arquitetura.** Se não existe no código, não escreva como
   se existisse.

## Fluxo do pipeline

```
VOD → sinais (áudio + cena) → transcrição
    → events → stories → candidates → editorial → dedup → diversidade
    → clipes selecionados → edit plan → FFmpeg
```

Entrada única: `core/discovery.py :: discover_and_select()`,
chamada por `core/pipeline.py :: run_pipeline()`.

## Módulos

| Caminho | Responsabilidade |
|---|---|
| `core/detection.py` | picos de áudio e cortes de cena |
| `core/transcription.py` | faster-whisper, timestamps por palavra |
| `core/events.py` | sinais viram eventos tipados |
| `core/story.py` | agrupa eventos; separa os independentes |
| `core/candidates.py` | uma história gera vários candidatos |
| `core/boundaries.py` | hook / payoff / exit pela transcrição |
| `core/editorial.py` | scoring heurístico; `EditorialAnalyzer` é a interface |
| `core/dedup.py` | deduplicação por conteúdo e diversidade |
| `core/discovery.py` | **única autoridade de seleção** |
| `core/montage.py` | orquestra corte e render. Não decide nada |
| `core/render/filters.py` | filtros de vídeo (funções puras) |
| `core/render/ffmpeg.py` | executa FFmpeg; `VIDEO_OUTPUT_ARGS` |
| `core/api_server.py` | rotas FastAPI |
| `core/database.py` · `repositories.py` · `persistence.py` | SQLite |
| `core/plans.py` | planos, limites, preços |
| `core/legacy/` | **código morto** — não importar |
| `web/index.html` · `assets/app.css` · `assets/app.js` | front-end |
| `config/settings.yaml` | configuração do pipeline |

## Comandos

```bash
python -m unittest discover -s tests            # 465 testes
python -m uvicorn core.api_server:app --reload
python run_benchmark.py
python .claude/hooks/full_suite.py              # suíte via hook
```

## FFmpeg — não alterar sem necessidade

Cada item abaixo custou depuração real:

- Vírgula dentro de expressão de filtro precisa de `\,`
- Caminho de arquivo dentro de filtro precisa escapar `:` (`C\:/...`),
  senão o FFmpeg lê só a letra do drive no Windows
- Sempre usar `VIDEO_OUTPUT_ARGS`: `yuv420p`, fps fixo, timescale fixa
- Nunca `concat -c copy` com pedaços de parâmetros diferentes
- `scale` com altura `-2`, nunca `-1` (H.264 exige altura par)

`core/subtitles.py` e `core/face_crop.py` também são delicados.

## Outras armadilhas

- Interface em **3 idiomas** (pt/en/es): chave nova exige as três
- Depois de editar HTML, conferir balanço de `<div>`
- Duração de clipe é consequência do conteúdo, não meta
