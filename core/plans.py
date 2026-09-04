"""
Planos, limites e preços por região.

ESTADO ATUAL: nada aqui cobra dinheiro. A flag payments_enabled continua
False e não existe integração com nenhum meio de pagamento. O que existe é
a ESTRUTURA: quem tem direito a quê, quanto já usou, e quando um clipe
expira. Ligar a cobrança depois não exige mexer no resto do sistema.

DECISÕES E SEUS MOTIVOS:

  Cobrança por MINUTO DE VÍDEO ENVIADO, não por clipe gerado.
      É o padrão do mercado e é o justo: o custo é processar 1 hora de
      vídeo, independente de sair 3 ou 20 clipes. Cobrar por clipe puniria
      justamente quem aproveita melhor a ferramenta.

  Retenção diferente por plano (7 dias no grátis, 30 no Pro).
      Disco é o custo que mais cresce sem ninguém perceber.

  Preço por região, não conversão do dólar.
      R$ 34,90 não é "$9,90 convertido" — é o preço que faz sentido no
      Brasil. Converter direto tornaria o produto caro demais aqui.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

FREE = "free"
PRO = "pro"
STUDIO = "studio"


@dataclass(frozen=True)
class RegionalPrice:
    currency: str
    symbol: str
    monthly: float

    @property
    def formatted(self) -> str:
        if self.currency == "BRL":
            return f"{self.symbol} {self.monthly:.2f}".replace(".", ",")
        return f"{self.symbol}{self.monthly:.2f}"


@dataclass(frozen=True)
class Plan:
    id: str
    name: str
    monthly_minutes: int
    retention_days: int
    watermark: bool
    ai_extras_included: bool      # título e thumbnail por IA
    priority_queue: bool = False  # fura a fila quando há vídeos na frente
    brand_kit: bool = False       # troca a marca do ClipRadar pela do canal
    prices: dict[str, RegionalPrice] = field(default_factory=dict)

    def price_for(self, region: str) -> RegionalPrice:
        """Preço da região, caindo pro dólar quando a região é desconhecida."""
        return self.prices.get(region.upper(), self.prices.get("US"))


# Preços definidos por poder de compra local, não por conversão.
# Ancorado em £10,99. As demais moedas NÃO são conversão direta: cada uma
# usa o valor que faz sentido no mercado local, terminando em .99 / ,90 como
# manda o costume de cada região.
#
# Comparação: OpusClip Starter $15, Pro $29. Eklipse Premium $24,99.
# Ficamos abaixo de todos, em qualquer região.
_STUDIO_PRICES = {
    "GB": RegionalPrice("GBP", "£", 24.99),
    "US": RegionalPrice("USD", "$", 29.99),
    "EU": RegionalPrice("EUR", "€", 27.99),
    "BR": RegionalPrice("BRL", "R$", 99.90),
}

_PRO_PRICES = {
    "GB": RegionalPrice("GBP", "£", 10.99),
    "US": RegionalPrice("USD", "$", 13.99),
    "EU": RegionalPrice("EUR", "€", 12.99),
    # Brasil mais baixo de propósito: poder de compra local. Converter
    # £10,99 direto daria ~R$ 75 e tornaria o produto inviável aqui.
    "BR": RegionalPrice("BRL", "R$", 49.90),
}

PLANS: dict[str, Plan] = {
    FREE: Plan(
        id=FREE,
        name="Grátis",
        monthly_minutes=90,      # acima da média do mercado (60), sem ser demais
        retention_days=7,        # OpusClip apaga em 3; 7 é diferencial real
        watermark=True,
        ai_extras_included=False,
        prices={
            region: RegionalPrice(p.currency, p.symbol, 0.0)
            for region, p in _PRO_PRICES.items()
        },
    ),
    PRO: Plan(
        id=PRO,
        name="Pro",
        monthly_minutes=400,
        retention_days=30,
        watermark=False,
        ai_extras_included=True,
        prices=_PRO_PRICES,
    ),
    STUDIO: Plan(
        id=STUDIO,
        name="Studio",
        monthly_minutes=1200,
        retention_days=90,      # deixa de ser ferramenta e vira arquivo do canal
        watermark=False,
        ai_extras_included=True,
        # Fura a fila quando há outros vídeos processando. É o diferencial
        # mais valioso pra quem posta todo dia — e o mais barato de entregar,
        # porque a fila já existe.
        priority_queue=True,
        # Marca do canal no lugar da marca do ClipRadar.
        brand_kit=True,
        prices=_STUDIO_PRICES,
    ),
}

DEFAULT_PLAN = FREE

# Mapeamento simples de país -> região de preço. Países da zona do euro
# usam "EU"; qualquer outro cai no dólar.
_EURO_COUNTRIES = {
    "PT", "ES", "FR", "DE", "IT", "IE", "NL", "BE", "AT", "FI", "GR",
}


def region_for_country(country_code: str | None) -> str:
    """Região de preço a partir do código do país (ex: 'BR', 'GB')."""
    if not country_code:
        return "US"
    code = country_code.strip().upper()
    if code == "BR":
        return "BR"
    if code in ("GB", "UK"):
        return "GB"
    if code in _EURO_COUNTRIES:
        return "EU"
    return "US"


def get_plan(plan_id: str | None) -> Plan:
    """Plano do usuário. Valor desconhecido cai no grátis — nunca libera
    recurso pago por engano."""
    return PLANS.get((plan_id or "").strip().lower(), PLANS[DEFAULT_PLAN])


def expires_at(created_at: datetime | None, plan_id: str) -> datetime:
    """Quando um clipe gerado agora deixa de ficar disponível."""
    base = created_at or datetime.now(timezone.utc)
    return base + timedelta(days=get_plan(plan_id).retention_days)


def days_until_expiry(created_at: datetime, plan_id: str) -> int:
    """Dias restantes, nunca negativo. A interface mostra isso em cada clipe —
    apagar sem avisar é o que gera raiva de verdade."""
    remaining = expires_at(created_at, plan_id) - datetime.now(timezone.utc)
    # Arredonda pra CIMA: faltando 1,9 dias, o certo é dizer "2 dias".
    # Arredondar pra baixo faria o usuário perder um dia de aviso.
    return max(math.ceil(remaining.total_seconds() / 86400), 0)


@dataclass(frozen=True)
class UsageStatus:
    """Quanto o usuário já gastou do mês e o que ainda pode fazer."""
    plan: Plan
    minutes_used: float
    region: str = "US"

    @property
    def minutes_left(self) -> float:
        return max(self.plan.monthly_minutes - self.minutes_used, 0.0)

    @property
    def percent_used(self) -> float:
        if not self.plan.monthly_minutes:
            return 0.0
        return round(min(self.minutes_used / self.plan.monthly_minutes, 1.0), 3)

    @property
    def exhausted(self) -> bool:
        return self.minutes_left <= 0

    def can_process(self, video_minutes: float) -> tuple[bool, str]:
        """
        Se o vídeo cabe no que resta do mês.

        Recusa ANTES de processar, e diz quanto falta — descobrir que
        acabou depois de esperar 20 minutos seria péssimo.
        """
        if self.exhausted:
            return False, (
                f"Seus {self.plan.monthly_minutes} minutos do mês acabaram. "
                f"O limite renova no início do próximo mês."
            )
        if video_minutes > self.minutes_left:
            return False, (
                f"Este vídeo tem {video_minutes:.0f} minutos, mas você só tem "
                f"{self.minutes_left:.0f} disponíveis neste mês."
            )
        return True, ""

    def as_dict(self) -> dict:
        price = self.plan.price_for(self.region)
        return {
            "plan": self.plan.id,
            "plan_name": self.plan.name,
            "minutes_used": round(self.minutes_used, 1),
            "minutes_total": self.plan.monthly_minutes,
            "minutes_left": round(self.minutes_left, 1),
            "percent_used": self.percent_used,
            "exhausted": self.exhausted,
            "retention_days": self.plan.retention_days,
            "watermark": self.plan.watermark,
            "ai_extras_included": self.plan.ai_extras_included,
            "priority_queue": self.plan.priority_queue,
            "brand_kit": self.plan.brand_kit,
            "region": self.region,
            "price": {
                "currency": price.currency,
                "amount": price.monthly,
                "formatted": price.formatted,
            },
        }


def describe_plans(region: str = "US") -> list[dict]:
    """Tabela de planos pra tela de preços, já na moeda da região."""
    out = []
    for plan in PLANS.values():
        price = plan.price_for(region)
        out.append({
            "id": plan.id,
            "name": plan.name,
            "monthly_minutes": plan.monthly_minutes,
            "retention_days": plan.retention_days,
            "watermark": plan.watermark,
            "ai_extras_included": plan.ai_extras_included,
            "priority_queue": plan.priority_queue,
            "brand_kit": plan.brand_kit,
            "price": {
                "currency": price.currency,
                "amount": price.monthly,
                "formatted": "Grátis" if price.monthly == 0 else price.formatted,
            },
        })
    return out
