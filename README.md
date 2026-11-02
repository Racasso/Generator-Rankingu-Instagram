# Oskar Kuban — ranking twórców Instagram

Backend REST API do tworzenia kampanii Instagram, pobierania publicznych danych o postach i profilach przez aktory Apify Store oraz zwracania rankingu twórców. Dane są przechowywane w MongoDB, a pobieranie wykonują workery działające w tle.

## Najważniejsze funkcje

- Tworzenie kampanii na podstawie listy nazw użytkowników Instagram albo bezpośrednich URL-i postów.
- Zlecanie pobierania jako zadania asynchronicznego i sprawdzanie jego statusu.
- Pobieranie postów i profili przez oficjalną bibliotekę [`apify-client`](https://docs.apify.com/api/client/python/) oraz aktory Apify Store.
- Obliczanie publicznego wskaźnika ER względem liczby obserwujących i sortowanie twórców według wyniku.
- Zapis identyfikatorów, statusów i kosztów runów Apify w dokumencie zadania.
- Obsługa wielu workerów, idempotentnych żądań z kluczem `Idempotency-Key` i ponownego przejęcia zadania po wygaśnięciu czasowej rezerwacji workera.
- Interaktywna dokumentacja API generowana przez FastAPI.

## Jak działa projekt

1. API zapisuje definicję kampanii w MongoDB.
2. `POST /campaigns/{campaign_id}/jobs` dodaje zadanie do kolejki.
3. Worker pobiera zadanie i uruchamia aktory Apify: post scraper, a następnie profile scraper dla znalezionych twórców.
4. Wyniki są normalizowane, zapisywane w MongoDB i udostępniane przez `GET /campaigns/{campaign_id}`.

API nie wydaje automatycznej rekomendacji współpracy. Zwraca dane i wskaźniki, które można wykorzystać przy podejmowaniu decyzji.

## Wymagania

Do uruchomienia przez Docker Compose potrzebujesz:

- Docker Engine z Docker Compose;
- tokenu Apify (`APIFY_TOKEN`), aby worker mógł uruchamiać aktory.

Do uruchomienia bezpośrednio na hoście potrzebujesz Pythona 3.12, MongoDB oraz tych samych zmiennych środowiskowych. Dockerfile używa `python:3.12-slim`, a Compose uruchamia MongoDB `mongo:8.0`.

Zależności Pythona są przypięte w [`requirements.txt`](requirements.txt): FastAPI, Pydantic, PyMongo, `apify-client`, Uvicorn i pytest.

## Szybki start w Dockerze

1. Utwórz lokalny plik konfiguracyjny na podstawie przykładu:

   ```bash
   cp .env.example .env
   ```

2. Otwórz `.env` i wpisz token Apify w `APIFY_TOKEN`. Nie publikuj ani nie commituj tego pliku — `.gitignore` wyklucza `.env` z repozytorium.

3. Zbuduj obrazy i uruchom API, MongoDB oraz trzy workery:

   ```bash
   docker compose up --build --scale worker=3 -d
   ```

4. Sprawdź API i otwórz dokumentację interaktywną:

   - Dokumentacja: <http://localhost:8000/docs>
   - Healthcheck: <http://localhost:8000/health>

Compose czeka z uruchomieniem API i workerów, aż healthcheck MongoDB potwierdzi gotowość bazy. Domyślna konfiguracja udostępnia API na porcie `8000`, a MongoDB tylko lokalnie pod `127.0.0.1:27017`.

Endpointy API w tej wersji nie wymagają uwierzytelniania; przykłady w tym README zakładają lokalne uruchomienie projektu.

## Konfiguracja

Przykładowe wartości i domyślne identyfikatory aktorów znajdują się w [`.env.example`](.env.example). Wartości `APIFY_TOKEN` trzeba uzupełnić lokalnie.

| Zmienna | Znaczenie | Domyślna wartość lub zachowanie |
| --- | --- | --- |
| `APIFY_TOKEN` | Token używany przez `apify-client`. | Brak. Bez tokenu zadanie zakończy się kodem `apify_token_missing`. |
| `APIFY_POSTS_ACTOR_ID` | Aktor pobierający posty. | `apify/instagram-post-scraper` |
| `APIFY_PROFILE_ACTOR_ID` | Aktor pobierający profile i liczbę obserwujących. | `apify/instagram-profile-scraper` |
| `APIFY_MAX_RUN_COST_USD` | Limit przekazywany do pojedynczego runu aktora. Kampania może uruchomić oba aktory. | `0.50` USD na run |
| `MONGODB_URI` | Adres MongoDB. | Lokalnie: `mongodb://localhost:27017`; w Compose URI jest ustawiany na `mongodb://mongo:27017`. |
| `MONGODB_DATABASE` | Nazwa bazy danych. | `creator_ranker` |
| `WORKER_POLL_SECONDS` | Odstęp między sprawdzeniami kolejki przez workera. | `2` sekundy; worker nie schodzi poniżej 1 sekundy. |
| `LOG_LEVEL` | Poziom logowania workera. | `INFO` |

Wartości z `.env` Compose przekazuje kontenerom. W trybie lokalnym załaduj je do środowiska powłoki przed uruchomieniem API i workera.

## Uruchomienie lokalne bez kontenerów aplikacji

Ten wariant uruchamia w Dockerze tylko MongoDB, a API i worker jako procesy Pythona na hoście.

1. Utwórz i aktywuj środowisko wirtualne, zainstaluj zależności i przygotuj `.env`:

   ```bash
   python --version
   python -m venv .venv
   source .venv/bin/activate
   python -m pip install -r requirements.txt
   cp .env.example .env
   ```

2. Wpisz token Apify do `.env` i uruchom MongoDB:

   ```bash
   docker compose up -d mongo
   ```

3. W pierwszym terminalu, w katalogu projektu i z aktywnym `.venv`, załaduj zmienne i uruchom API:

   ```bash
   set -a
   . ./.env
   set +a
   uvicorn app.api:app --reload
   ```

4. W drugim terminalu aktywuj to samo środowisko wirtualne, załaduj `.env` i uruchom workera:

   ```bash
   set -a
   . ./.env
   set +a
   python -m app.worker
   ```

## Użycie API

Wszystkie poniższe przykłady zakładają, że API działa pod `http://localhost:8000`. Te same operacje można wykonać w `/docs`.

### 1. Zapisz kampanię

Kampania przyjmuje dokładnie jedno źródło danych: `creator_usernames` albo `post_urls`.

Przykład dla profili. Podmień przykładowe nazwy użytkowników i daty na dane kampanii:

```bash
curl -X PUT http://localhost:8000/campaigns/oskar-kuban \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Oskar Kuban",
    "period_start": "2026-10-01",
    "period_end": "2026-10-31",
    "creator_usernames": ["creator_one", "creator_two"],
    "results_limit_per_creator": 50
  }'
```

Alternatywnie możesz podać bezpośrednie URL-e postów. Zastąp `POST_CODE` prawdziwym kodem posta:

```bash
curl -X PUT http://localhost:8000/campaigns/oskar-kuban-posts \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Oskar Kuban",
    "period_start": "2026-10-01",
    "period_end": "2026-10-31",
    "post_urls": ["https://www.instagram.com/p/POST_CODE/"]
  }'
```

Zakres dat jest włącznie od `period_start` do `period_end`; daty publikacji są porównywane w UTC. Dla profili aktor pobiera do `results_limit_per_creator` postów od daty początkowej, pomija posty przypięte, a aplikacja odrzuca posty po dacie końcowej. Limit wynosi od 1 do 100. Jeśli w okresie od daty początkowej pojawiło się więcej postów niż limit, starsze posty mogą nie zostać pobrane. Dla konkretnej kampanii dokładniejsze są URL-e jej postów.

`results_limit_per_creator` jest opcjonalne i domyślnie wynosi `50`. Możesz podać maksymalnie 100 nazw użytkowników albo 200 URL-i postów. Nazwa kampanii ma od 1 do 200 znaków; nazwy użytkowników i URL-e w danej liście muszą być unikalne.

Nazwy użytkowników są przyjmowane z opcjonalnym `@`, a następnie normalizowane przez usunięcie spacji brzegowych i zmianę liter na małe. URL-e muszą używać HTTPS oraz hosta `instagram.com` albo `www.instagram.com`.

`campaign_id` może zawierać litery ASCII, cyfry, `_` i `-`, musi zaczynać się od litery lub cyfry i mieć maksymalnie 100 znaków. Ponowne zapisanie tego samego ID z tą samą definicją jest dozwolone; inna definicja pod tym samym ID zwróci `409 campaign_id_conflict`.

### 2. Zleć pobranie

```bash
curl -X POST http://localhost:8000/campaigns/oskar-kuban/jobs \
  -H 'Idempotency-Key: oskar-kuban-2026-10-run-1'
```

Odpowiedź `202 Accepted` zawiera `job_id` i początkowy status `queued`. Nagłówek `Idempotency-Key` jest opcjonalny. Powtórzenie go w ramach tej samej kampanii zwróci to samo zadanie; nowe pobranie powinno dostać nowy klucz.

### 3. Sprawdź status zadania

Wstaw `job_id` z poprzedniej odpowiedzi:

```bash
curl http://localhost:8000/jobs/JOB_ID
```

Status zadania to `queued`, `running`, `done` albo `failed`. Odpowiedź zawiera też liczbę prób, identyfikatory i statusy runów aktorów, zarejestrowane koszty oraz — w przypadku błędu — `error_code`.

### 4. Pobierz ranking

Po uzyskaniu statusu `done` pobierz wynik kampanii:

```bash
curl http://localhost:8000/campaigns/oskar-kuban
```

Dokument zawiera definicję kampanii, podsumowanie liczby twórców i postów oraz listę twórców z pozycją `rank`, metrykami i postami.

### Dostępne endpointy

| Metoda i ścieżka | Działanie |
| --- | --- |
| `GET /health` | Sprawdza dostępność MongoDB. |
| `PUT /campaigns/{campaign_id}` | Tworzy kampanię albo potwierdza istniejącą definicję. |
| `GET /campaigns/{campaign_id}` | Zwraca kampanię z rankingiem i postami. |
| `POST /campaigns/{campaign_id}/jobs` | Dodaje zadanie pobierania do kolejki. |
| `GET /jobs/{job_id}` | Zwraca status zadania i zapisane runy aktorów. |

## Metryki i ograniczenia

`engagement_rate_by_followers_pct` jest liczony według wzoru:

```text
100 × suma(polubień + komentarzy) / (liczba postów × liczba obserwujących)
```

To średnia liczba publicznych polubień i komentarzy na post odniesiona do aktualnej liczby obserwujących. Wskaźnik jest obliczany tylko wtedy, gdy liczba obserwujących jest większa od zera i każdy post twórcy ma dostępne oba liczniki interakcji. Wynik jest zaokrąglany do czterech miejsc po przecinku.

Twórcy są sortowani malejąco po ER; remisy rozstrzygają kolejno większa liczba obserwujących i nazwa użytkownika rosnąco. Wysoki ER oparty na jednym poście może nie odzwierciedlać typowych wyników twórcy.

- `followers_count` jest odczytywany w czasie pobrania profilu, a nie w dniu publikacji postów.
- `actual_reach` pozostaje `null`. Publiczne dane aktorów nie zawierają Instagram Insights potrzebnych do policzenia rzeczywistego zasięgu.
- `video_plays_total` jest sumą dostępnych liczników odtworzeń; pozostaje `null`, jeśli aktor nie zwrócił ich dla żadnego postu. Odtworzenia nie są zasięgiem.
- Jeżeli w danym zadaniu brakuje tokenu Apify, job kończy się statusem `failed` i kodem `apify_token_missing`.

## Testy

Testy korzystają z MongoDB. Możesz uruchomić bazę i testy z katalogu projektu:

```bash
docker compose up -d mongo
python -m pytest
```

Albo uruchomić testy w kontenerze API:

```bash
docker compose run --rm api python -m pytest
```

Fixture testowa używa `TEST_MONGODB_URI`, jeśli jest ustawione, w przeciwnym razie `MONGODB_URI` albo domyślnego `mongodb://localhost:27017`. Gdy MongoDB jest niedostępne, testy korzystające z bazy są pomijane.

Testy obejmują normalizację przykładowych danych aktorów i wyliczanie metryk, zastępowanie wcześniej zapisanego posta o tym samym URL-u oraz atomowe przejmowanie zadań przez równoległe workery.

## Struktura projektu

```text
app/
  api.py       endpointy HTTP i inicjalizacja aplikacji
  apify.py     wywołania aktorów i normalizacja ich danych
  db.py        MongoDB, kolejka zadań i agregacja rankingu
  models.py    modele i walidacja danych API
  worker.py    pobieranie i obsługa zadań w tle
tests/
  test_*.py    testy metryk, idempotencji i workerów
  fixtures/    przykładowe odpowiedzi aktorów i dane testowe
Dockerfile
docker-compose.yml
requirements.txt
.env.example
```

Źródła i przeznaczenie przykładowych danych w testach opisuje [`tests/fixtures/README.md`](tests/fixtures/README.md).

## Diagnostyka

- **`GET /health` zwraca `503 database_unavailable`** — API nie może połączyć się z MongoDB. Sprawdź, czy usługa MongoDB działa i czy `MONGODB_URI` wskazuje właściwy adres. W Compose URI wewnątrz kontenerów ma host `mongo`.
- **Job kończy się kodem `apify_token_missing`** — uzupełnij `APIFY_TOKEN` w `.env` i ponownie uruchom usługi Compose.
- **`409 campaign_id_conflict`** — pod używanym ID jest już inna definicja kampanii. Użyj nowego `campaign_id` albo zapisz dokładnie tę samą definicję.
- **`422` przy zapisie kampanii** — sprawdź, czy podano dokładnie jedno niepuste źródło (`creator_usernames` lub `post_urls`), prawidłowy zakres dat i poprawny format URL-i.
- **Job ma status `failed`** — sprawdź `error_code` i `actor_runs` w `GET /jobs/{job_id}`. Przy błędzie aktora odpowiedź zawiera jego identyfikator runu, który ułatwia dalszą diagnostykę w Apify.

## Powiązane linki

- [Dokumentacja interaktywna API](http://localhost:8000/docs) — dostępna po uruchomieniu projektu.
- [Aktor Apify Instagram Post Scraper](https://apify.com/apify/instagram-post-scraper)
- [Aktor Apify Instagram Profile Scraper](https://apify.com/apify/instagram-profile-scraper)
- [Dokumentacja klienta Apify dla Pythona](https://docs.apify.com/api/client/python/)
