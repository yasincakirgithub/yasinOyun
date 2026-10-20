import json

from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import Comment

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
        'image': 'sayi/img/sayi_tahmin.png',
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
        'image': 'kim/img/kim_bu.png',
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
        'image': 'amiral/img/amiral_batti.png',
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
        'image': 'satranc/img/satranc.png',
    },
    {
        'slug': 'okey101',
        'url_name': 'okey101:home',
        'title': '101 Okey',
        'description': (
            '2-4 kişilik klasik 101 Okey. Oda kur, taş çek, perlerini aç '
            've elini ilk bitiren ol.'
        ),
        'tag': 'Kart',
        'image': 'okey101/img/okey101.svg',
    },
]


GAME_SLUGS = {game['slug'] for game in GAMES}
COMMENT_LIMIT = 100
GAMES_PAGE_SIZE = 3
_TR_SEARCH_MAP = str.maketrans({
    'ç': 'c', 'Ç': 'c', 'ğ': 'g', 'Ğ': 'g', 'ı': 'i', 'I': 'i', 'İ': 'i',
    'ö': 'o', 'Ö': 'o', 'ş': 's', 'Ş': 's', 'ü': 'u', 'Ü': 'u',
})


def _search_key(value):
    return value.translate(_TR_SEARCH_MAP).lower()


def _serialize_comment(comment):
    return {
        'author': comment.author_name or 'Misafir',
        'body': comment.body,
        'created_at': timezone.localtime(comment.created_at).strftime('%d.%m.%Y %H:%M'),
    }


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def comments(request, game):
    """List or add comments for a single game's landing page."""
    if game not in GAME_SLUGS:
        return JsonResponse({'success': False, 'error': 'Geçersiz oyun.'}, status=404)

    if request.method == 'GET':
        items = [_serialize_comment(c) for c in Comment.objects.filter(game=game)[:COMMENT_LIMIT]]
        return JsonResponse({'success': True, 'comments': items})

    try:
        data = json.loads(request.body or '{}')
    except ValueError:
        data = {}

    author = (data.get('name') or '').strip()[:30]
    body = (data.get('body') or '').strip()[:500]

    if not body:
        return JsonResponse({'success': False, 'error': 'Yorum boş olamaz.'}, status=400)

    comment = Comment.objects.create(game=game, author_name=author, body=body)
    return JsonResponse({'success': True, 'comment': _serialize_comment(comment)})


def home(request):
    """Landing page: let the visitor pick which game to play."""
    return render(request, 'core/home.html', {'games': GAMES})


def games(request):
    """Searchable, paginated catalogue of all games."""
    query = (request.GET.get('q') or '').strip()

    items = GAMES
    if query:
        needle = _search_key(query)
        items = [
            game for game in GAMES
            if needle in _search_key(game['title'])
            or needle in _search_key(game['description'])
            or needle in _search_key(game['tag'])
        ]

    paginator = Paginator(items, GAMES_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'core/games.html', {
        'page_obj': page_obj,
        'query': query,
        'total': paginator.count,
    })
