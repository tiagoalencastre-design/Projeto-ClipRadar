"""
Ponto de entrada do pipeline de análise: VOD -> analysis_<nome>_<timestamp>.json
com momentos ranqueados.

Cada vídeo analisado gera seu PRÓPRIO arquivo (com o nome do vídeo + data/hora),
em vez de sobrescrever sempre o mesmo analysis.json — assim dá pra analisar
vários VODs diferentes e ainda ter acesso ao resultado de todos depois, tanto
pelo terminal quanto pela tela de revisão.

Uso:
    python core/pipeline.py --input data/vods/meu_vod.mp4
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import yaml
from tqdm import tqdm
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.detection import collect_raw_signals
from core import transcript_cache
from core.transcription import transcribe
from core.discovery import discover_and_select
from core.v2_adapter import candidates_to_moments
from core.timeutils import format_timestamp
from core.app_config import get_app_config

# Carrega variáveis do arquivo .env (se existir) — é aqui que a chave da
# OpenAI deve morar agora, NUNCA em config/settings.yaml (que pode ir pro Git).
load_dotenv()


class PipelineError(Exception):
    """Erro amigável — a mensagem já vem pronta pra mostrar pro usuário final."""
    pass


def load_config(config_path: str = "config/settings.yaml") -> dict:
    config_file = Path(config_path)
    if not config_file.exists():
        raise PipelineError(f"Arquivo de configuração não encontrado: {config_path}")
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise PipelineError(
            f"O arquivo {config_path} tem um erro de formatação (YAML inválido). "
            f"Confira se não ficou nenhuma linha duplicada ou desalinhada.\nDetalhe: {e}"
        )
    if not config:
        raise PipelineError(f"O arquivo {config_path} está vazio ou não pôde ser lido.")

    # SEGURANÇA: a chave de API NUNCA vem do arquivo settings.yaml (que pode
    # acabar indo pro Git sem querer) — só aceita via variável de ambiente
    # OPENAI_API_KEY, lida do arquivo .env local (que fica fora do Git).
    # Se a variável não existir, a geração de título por IA (e o Edit Plan
    # do P1) ficam desligados automaticamente, sem quebrar o pipeline.
    env_key = os.environ.get("OPENAI_API_KEY", "").strip()

    # NOVO (Fase 1): além de precisar da chave, o modo atual do app também
    # pode bloquear IA de propósito — no modo "mock", nenhuma chamada paga
    # acontece mesmo que a chave exista no .env (garantia de teste seguro).
    app_config = get_app_config()

    for section_name in ("ai_title", "edit_plan"):
        if section_name in config:
            config[section_name]["api_key"] = env_key
            if not env_key or not app_config.flags.ai_processing_enabled:
                config[section_name]["enabled"] = False

    return config


def default_output_path(video_path: str, output_dir: str = "data/cache") -> str:
    """Gera um nome de arquivo único por vídeo + horário de análise, pra não
    sobrescrever análises anteriores de outros vídeos."""
    video_stem = Path(video_path).stem
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return str(Path(output_dir) / f"analysis_{video_stem}_{timestamp}.json")


def run_pipeline(video_path: str, config: dict, output_path: str, on_step: callable = None) -> list:
    """
    on_step: callback opcional, chamado com uma string curta ANTES de cada
    etapa real começar (ex: "detecting", "transcribing", "scoring") — usado
    pra reportar progresso de verdade pra quem chama isto (ex: api_server.py),
    sem fingir etapas que não existem. Se None, ignora silenciosamente.
    """
    if not Path(video_path).exists():
        raise PipelineError(f"Arquivo de vídeo não encontrado: {video_path}")

    def _report(step_key: str) -> None:
        if on_step:
            try:
                on_step(step_key)
            except Exception:
                pass  # progresso é só informativo — nunca deve derrubar o pipeline

    steps = ["Detectando cortes de cena e picos de áudio", "Transcrevendo áudio", "Calculando Content Score"]
    with tqdm(total=len(steps), desc="Pipeline") as pbar:
        pbar.set_description(steps[0])
        _report("detecting")
        try:
            signals = collect_raw_signals(video_path, config)
        except Exception as e:
            raise PipelineError(f"Falha ao detectar cenas/áudio em {video_path}. O vídeo pode estar corrompido ou num formato não suportado.\nDetalhe técnico: {e}")
        pbar.update(1)

        pbar.set_description(steps[1])
        _report("transcribing")

        # CACHE DE TRANSCRIÇÃO.
        #
        # A transcrição é a etapa mais cara do pipeline (Whisper na CPU) e a
        # mais determinística: o mesmo vídeo, com o mesmo modelo e idioma,
        # sempre produz o mesmo texto. Reaproveitar economiza minutos a cada
        # reanálise — e reanalisar acontece o tempo todo: ao comparar pesos
        # do scoring, ao rodar o benchmark, ou quando o usuário gera
        # "montagem" depois de "clipes separados" do mesmo VOD.
        #
        # O cache fica ao lado do analysis.json, na pasta do usuário.
        model_size = config["whisper"]["model_size"]
        language = config["whisper"]["language"]
        cached_at = transcript_cache.cache_path(
            Path(output_path).parent, video_path, model_size, language
        )
        transcript = transcript_cache.load(cached_at)

        if transcript is None:
            try:
                transcript = transcribe(
                    video_path, model_size=model_size, language=language,
                )
            except Exception as e:
                raise PipelineError(f"Falha ao transcrever o áudio de {video_path}.\nDetalhe técnico: {e}")
            transcript_cache.save(cached_at, transcript)
        pbar.update(1)

        pbar.set_description(steps[2])
        _report("scoring")
        # MOTOR V2: esta é a ÚNICA autoridade de seleção do pipeline.
        # sinais -> eventos -> histórias -> vários candidatos por história
        #        -> avaliação editorial heurística -> dedup -> diversidade
        # Não há IA envolvida: o analisador é o HeuristicEditorialAnalyzer.
        selected, report = discover_and_select(signals, transcript, config)
        all_candidates = getattr(report, "all_candidates", []) or []
        pbar.update(1)

    moments = candidates_to_moments(selected, transcript)

    result = {
        "video_path": video_path,
        "analyzed_at": datetime.now().isoformat(),
        "engine": "v2",
        "total_candidates": report.raw_candidates,
        # "moments" traz os clipes JÁ SELECIONADOS pela V2. O montage.py
        # renderiza esta lista sem refazer seleção editorial.
        "moments": moments,
        # Relatório de execução e candidatos descartados, pra diagnosticar
        # "por que só saíram 3 clipes?" sem adivinhação.
        "discovery_report": report.as_dict(),
        "all_candidates": [c.as_dict() for c in all_candidates],
    }

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return moments


def main():
    parser = argparse.ArgumentParser(description="Pipeline de análise de VOD")
    parser.add_argument("--input", required=True, help="Caminho do arquivo de vídeo (mp4)")
    parser.add_argument("--config", default="config/settings.yaml", help="Caminho do arquivo de config")
    parser.add_argument("--output", default=None, help="Onde salvar o resultado (padrão: gera nome automático por vídeo)")
    args = parser.parse_args()

    output_path = args.output or default_output_path(args.input)

    try:
        config = load_config(args.config)
        moments = run_pipeline(args.input, config, output_path)
    except PipelineError as e:
        print(f"\nErro: {e}")
        sys.exit(1)

    print(f"\n{len(moments)} momentos candidatos encontrados. Top 5:\n")
    for m in moments[:5]:
        print(f"  [{m.score:5.1f}] {m.clip_id}  {format_timestamp(m.start_seconds):>8} -> {format_timestamp(m.end_seconds):>8}  "
              f"(contexto desde {format_timestamp(m.context_start_seconds):>8})  fontes: {m.signal_sources}")
    print(f"\nResultado completo salvo em: {output_path}")
    print("Rode `python -m uvicorn core.api_server:app --reload` e abra http://localhost:8000")


if __name__ == "__main__":
    main()
