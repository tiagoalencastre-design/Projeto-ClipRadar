# ClipRadar — Diagnóstico de Arquitetura e Plano de Evolução

*Nenhum código foi alterado na produção deste documento. Análise feita lendo o projeto atual por completo.*

---

## A. Arquitetura atual

**Front-end**
- 3 páginas HTML estáticas (`landing.html`, `login.html`, `index.html`), servidas pelo FastAPI como texto puro (`HTMLResponse`)
- Sem framework, sem build step — HTML/CSS/JS de mão, num arquivo cada
- `index.html` sozinho tem ~1580 linhas (4 telas: dashboard, processamento, resultados, revisão manual)
- Tradução (pt/en/es) via dicionário JS embutido em cada página

**Back-end**
- Um único arquivo, `core/api_server.py` (586 linhas), concentra: rotas HTTP, autenticação, orquestração de processamento, acesso a arquivo — tudo junto, sem camadas separadas
- 18 rotas no total (auth, vídeos, geração, análise, render de clip)

**Banco de dados**
- SQLite, 1 arquivo (`data/cliparadar.db`)
- **Só 2 tabelas existem: `users` e `sessions`**. Não há tabela de vídeos, projetos, clipes, jobs, uso ou custo — esse "estado" hoje vive só em memória RAM (jobs) e em pastas no disco (arquivos), sem registro consultável

**Autenticação**
- Feita à mão: hash de senha com PBKDF2 (biblioteca padrão do Python, sem bcrypt/passlib), sessão por cookie + token opaco no banco
- Confirmação de e-mail via Resend já funciona
- Falta: recuperação de senha, limite de tentativas de login, revogar sessões em massa

**Armazenamento**
- Sistema de arquivos local, isolado por usuário via uma pasta com nome aleatório (`storage_key`)
- Sem armazenamento em nuvem (S3 ou parecido), sem CDN

**Pipeline de vídeo** (`core/pipeline.py` orquestra)
1. Detecção de corte de cena (PySceneDetect) + picos de áudio (librosa)
2. Transcrição (faster-whisper, local, CPU)
3. Scoring heurístico **próprio, sem IA** (`core/scoring.py`) — 7 sinais hoje: intensidade de gameplay, reação emocional, contexto narrativo, potencial de retenção, originalidade, reação de chat, potencial de comentário
4. Montagem/renderização via FFmpeg (`core/montage.py`, 1015 linhas — o maior arquivo do projeto): corte, reenquadramento (com detecção de rosto e empilhamento gameplay+facecam), legenda queimada, zoom "punch-in", 3 presets (Clean/Impact/Streamer), 3 layouts

**Uso de IA hoje**
- Só 2 pontos, os dois **opcionais e com fallback gracioso** se não configurados: título do thumbnail (`ai_title.py`) e "Edit Plan" editorial (`edit_plan.py`)
- Os dois chamam a OpenAI **diretamente**, sem nenhuma camada de abstração — hoje é 100% acoplado a um único fornecedor

**Processamento assíncrono**
- `threading.Thread` por requisição + um contador em memória limitando a 2 processamentos simultâneos
- **Não é fila de verdade** — nada sobrevive a reiniciar o servidor, não escala além de 1 processo

**Configuração**
- `config/settings.yaml`: parâmetros de ajuste do pipeline (bom, já existe)
- `.env`: só segredos (chaves de API)
- **Não existe** modo dev/mock/produção, nem feature flags

**MCP**
- Não existe nenhum código relacionado ainda

**Observabilidade**
- Só `print()` soltos em blocos de erro — sem log estruturado, sem tempo/custo por etapa

**Código morto**
- `app/dashboard.py` e `app/review.py` — interface antiga em Streamlit, totalmente substituída pelo front-end atual, mas ainda no repositório (e `streamlit` ainda no `requirements.txt`)

---

## B. Problemas encontrados

1. **Zero separação de camadas** — regra de negócio, acesso a dado e rota HTTP tudo misturado em `api_server.py`
2. **Acoplamento direto a um único provedor de IA** (OpenAI) em 2 arquivos — bate de frente com o princípio de arquitetura modular pedido
3. **Nenhuma tabela de domínio** (vídeo/projeto/clipe/job/uso) — hoje "reiniciar o servidor" apaga o histórico de processamento; a entrada "Meus projetos" do menu existe visualmente mas não consulta nada de verdade
4. **Fila de processamento não existe** — é só thread + contador, sem fila real, sem retry, sem sobreviver a reinício
5. **Scoring já é próprio (boa notícia)**, mas mais simples que o pedido: 7 sinais hoje vs. os 13 descritos no documento
6. **Sem controle de custo/uso** — nenhum contador de minutos, chamadas de IA ou custo por usuário
7. **Sem observabilidade estruturada**
8. **Sem feature flags nem modo mock/produção**
9. **Autenticação incompleta**: sem recuperação de senha, sem limite de tentativas
10. **Código morto** (Streamlit) aumentando a superfície de manutenção
11. **`index.html` monolítico** (~1580 linhas, 4 telas num arquivo só) — já vimos nesta conversa mudanças pequenas quebrarem outra parte sem querer
12. **Nenhum teste automatizado** no projeto

---

## C. Arquitetura recomendada

```
cliparadar/
├── app/                       # Camada de API (FastAPI) — só rotas HTTP, finas
│   ├── main.py
│   ├── routers/
│   │   ├── auth.py
│   │   ├── videos.py
│   │   ├── projects.py
│   │   └── clips.py
│   └── dependencies.py        # guarda de autenticação, etc
│
├── domain/                    # Regra de negócio pura, sem depender de FastAPI/SQLite
│   ├── models.py              # User, Project, Video, Clip, Job (dataclasses)
│   ├── scoring/
│   │   ├── signals.py         # os sinais individuais (os 13 do documento)
│   │   └── clip_score.py      # combinação em Clip Score final
│   └── pipeline/
│       ├── steps/              # cada etapa como um "Step" independente e substituível
│       └── pipeline.py         # orquestra a sequência
│
├── ai_providers/               # Camada de abstração de IA
│   ├── base.py                 # interface: TranscriptionProvider, TextProvider...
│   ├── openai_provider.py       # implementação atual
│   └── registry.py              # decide qual provider usar, por config
│
├── infra/
│   ├── database/                # SQLAlchemy/SQLite + migrations
│   ├── storage/                  # abstração (local hoje, S3 amanhã)
│   ├── queue/                     # abstração de fila (thread hoje, Redis/Celery amanhã)
│   └── app_config.py              # config central: MODE + feature flags
│
├── mcp/                          # Preparado, isolado, DESLIGADO
│   └── server.py                  # placeholder
│
├── web/                           # Front-end (mantém como está por enquanto)
└── tests/
```

**Ideia central:** hoje o pipeline de vídeo e o scoring já são bons e já seguem o espírito certo (heurística própria, sem depender de 1 IA dizendo "isso é bom"). O que falta não é reescrever a lógica — é **colocar essa lógica em módulos isolados**, atrás de interfaces trocáveis, em vez de espalhada e amarrada a implementações específicas.

---

## D. O que deve ser mantido (funciona, não mexe agora)

- Toda a lógica do pipeline de vídeo (detecção, transcrição, scoring heurístico, montagem/render) — só muda **onde mora**, não **o que faz**
- O sistema de scoring heurístico atual, sem IA — é exatamente o "sistema próprio de score" pedido; só precisa crescer
- Landing page, login, autenticação básica — já funcionam
- O padrão de "degradar com segurança" (IA opcional desliga sozinha sem quebrar nada) — esse espírito é o certo pra manter ao abstrair os provedores

## E. O que deve ser refatorado

- `api_server.py` → dividir em routers por domínio
- `ai_title.py` e `edit_plan.py` → extrair a chamada à OpenAI por trás de uma interface, sem mudar o comportamento
- Sistema de jobs em memória → abstrair atrás de uma interface de fila (implementação continua em thread por enquanto)
- `config/settings.yaml` → separar "ajuste de pipeline" (já existe) de "modo/feature flags" (falta)

## F. O que deve ser criado

- Tabelas novas: `projects`, `videos`, `clips`, `jobs`, `usage_events`
- Camada de AI Provider abstrata
- Sinais de scoring que faltam (hook, surpresa, clareza, compartilhamento, viralização, qualidade de início/fim, duração ideal, adequação ao vertical) — a maioria dá pra fazer como heurística nova, sem custo de IA
- `AppConfig` central: `MODE` (development/mock/production) + feature flags nomeados
- Estrutura MCP isolada, desligada
- Log estruturado mínimo (job_id, etapa, duração, modelo usado, custo estimado, erro)

## G. Ordem exata de implementação

1. `AppConfig` central + feature flags (organiza o que já existe, não quebra nada)
2. Tabelas novas no banco (sem migrar dado nenhum ainda, só criar estrutura)
3. Camada de AI Provider, com a OpenAI como único provider concreto por enquanto (só troca "chamada direta" por "chamada via interface")
4. Popular as tabelas novas **em paralelo** ao que já existe (sem remover o jeito antigo ainda)
5. Expandir o scoring, um sinal de cada vez, testando contra vídeo real
6. Dividir `api_server.py` em routers
7. Abstrair a fila (interface + mesma implementação em thread de hoje)
8. Preparar (sem ativar) a estrutura MCP
9. Observabilidade estruturada
10. Só então: feature flags de produção + `CLIPRADAR_MODE`

## H. O que fica desligado até a fase de ativação

- MCP inteiro
- Qualquer provedor de IA novo além do que já está em uso
- Fila/worker real (Redis/Celery) — continua em thread local
- Cobrança/créditos reais — só a estrutura de dados, sem cobrar nada
- `CLIPRADAR_MODE=production` — continua em development/mock até você aprovar
