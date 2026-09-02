"""
Interface local de revisão dos momentos candidatos gerados pelo pipeline.

Agora com histórico: como o pipeline salva 1 arquivo por vídeo analisado
(em vez de sobrescrever sempre o mesmo), esta tela deixa você escolher qual
análise revisar.

Rodar: streamlit run app/review.py
"""
import json
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.timeutils import format_timestamp

CACHE_DIR = Path("data/cache")
FEEDBACK_PATH = Path("data/feedback.json")

REJECT_REASONS = [
    "Muito longo",
    "Sem contexto",
    "Não foi engraçado",
    "Não foi interessante",
]
APPROVE_REASONS = [
    "Boa gameplay",
    "Boa reação",
    "Bom hook",
    "Boa edição",
]


def load_feedback() -> dict:
    if FEEDBACK_PATH.exists():
        return json.loads(FEEDBACK_PATH.read_text(encoding="utf-8"))
    return {}


def save_feedback(feedback: dict):
    FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    FEEDBACK_PATH.write_text(json.dumps(feedback, ensure_ascii=False, indent=2), encoding="utf-8")


st.set_page_config(page_title="Revisão de Clips", layout="wide")
st.title("Revisão de Momentos Candidatos")

analysis_files = sorted(CACHE_DIR.glob("analysis_*.json"), reverse=True)
legacy_file = CACHE_DIR / "analysis.json"
if legacy_file.exists():
    analysis_files.append(legacy_file)

if not analysis_files:
    st.warning(
        "Nenhuma análise encontrada ainda. Rode primeiro pelo painel principal "
        "(`streamlit run app/dashboard.py`) ou pelo terminal:\n\n"
        "`python core/pipeline.py --input data/vods/seu_vod.mp4`"
    )
    st.stop()

selected_file = st.selectbox(
    "Qual análise revisar?",
    analysis_files,
    format_func=lambda p: p.stem.replace("analysis_", "").replace("_", " ") if p.stem != "analysis" else "análise mais recente (legado)",
)

st.info(
    "🔒 **Antes de publicar:** os trechos abaixo mostram exatamente o que foi falado "
    "(inclui nomes, comentários pessoais, etc). Revise o texto de cada momento antes "
    "de aprovar, principalmente se outras pessoas forem usar essa análise.",
    icon="🔒",
)

analysis = json.loads(selected_file.read_text(encoding="utf-8"))
feedback = load_feedback()

st.caption(f"Vídeo: {analysis['video_path']}  •  {analysis['total_candidates']} momentos candidatos")

for moment in analysis["moments"]:
    clip_id = moment["clip_id"]
    with st.container(border=True):
        col_info, col_score = st.columns([3, 1])

        with col_info:
            st.subheader(f"{clip_id}  —  score {moment['score']}/100")
            st.write(
                f"**{format_timestamp(moment['context_start_seconds'])} → {format_timestamp(moment['end_seconds'])}** "
                f"(ação principal a partir de {format_timestamp(moment['start_seconds'])})"
            )
            if moment["transcript_excerpt"]:
                st.caption(f"Transcrição próxima: \"{moment['transcript_excerpt']}\"")
            st.caption(f"Fontes de sinal: {', '.join(moment['signal_sources'])}")

        with col_score:
            b = moment["breakdown"]
            st.metric("Gameplay intensity", f"{b['gameplay_intensity']:.0f}")
            st.metric("Emotional reaction", f"{b['emotional_reaction']:.0f}")
            st.metric("Narrative context", f"{b['narrative_context']:.0f}")
            st.metric("Retention potential", f"{b['retention_potential']:.0f}")

        existing = feedback.get(clip_id, {})

        col_rate, col_reason = st.columns([1, 2])
        with col_rate:
            rating = st.radio(
                "Avaliação",
                ["Sem avaliação", "👍 Gostei", "⭐ Excelente", "👎 Não gostei", "❌ Nunca mais"],
                index=["Sem avaliação", "👍 Gostei", "⭐ Excelente", "👎 Não gostei", "❌ Nunca mais"].index(
                    existing.get("rating", "Sem avaliação")
                ),
                key=f"rating_{clip_id}",
                horizontal=True,
            )
        with col_reason:
            reasons_pool = APPROVE_REASONS if rating in ("👍 Gostei", "⭐ Excelente") else REJECT_REASONS
            reason = st.selectbox(
                "Motivo (opcional)",
                ["—"] + reasons_pool,
                key=f"reason_{clip_id}",
            )

        if rating != "Sem avaliação":
            feedback[clip_id] = {
                "rating": rating,
                "reason": reason if reason != "—" else None,
                "score_at_time": moment["score"],
                "breakdown": moment["breakdown"],
            }
            save_feedback(feedback)

st.divider()
st.caption(
    f"Feedback salvo em `{FEEDBACK_PATH}` — {len(feedback)} de {len(analysis['moments'])} avaliados. "
    "Este arquivo é a base do aprendizado individual (Fase 3)."
)
