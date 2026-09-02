"""
Painel principal — layout em 2 colunas (prévia/resultado à esquerda, texto e
ação à direita), inspirado na estrutura de landing pages de produtos como o
Eklipse, mas com paleta e identidade próprias (verde neon).

Rodar: streamlit run app/dashboard.py
"""
import base64
import json
import sys
import traceback
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.pipeline import load_config, run_pipeline, default_output_path, PipelineError
from core.montage import (
    run_montage, MontageError, SUBTITLE_STYLES, DEFAULT_SUBTITLE_STYLE,
    PLATFORM_DURATION_PRESETS, DEFAULT_PLATFORM,
)
from core.thumbnail import extract_thumbnail, derive_thumbnail_text

st.set_page_config(page_title="GringoBrasileiro — Clip Studio", page_icon="🎮", layout="wide")

st.markdown("""
<style>
    .main .block-container { padding-top: 1.5rem; max-width: 1250px; }

    .top-bar {
        display: flex; align-items: center; justify-content: space-between;
        padding: 0.9rem 1.5rem; border-radius: 14px;
        background: #0d0f0d; border: 1px solid rgba(57,255,20,0.3);
        margin-bottom: 1.5rem;
    }
    .top-bar .brand { display: flex; align-items: center; gap: 0.6rem; }
    .top-bar .brand-name { color: #39FF14; font-weight: 800; font-size: 1.15rem; letter-spacing: 0.5px; }
    .top-bar .status-pill {
        background: rgba(57,255,20,0.12); color: #39FF14; border: 1px solid rgba(57,255,20,0.4);
        padding: 0.3rem 0.8rem; border-radius: 999px; font-size: 0.8rem; font-weight: 600;
    }

    .headline { font-size: 2.4rem; font-weight: 800; line-height: 1.15; color: white; margin-bottom: 0.9rem; }
    .headline .hl-green { color: #39FF14; text-shadow: 0 0 14px rgba(57,255,20,0.5); }
    .headline .hl-gold { color: #FFD23F; text-shadow: 0 0 14px rgba(255,210,63,0.4); }
    .subtext { color: rgba(255,255,255,0.75); font-size: 1.02rem; margin-bottom: 1.4rem; }

    .connect-card {
        padding: 1.4rem 1.5rem; border-radius: 14px;
        background: #101210; border: 1px solid rgba(57,255,20,0.28);
    }
    .connect-card .label {
        color: #39FF14; font-weight: 700; font-size: 0.8rem;
        text-transform: uppercase; letter-spacing: 0.6px; margin-bottom: 0.6rem;
    }
    .fine-print { color: rgba(255,255,255,0.45); font-size: 0.78rem; margin-top: 0.6rem; }

    .preview-panel {
        border-radius: 16px; border: 1px solid rgba(57,255,20,0.25);
        background: radial-gradient(circle at 30% 20%, rgba(57,255,20,0.10) 0%, rgba(10,10,10,0) 65%), #0b0d0b;
        padding: 2.2rem 1.5rem; text-align: center; min-height: 220px;
        display: flex; flex-direction: column; align-items: center; justify-content: center;
        margin-bottom: 1rem;
    }
    .preview-panel .icon { font-size: 2.4rem; margin-bottom: 0.6rem; }
    .preview-panel .msg { color: rgba(255,255,255,0.55); font-size: 0.95rem; }

    .clips-ready-card {
        border-radius: 14px; border: 1px solid rgba(57,255,20,0.25);
        background: #101210; padding: 1rem 1.2rem;
    }
    .clips-ready-header {
        display: flex; align-items: center; gap: 0.5rem;
        color: white; font-weight: 700; font-size: 0.95rem; margin-bottom: 0.9rem;
    }
    .clips-ready-header .count { color: #39FF14; font-weight: 800; font-size: 1.1rem; }

    .moment-grid { display: flex; gap: 12px; flex-wrap: wrap; }
    .moment-card {
        position: relative; width: 140px; border-radius: 10px; overflow: hidden;
        border: 1px solid rgba(57,255,20,0.3); background: #0d0f0d;
    }
    .moment-card img { width: 100%; display: block; aspect-ratio: 9/16; object-fit: cover; }
    .moment-score {
        position: absolute; top: 6px; left: 6px;
        background: #39FF14; color: #0a0a0a; font-weight: 800; font-size: 0.78rem;
        padding: 1px 7px; border-radius: 6px;
    }
    .moment-label { padding: 5px 6px; font-size: 0.7rem; color: white; background: rgba(0,0,0,0.55); }
    .moment-tag {
        display: inline-block; margin: 4px 0 5px 6px;
        background: rgba(57,255,20,0.15); color: #39FF14; border: 1px solid rgba(57,255,20,0.35);
        font-size: 0.62rem; font-weight: 700; padding: 1px 6px; border-radius: 5px;
    }

    div[data-testid="stButton"] button[kind="primary"] {
        border-radius: 10px; height: 3.2rem; font-size: 1.05rem; font-weight: 700;
        background: #39FF14; color: #0a0a0a; border: none;
        box-shadow: 0 0 18px rgba(57,255,20,0.45); width: 100%;
    }
    div[data-testid="stButton"] button[kind="primary"]:hover {
        box-shadow: 0 0 26px rgba(57,255,20,0.7); transform: translateY(-1px);
    }

    section[data-testid="stSidebar"] { background-color: rgba(57,255,20,0.03); border-right: 1px solid rgba(57,255,20,0.15); }
    div[data-testid="stExpander"] { border-radius: 12px; border: 1px solid rgba(57,255,20,0.2); }
    div[data-testid="stProgress"] > div > div > div { background-color: #39FF14; }
</style>
""", unsafe_allow_html=True)


def _image_to_data_uri(path: str) -> str:
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return f"data:image/jpeg;base64,{data}"


def render_moment_cards(cards: list[dict]) -> None:
    html = ['<div class="moment-grid">']
    for c in cards:
        html.append(
            f'<div class="moment-card">'
            f'<img src="{c["image"]}"/>'
            f'<div class="moment-score">{c["score"]:.0f}</div>'
            f'<div class="moment-label">{c["label"]}</div>'
            f'</div>'
        )
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def build_preview_cards(analysis_path: str, preview_dir: Path, top_n: int = 3) -> list[dict]:
    data = json.loads(Path(analysis_path).read_text(encoding="utf-8"))
    video_path = data["video_path"]
    top_moments = sorted(data["moments"], key=lambda m: m["score"], reverse=True)[:top_n]

    preview_dir.mkdir(parents=True, exist_ok=True)
    cards = []
    for m in top_moments:
        thumb_path = preview_dir / f"preview_{m['clip_id']}.jpg"
        label = derive_thumbnail_text(m.get("transcript_excerpt", ""), max_words=3) or "MOMENTO"
        extract_thumbnail(video_path, m["start_seconds"], str(thumb_path), text=None)
        cards.append({"image": _image_to_data_uri(str(thumb_path)), "score": m["score"], "label": label})
    return cards


vods_dir = Path("data/vods")
vods_dir.mkdir(parents=True, exist_ok=True)
available_videos = sorted([p for p in vods_dir.glob("*.mp4")])

st.markdown(
    f"""
    <div class="top-bar">
        <div class="brand">🎮 <span class="brand-name">GRINGOBRASILEIRO</span></div>
        <div class="status-pill">{len(available_videos)} vídeo(s) na fila</div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("⚙️ Opções")
    orientation = st.radio("Formato", ["vertical", "horizontal"], horizontal=True)

    platform_labels = {
        "sem_preferencia": "Sem preferência",
        "tiktok": "TikTok (~34s)",
        "reels": "Instagram Reels (~90s)",
        "shorts": "YouTube Shorts (~60s)",
    }
    platform = st.selectbox(
        "Rede social de destino",
        list(PLATFORM_DURATION_PRESETS.keys()),
        index=list(PLATFORM_DURATION_PRESETS.keys()).index(DEFAULT_PLATFORM),
        format_func=lambda k: platform_labels.get(k, k),
    )

    st.divider()
    burn_captions = st.checkbox("Legendas queimadas", value=True)

    subtitle_style_labels = {
        "classic": "Clássico",
        "bold_yellow": "Negrito amarelo",
        "minimal_top": "Minimalista (topo)",
        "boxed": "Caixa preta",
    }
    subtitle_style = st.selectbox(
        "Estilo da legenda",
        list(SUBTITLE_STYLES.keys()),
        index=list(SUBTITLE_STYLES.keys()).index(DEFAULT_SUBTITLE_STYLE),
        format_func=lambda k: subtitle_style_labels.get(k, k),
        disabled=not burn_captions,
    )

    st.divider()
    st.caption(
        "🤖 O app já aplica sozinho, quando fizer sentido: zoom sutil, corte de "
        "silêncio interno, e enquadramento seguindo rosto/webcam quando detectado."
    )

if not available_videos:
    st.warning(
        f"Nenhum vídeo .mp4 encontrado em `{vods_dir}/`. "
        "Coloque um arquivo de vídeo lá e recarregue esta página (F5)."
    )
    st.stop()

col_left, col_right = st.columns([1.1, 1])

with col_left:
    preview_placeholder = st.empty()
    with preview_placeholder.container():
        st.markdown(
            """
            <div class="preview-panel">
                <div class="icon">🎬</div>
                <div class="msg">Seu clip final vai aparecer aqui depois de gerar</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    clips_ready_placeholder = st.empty()
    with clips_ready_placeholder.container():
        st.markdown(
            """
            <div class="clips-ready-card">
                <div class="clips-ready-header"><span class="count">0</span> clips prontos</div>
                <div style="color: rgba(255,255,255,0.45); font-size: 0.85rem;">
                    Escolha um vídeo e clique em gerar pra ver os melhores momentos aqui.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

with col_right:
    st.markdown(
        '<div class="headline">De um VOD de horas pra um '
        '<span class="hl-gold">clip pronto</span> pra postar, '
        '<span class="hl-green">em minutos</span>.</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="subtext">O app analisa seu vídeo, encontra os melhores momentos com IA, '
        'e já entrega cortado, legendado e formatado pra TikTok, Reels e Shorts.</div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="connect-card"><div class="label">📼 Vídeo de origem</div>', unsafe_allow_html=True)
    mode = st.radio(
        "O que processar?",
        ["Um vídeo específico", f"Todos os vídeos ({len(available_videos)})"],
        label_visibility="collapsed",
    )
    video_choice = None
    if mode == "Um vídeo específico":
        video_choice = st.selectbox("Vídeo", available_videos, format_func=lambda p: p.name, label_visibility="collapsed")
    else:
        st.caption(f"Serão processados todos os {len(available_videos)} vídeos da pasta.")

    button_label = "🚀 Analisar e Gerar Clip" if mode == "Um vídeo específico" else f"🚀 Processar {len(available_videos)} vídeos"
    generate_clicked = st.button(button_label, type="primary", use_container_width=True)
    st.markdown('<div class="fine-print">Processamento local, sem custo por vídeo.</div>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


def _process_one(video_path: Path, config: dict):
    analysis_output_path = default_output_path(str(video_path))
    moments = run_pipeline(str(video_path), config, analysis_output_path)
    final_video_path, thumbnail_path = run_montage(
        analysis_path=analysis_output_path,
        auto=True,
        platform=platform,
        orientation=orientation,
        burn_captions=burn_captions,
        subtitle_style=subtitle_style,
        dynamic_zoom=True,
        trim_dead_air=True,
        auto_face_crop=True,
        ai_title_config=config.get("ai_title", {}),
    )
    return len(moments), final_video_path, thumbnail_path, analysis_output_path


if generate_clicked:
    if mode == "Um vídeo específico":
        try:
            with st.spinner("Detectando momentos e transcrevendo áudio... isso pode levar vários minutos"):
                config = load_config()
                total_moments, final_video_path, thumbnail_path, analysis_output_path = _process_one(video_choice, config)

            preview_dir = Path("data/clips") / "_previews"
            cards = []
            try:
                cards = build_preview_cards(analysis_output_path, preview_dir, top_n=min(3, total_moments))
            except Exception:
                pass

            with clips_ready_placeholder.container():
                cards_html = "".join(
                    f'<div class="moment-card">'
                    f'<img src="{c["image"]}"/>'
                    f'<div class="moment-score">{c["score"]:.0f}</div>'
                    f'<div class="moment-label">{c["label"]}</div>'
                    f'</div>'
                    for c in cards
                )
                st.markdown(
                    f"""
                    <div class="clips-ready-card">
                        <div class="clips-ready-header"><span class="count">{len(cards)}</span> clips prontos</div>
                        <div class="moment-grid">{cards_html}</div>
                        <div class="moment-tag">✓ {total_moments} momentos analisados</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            with preview_placeholder.container():
                if final_video_path is None:
                    st.warning(
                        "Nenhum momento com qualidade suficiente foi encontrado nesse vídeo. "
                        "Revise os momentos individualmente na tela de Revisão pra entender por quê."
                    )
                else:
                    st.video(final_video_path)
                    if thumbnail_path:
                        st.image(thumbnail_path, caption="Thumbnail gerado", width=220)
                    st.caption(f"Análise salva em: `{analysis_output_path}`")

        except (PipelineError, MontageError) as e:
            st.error(str(e))
        except Exception:
            st.error("Algo deu errado de um jeito inesperado. Detalhe técnico:")
            st.code(traceback.format_exc())

    else:
        config = load_config()
        progress_bar = st.progress(0.0)
        status_text = st.empty()
        results = {"sucesso": [], "sem_momentos": [], "erro": []}

        for i, video_path in enumerate(available_videos, start=1):
            status_text.text(f"[{i}/{len(available_videos)}] Processando: {video_path.name}")
            try:
                _, final_video_path, _, _ = _process_one(video_path, config)
                if final_video_path is None:
                    results["sem_momentos"].append(video_path.name)
                else:
                    results["sucesso"].append(video_path.name)
            except (PipelineError, MontageError) as e:
                results["erro"].append((video_path.name, str(e)))
            except Exception as e:
                results["erro"].append((video_path.name, str(e)))
            progress_bar.progress(i / len(available_videos))

        status_text.empty()
        st.success(
            f"Concluído: {len(results['sucesso'])} vídeos processados com sucesso, "
            f"{len(results['sem_momentos'])} sem momentos bons o suficiente, "
            f"{len(results['erro'])} com erro."
        )
        if results["erro"]:
            st.error("Vídeos com erro:")
            for name, reason in results["erro"]:
                st.write(f"**{name}**: {reason}")
        st.caption("Vá na tela de Revisão pra ver e avaliar cada montagem gerada.")