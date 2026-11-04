"""Codificación biyectiva de enteros no negativos; no es un hash criptográfico."""

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
INITIAL_ID = 597_652_313


def encode(number: int) -> str:
    if number < 0:
        raise ValueError("El identificador debe ser no negativo")
    if number == 0:
        return ALPHABET[0]
    digits = []
    while number:
        number, remainder = divmod(number, len(ALPHABET))
        digits.append(ALPHABET[remainder])
    return "".join(reversed(digits))


def is_valid_hash(value: str) -> bool:
    return 1 <= len(value) <= 11 and all(char in ALPHABET for char in value)
