"""
Gera um "Edit Plan" (plano editorial estruturado) pros MELHORES momentos
candidatos — nunca pro VOD inteiro. A ideia é simular decisões que um editor
humano tomaria: onde começar (hook), qual é o auge (payoff), onde terminar,
que tipo de conteúdo é aquilo, se dá pra cortar silêncio com segurança, e
quais palavras merecem destaque na legenda.

Regra de ouro: se a chave de API não estiver configurada, ou a chamada
falhar por qualquer motivo (sem internet, resposta malformada, etc), a
função retorna None — quem chamar isto DEVE continuar funcionando com o
comportamento padrão (sem plano editorial), sem quebrar o app.
"""
from __future__ import annotations

import json

from core.ai_providers import get_provider
from core.ai_providers.registry import get_model_for_task

VALID_CLIP_TYPES = {"clutch", "reaction", "funny", "strong_quote", "gameplay", "conversation", "generic"}
VALID_SUBTITLE_STYLES = {"classic", "bold_yellow", "minimal_top", "boxed"}
MAX_ZOOM_EVENTS = 4  # limite de segurança — evita um plano com zoom em excesso
MAX_HIGHLIGHT_WORDS = 8

_SCHEMA_INSTRUCTIONS = """
Responda APENAS com um JSON válido, sem nenhum texto antes ou depois, exatamente neste formato:
{
  "clip_type": "clutch" | "reaction" | "funny" | "strong_quote" | "gameplay" | "conversation" | "generic",
  "hook_point": <segundos, número>,
  "payoff_point": <segundos, número>,
  "exit_point": <segundos, número>,
  "recommended_subtitle_style": "classic" | "bold_yellow" | "minimal_top" | "boxed",
  "zoom_events": [{"start": <segundos>, "end": <segundos>}],
  "highlight_words": ["palavra1", "palavra2"],
  "silence_cut_safe": true ou false,
  "explanation": "<explicação curta, 1-2 frases, no mesmo idioma da transcrição>"
}
Todos os timestamps são em segundos, no MESMO referencial de tempo do momento
descrito abaixo (não relativos a zero). "silence_cut_safe" deve ser false
sempre que o momento depender de ação visual silenciosa (tensão, mira,
movimento sem fala) — só marque true se pausas de fala forem realmente
irrelevantes pro entendimento do clip.
"""


def generate_edit_plan(
    moment: dict,
    api_key: str | None = None,
    model: str | None = None,
) -> dict | None:
    """
    moment: dict de um momento candidato (do analysis.json) — precisa ter
    start_seconds, end_seconds, context_start_seconds, transcript_excerpt e
    breakdown.

    Retorna o plano editorial (dict validado) ou None se indisponível/falhar.
    """
    # FASE 4: quem decide se há IA disponível é a camada de providers.
    # api_key/model continuam na assinatura só por compatibilidade.
    provider = get_provider("edit_plan")
    if provider is None:
        return None

    context_start = moment.get("context_start_seconds", moment.get("start_seconds", 0))
    end = moment.get("end_seconds", context_start + 10)
    excerpt = moment.get("transcript_excerpt", "") or "(sem fala próxima detectada)"
    breakdown = moment.get("breakdown", {}) or {}

    user_prompt = (
        f"Momento de gameplay entre {context_start:.1f}s e {end:.1f}s (duração ~{end - context_start:.1f}s).\n"
        f"Transcrição próxima: \"{excerpt}\"\n"
        f"Notas do sistema (0-100): intensidade de gameplay={breakdown.get('gameplay_intensity', 0):.0f}, "
        f"reação emocional={breakdown.get('emotional_reaction', 0):.0f}, "
        f"contexto narrativo={breakdown.get('narrative_context', 0):.0f}, "
        f"potencial de retenção={breakdown.get('retention_potential', 0):.0f}.\n\n"
        f"{_SCHEMA_INSTRUCTIONS}"
    )

    raw = provider.complete_text(
        system=(
            "Você é um editor de vídeo especialista em clips de gaming pra redes sociais. "
            "Analise o momento descrito e retorne um plano editorial estruturado, em JSON puro, "
            "sem inventar informação que não foi dada."
        ),
        user=user_prompt,
        model=model or get_model_for_task("edit_plan"),
        max_tokens=450,
        temperature=0.4,
        json_mode=True,
    )
    if not raw:
        return None

    try:
        plan = json.loads(raw)
        return _validate_plan(plan, context_start, end)
    except Exception:
        # qualquer falha (sem crédito, sem internet, JSON malformado, etc):
        # cai de volta pro comportamento sem plano editorial, silenciosamente
        return None


def _validate_plan(plan: dict, context_start: float, end: float) -> dict | None:
    """Confere que o plano tem os campos mínimos e valores dentro de faixa
    razoável. Um plano malformado é descartado (retorna None) em vez de
    arriscar usar dado inválido na renderização."""
    if not isinstance(plan, dict):
        return None

    required_keys = {"clip_type", "hook_point", "payoff_point", "exit_point", "silence_cut_safe", "explanation"}
    if not required_keys.issubset(plan.keys()):
        return None

    if plan.get("clip_type") not in VALID_CLIP_TYPES:
        plan["clip_type"] = "generic"

    if plan.get("recommended_subtitle_style") not in VALID_SUBTITLE_STYLES:
        plan["recommended_subtitle_style"] = "classic"

    for key in ("hook_point", "payoff_point", "exit_point"):
        try:
            plan[key] = max(context_start, min(float(plan[key]), end))
        except (TypeError, ValueError):
            plan[key] = context_start

    clean_events = []
    for ev in (plan.get("zoom_events") or [])[:MAX_ZOOM_EVENTS]:
        try:
            s = max(context_start, min(float(ev["start"]), end))
            e = max(s + 0.2, min(float(ev["end"]), end))
            clean_events.append({"start": s, "end": e})
        except (KeyError, TypeError, ValueError):
            continue
    plan["zoom_events"] = clean_events

    highlight_words = plan.get("highlight_words") or []
    plan["highlight_words"] = [str(w).strip() for w in highlight_words if str(w).strip()][:MAX_HIGHLIGHT_WORDS]

    plan["silence_cut_safe"] = bool(plan.get("silence_cut_safe", False))
    plan["explanation"] = str(plan.get("explanation", ""))[:300]

    return plan
