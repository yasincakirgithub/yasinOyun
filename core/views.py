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
        'slug': 'satranc',
        'url_name': 'satranc:home',
        'title': 'Satranç',
        'description': (
            'Klasik iki kişilik satranç. Oda kur, kodu paylaş ya da '
            'Stockfish botuna karşı stratejini test et.'
        ),
        'tag': 'Strateji',
        'tone': 'violet',
        'players': '2 oyuncu',
        'mode': 'Canlı / Bot',
        'image': 'core/img/satranc.webp',
        'image_width': 1600,
        'image_height': 497,
    },
    {
        'slug': 'kim-bu',
        'url_name': 'kim:home',
        'title': 'Kim Bu?',
        'description': (
            'Gizli karakterini seç, evet/hayır soruları sor ve rakibinin '
            'karakterini herkesten önce bul.'
        ),
        'tag': 'Parti',
        'tone': 'coral',
        'players': '2 oyuncu',
        'mode': 'Canlı',
        'image': 'core/img/kim_bu.webp',
        'image_width': 1600,
        'image_height': 497,
    },
    {
        'slug': 'okey101',
        'url_name': 'okey101:home',
        'title': '101 Okey',
        'description': (
            '2–4 kişilik klasik 101 Okey. Oda kur, taş çek, perlerini aç '
            've elini ilk bitiren ol.'
        ),
        'tag': 'Masa Oyunu',
        'tone': 'amber',
        'players': '2–4 oyuncu',
        'mode': 'Canlı',
        'image': 'core/img/okey.webp',
        'image_width': 1600,
        'image_height': 497,
    },
    {
        'slug': 'codenames',
        'url_name': 'codenames:home',
        'title': 'Codenames',
        'description': (
            'İki takım, gizli ajanlar ve tek kelimelik ipuçları. Spymaster '
            'ipucunu ver, operatifler doğru kelimeleri bulmadan rakibine fırsat verme.'
        ),
        'tag': 'Parti',
        'tone': 'cyan',
        'players': '4–10 oyuncu',
        'mode': 'Canlı',
        'image': 'core/img/codenames.svg',
        'image_width': 1600,
        'image_height': 497,
    },
    {
        'slug': 'fcmanager',
        'url_name': 'fcmanager:home',
        'title': 'FC Manager',
        'description': (
            'Bütçeni yönet, ortak görevleri tamamla ve sürükle-bırak ile '
            'hayalindeki 11’i kur. Rakibinle mini maç simülasyonunda karşılaş.'
        ),
        'tag': 'Spor',
        'tone': 'emerald',
        'players': '2 oyuncu',
        'mode': 'Canlı',
        'image': 'core/img/fcmanager.svg',
        'image_width': 1600,
        'image_height': 497,
    },
    {
        'slug': 'amiral',
        'url_name': 'amiral:home',
        'title': 'Amiral Battı',
        'description': (
            'Gemilerini yerleştir, koordinatlara ateş et ve rakibinin tüm '
            'filosunu batırmak için hamle yap.'
        ),
        'tag': 'Strateji',
        'tone': 'cyan',
        'players': '2 oyuncu',
        'mode': 'Canlı',
        'image': 'core/img/amiral_batti.webp',
        'image_width': 1600,
        'image_height': 497,
    },
    {
        'slug': 'sayi',
        'url_name': 'sayi:home',
        'title': 'Sayı Tahmin Oyunu',
        'description': (
            'Rakibinin 4 basamaklı gizli sayısını artı/eksi ipuçlarıyla '
            'tahmin etmeye çalış.'
        ),
        'tag': 'Mantık',
        'tone': 'rose',
        'players': '2 oyuncu',
        'mode': 'Canlı',
        'image': 'core/img/sayi_tahmin.svg',
        'image_width': 1200,
        'image_height': 675,
    },
]


GAME_SLUGS = {game['slug'] for game in GAMES}
COMMENT_LIMIT = 100
GAMES_PAGE_SIZE = 6
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
