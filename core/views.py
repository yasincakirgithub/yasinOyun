from django.shortcuts import render

# Games shown on the landing page.
GAMES = [
    {
        'slug': 'sayi',
        'url_name': 'sayi:home',
        'title': 'Sayı Tahmin Oyunu',
        'description': (
            'Rakibinin 4 basamaklı gizli sayısını artı/eksi ipuçlarıyla '
            'tahmin etmeye çalış.'
        ),
        'tag': 'Rakam',
    },
    {
        'slug': 'kim-bu',
        'url_name': 'kim:home',
        'title': 'Kim Bu?',
        'description': (
            'Gizli karakterini seç, evet/hayır soruları sor ve rakibinin '
            'karakterini bul.'
        ),
        'tag': 'Karakter',
    },
]


def home(request):
    """Landing page: let the visitor pick which game to play."""
    return render(request, 'core/home.html', {'games': GAMES})
