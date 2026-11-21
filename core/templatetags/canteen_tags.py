from django import template

register = template.Library()


@register.filter
def fcfa(value):
    """Formate un entier en FCFA : 1500 -> '1 500 FCFA'."""
    if value is None or value == "":
        return "0 FCFA"
    try:
        amount = int(value)
    except (TypeError, ValueError):
        return str(value)
    sign = "-" if amount < 0 else ""
    formatted = f"{abs(amount):,}".replace(",", "\u00a0")
    return f"{sign}{formatted}\u00a0FCFA"
