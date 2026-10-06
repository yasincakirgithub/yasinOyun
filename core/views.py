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
    {
        'slug': 'amiral',
        'url_name': 'amiral:home',
        'title': 'Amiral Battı',
        'description': (
            'Gemilerini yerleştir, koordinatlara ateş et ve rakibinin tüm '
            'filosunu batır.'
        ),
        'tag': 'Strateji',
    },
    {
        'slug': 'satranc',
        'url_name': 'satranc:home',
        'title': 'Satranç',
        'description': (
            'Klasik iki kişilik satranç. Oda kur, kodu paylaş ve rakibini '
            'mat etmeye çalış.'
        ),
        'tag': 'Zeka',
    },
]


def home(request):
    """Landing page: let the visitor pick which game to play."""
    return render(request, 'core/home.html', {'games': GAMES})
