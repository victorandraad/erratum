import os


def t(en, pt):
    """Texto humano: inglês por padrão, português com ERRATUM_LANG=pt. Lido a cada chamada."""
    return pt if os.environ.get("ERRATUM_LANG", "").lower().startswith("pt") else en
