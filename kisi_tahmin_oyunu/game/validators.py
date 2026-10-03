from django.core.exceptions import ValidationError


def validate_four_digit_unique(value):
    """
    Validate that value is exactly 4 digits, all unique, and first digit not zero.
    Raises ValidationError if invalid.
    """
    if not isinstance(value, str):
        raise ValidationError('Must be a string.')
    if not value.isdigit() or len(value) != 4:
        raise ValidationError('Must be exactly 4 digits.')
    if value[0] == '0':
        raise ValidationError('First digit cannot be zero.')
    if len(set(value)) != 4:
        raise ValidationError('All digits must be unique.')