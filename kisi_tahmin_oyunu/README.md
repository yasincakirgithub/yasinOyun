# Kim Bu? — Online Karakter Tahmin Oyunu

Django + Channels (WebSocket) ile geliştirilmiş, iki kişilik online "Guess Who"
(Kim Bu?) oyunu. Oyuncular `characters/` klasöründeki karakterlerden birini gizli
olarak seçer, sırayla birbirlerine evet/hayır soruları sorar ve rakip karakteri
elemeye çalışır.

## Özellikler

- WebSocket üzerinden gerçek zamanlı iki kişilik oyun
- Oda kodu ile arkadaşını davet etme
- `characters/` klasöründeki görsellerden otomatik oluşan karakter tahtası
- Sıra tabanlı soru/cevap akışı ve oyun içi sohbet
- Soru sorana kadar sıranın kendisinde kaldığı, cevaptan sonra sıranın rakibe geçtiği akış
- Karakterleri tek tıklamayla eleme (işaretleme)
- Yanlış tahmin oyunu kaybettirir; doğru tahmin kazandırır
- Mobil ve masaüstüne uyumlu, kağıt/not defteri temalı arayüz
- Docker ile kolay kurulum

## Oyun Kuralları

1. Her oyuncu gizli bir karakter seçer (rakip bunu göremez).
2. Oyuncular sırayla birbirlerine evet/hayır sorusu sorar.
3. Cevap verildikten sonra sıra cevap veren oyuncuya geçer.
4. Tahmin sırası gelen oyuncu, rakip karakteri tahmin edebilir:
   - Doğru tahmin: oyunu kazanır.
   - Yanlış tahmin: oyunu kaybeder.
5. Kazanan, rakibin karakterini doğru tahmin eden oyuncudur.

## Gereksinimler

- Docker ve Docker Compose
- veya Python 3.11+, PostgreSQL, Redis (yerel geliştirme için)

## Tek Sunucuda (EC2) Kurulum

Bu senaryoda PostgreSQL **ve Redis**, iki oyun klasörünün bir üstündeki ortak
`../docker-compose.yml` ile host üzerinde Docker'da çalışmaktadır. Uygulama kendi
veritabanı/önbellek konteynerini başlatmaz; mevcut sunuculara bağlanıp içindeki
`kimbu` veritabanını ve ortak Redis'i kullanır. Stack yalnızca `web` (Django/ASGI)
ve isteğe bağlı `db-init` servislerini çalıştırır.

1. Ortak altyapıyı başlatın (bir kez):
   ```bash
   cd ..
   docker compose up -d
   cd kisi_tahmin_oyunu
   ```
2. Ortam dosyası:
   ```bash
   cp .env.example .env
   # .env içinde ALLOWED_HOSTS / CSRF_TRUSTED_ORIGINS ve DB_* / DATABASE_URL
   # değerlerini EC2 IP veya alan adına göre düzenleyin.
   ```
3. Uygulamayı başlatın:
   ```bash
   docker compose up -d --build
   ```
4. Oyun: `http://<EC2_PUBLIC_IP>:8001`

Konteyner, host'taki ortak PostgreSQL ve Redis'e `host.docker.internal` üzerinden
ulaşır (`extra_hosts: host-gateway`). Bağlantı bilgileri `.env` içindeki `DB_*` /
`REDIS_URL` değişkenleriyle veya tek satırda `DATABASE_URL` ile verilir. Başlangıçta
`ensure_db.py`, `DB_NAME` ile verilen veritabanını yoksa oluşturur; ardından
migrate otomatik uygulanır.

> `db-init` hâlâ isteğe bağlı tek seferlik bir yardımcı olarak kullanılabilir:
> `docker compose --profile init run --rm db-init`.

> HTTPS/TLS kurana kadar `SECURE_SSL_REDIRECT=False` bırakın. Doğrudan IP
> üzerinden HTTP ile erişimi bu ayar sağlar. TLS arkasına geçince `True` yapın
> ve `ALLOWED_HOSTS` ile `CSRF_TRUSTED_ORIGINS` değerlerini güncelleyin.

## Docker Dosyaları

- `Dockerfile`: docker-compose için varsayılan imaj (ASGI, uvicorn).
- `Dockerfile.dev`: geliştirme imajı (`config.settings`, otomatik reload).
- `Dockerfile.prod`: üretim imajı (gunicorn + uvicorn worker).
- `docker-compose.yml`: `web` servisi ve isteğe bağlı `db-init` (PostgreSQL/Redis
  üst seviyedeki ortak `../docker-compose.yml` içindedir).
- `ensure_db.py`: başlangıçta veritabanı yoksa oluşturur.
- `.dockerignore`: imaja kopyalanmayacak dosyalar.

Karakter görselleri `characters/` klasöründedir ve `STATICFILES_DIRS` içinde
`characters` önekiyle tanımlıdır; bu sayede `collectstatic` sonrası
`/static/characters/` altından servis edilir.

## Yerel Geliştirme (Docker'sız)

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

WebSocket desteği için Redis çalışıyor olmalıdır (`redis-server`).

## API Uç Noktaları

Sayfalar:
- `GET /` veya `GET /game/` — ana sayfa (oyun kur / katıl)
- `GET /game/<room_code>/` — oyun odası

REST ( `/game/api/` ):
- `POST /game/api/create/` — yeni oda oluşturur
- `POST /game/api/join/` — odaya katılır
- `GET /game/api/state/<room_code>/` — odanın genel durumu

WebSocket:
- `WS /ws/game/<room_code>/`

WebSocket mesaj tipleri: `join_player`, `choose_character`, `send_chat`,
`ask_question`, `answer_question`, `make_accusation`, `set_eliminated`,
`restart_game`, `get_state`.

## Testler

```bash
python manage.py test
```

## Lisans

MIT
