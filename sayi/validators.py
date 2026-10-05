from django.core.exceptions import ValidationError


def validate_four_digit_unique(value):
    """
    Validate that value is exactly 4 digits, all unique, and first digit not zero.
    Raises ValidationError if invalid.
    """
    if not isinstance(value, str):
        raise ValidationError('Metin olmalı.')
    if not value.isdigit() or len(value) != 4:
        raise ValidationError('Tam 4 basamaklı olmalı.')
    if value[0] == '0':
        raise ValidationError('İlk basamak 0 olamaz.')
    if len(set(value)) != 4:
        raise ValidationError('Tüm rakamlar birbirinden farklı olmalı.')