"""
Envio de e-mail de confirmação de conta, via API da Resend
(https://resend.com — 3.000 e-mails grátis por mês, sem cartão).

Precisa de 2 variáveis no seu .env:
    RESEND_API_KEY=re_sua_chave_aqui
    RESEND_FROM_EMAIL=onboarding@seudominio.com  (domínio verificado na Resend)

Se essas variáveis não estiverem configuradas, o cadastro continua
funcionando, mas o e-mail não é enviado de verdade (só um aviso no console)
— evita que o app trave por causa disso durante o desenvolvimento.
"""
from __future__ import annotations

import os

RESEND_API_URL = "https://api.resend.com/emails"


def send_verification_email(to_email: str, username: str, verification_url: str) -> bool:
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    from_address = os.environ.get("RESEND_FROM_EMAIL", "").strip()

    if not api_key or not from_address:
        print(
            "[ClipRadar] RESEND_API_KEY ou RESEND_FROM_EMAIL não configurados no .env "
            "— e-mail de confirmação NÃO foi enviado de verdade."
        )
        print(f"[ClipRadar] Link de confirmação (use manualmente por enquanto): {verification_url}")
        return False

    try:
        import requests
    except ImportError:
        print("[ClipRadar] Biblioteca requests não instalada. Rode: pip install requests")
        return False

    payload = {
        "from": from_address,
        "to": [to_email],
        "subject": "Confirme sua conta no ClipRadar",
        "html": (
            f"<p>Oi, {username}!</p>"
            f"<p>Clique no link abaixo pra confirmar sua conta no ClipRadar:</p>"
            f'<p><a href="{verification_url}">{verification_url}</a></p>'
            f"<p>Se você não criou essa conta, pode ignorar este e-mail.</p>"
        ),
    }
    try:
        response = requests.post(
            RESEND_API_URL,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=10,
        )
        if response.status_code >= 300:
            print(f"[ClipRadar] Resend recusou o envio ({response.status_code}): {response.text[:300]}")
        return response.status_code < 300
    except Exception as e:
        print(f"[ClipRadar] Falha ao enviar e-mail: {e}")
        return False
