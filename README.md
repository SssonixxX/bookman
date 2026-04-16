# Booking Manager

MVP web per la gestione commerciale del booking artistico. L'app e pensata come CRM verticale per raccogliere, filtrare e seguire locali, club, hotel, beach club ed eventi.

## Stack

- `Flask` per backend, routing e API JSON
- `SQLite` per persistenza locale semplice da distribuire
- `HTML/CSS/JavaScript` vanilla per frontend rapido e facilmente estendibile
- `Supabase` supportato come backend dati alternativo via REST API

## Architettura consigliata

- `web_app.py`: bootstrap applicazione, schema database, API CRUD, dashboard e pipeline
- `templates/index.html`: layout applicativo, viste principali e drawer dettaglio
- `static/styles.css`: UI responsive, palette e componenti visuali
- `static/app.js`: logica frontend, fetch API, filtri, ricerca, CRUD e navigazione tab
- `data/booking_manager.db`: database SQLite creato automaticamente al primo avvio
- `supabase_schema.sql`: schema da eseguire nel progetto Supabase
- `supabase.env.example`: esempio variabili per backend Supabase

## Modello dati

### `venues`

Contiene anagrafica locale, geografia flessibile, canali di contatto, stato, priorita, note, follow-up e tag.

### `venue_activities`

Storico aggiornamenti e interazioni interne legate a ogni locale.

### `booking_dates`

Date chiuse o confermate associate a un locale.

## Schermate MVP

- Dashboard con contatori, pipeline, priorita e ultimi aggiornamenti
- Archivio locali con ricerca full-text e filtri
- Form rapido di inserimento/modifica
- Precompilazione da URL pubblico di sito o social del locale
- Follow-up con evidenza di scadenze e ritardi
- Trattative attive
- Date chiuse
- Impostazioni roadmap

## Avvio

1. Installare Flask se non presente:

```powershell
python -m pip install flask
```

2. Avviare l'app:

```powershell
python web_app.py
```

3. Aprire il browser su `http://127.0.0.1:5000`

## Deploy su Vercel

L'app e pronta per essere pubblicata su `Vercel` tramite repository `GitHub`.

File gia predisposti:

- [vercel.json](/C:/Users/pakyj/Desktop/Booking%20Manager/vercel.json)
- [api/index.py](/C:/Users/pakyj/Desktop/Booking%20Manager/api/index.py)
- [requirements.txt](/C:/Users/pakyj/Desktop/Booking%20Manager/requirements.txt)
- [.gitignore](/C:/Users/pakyj/Desktop/Booking%20Manager/.gitignore)

### Variabili ambiente da configurare in Vercel

Per il deploy usa `Supabase`, non `SQLite`, perche il filesystem di Vercel non e adatto alla persistenza del database locale.

Inserisci in `Vercel Project Settings > Environment Variables`:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `FLASK_SECRET_KEY`

Opzionale:

- `SUPABASE_ANON_KEY`

### Flusso consigliato

1. Inizializza la repository Git locale.
2. Crea una nuova repository vuota su GitHub.
3. Collega il remote GitHub e fai il primo push.
4. Importa la repository dentro Vercel.
5. Configura le variabili ambiente.
6. Esegui il primo deploy.

### Comandi Git locali

```powershell
git init
git add .
git commit -m "Initial Booking Manager CRM"
git branch -M main
git remote add origin https://github.com/TUO-USERNAME/NOME-REPOSITORY.git
git push -u origin main
```

### Configurazione Vercel

Su Vercel:

1. `Add New...` -> `Project`
2. seleziona la repository GitHub del CRM
3. framework preset: `Other`
4. root directory: lascia la root del progetto
5. aggiungi le environment variables
6. deploy

Una volta completato il deploy, l'app usera le API Flask servite da `api/index.py` e i dati resteranno su `Supabase`.

## Backend Supabase

Se vuoi usare Supabase al posto di SQLite:

1. Esegui il contenuto di [supabase_schema.sql](/C:/Users/pakyj/Desktop/Booking%20Manager/supabase_schema.sql:1) nel SQL editor di Supabase.
2. Crea un file locale `supabase.env` nella root del progetto copiando [supabase.env.example](/C:/Users/pakyj/Desktop/Booking%20Manager/supabase.env.example:1).
3. Inserisci `SUPABASE_URL`, `SUPABASE_ANON_KEY` e `SUPABASE_SERVICE_ROLE_KEY`.
4. Riavvia l'app.

Quando `SUPABASE_URL` e `SUPABASE_SERVICE_ROLE_KEY` sono presenti, il backend usa Supabase REST; altrimenti resta su SQLite.

## Inserimento rapido da link

Nella schermata `Nuovo locale` e disponibile un box dove incollare il sito web o il profilo social del locale. Il backend prova a leggere meta tag, dati strutturati `JSON-LD` e contatti pubblici per precompilare i campi principali.

Flusso attuale:

- `Analizza link`: recupera i dati pubblici e mostra un'anteprima di conferma
- `Compila il form`: inserisce i dati trovati nel form per revisione manuale
- `Conferma e salva`: crea subito il locale senza passare dal form, se e stato trovato almeno il nome

Parser supportati meglio nel MVP attuale:

- siti web ufficiali con meta tag o `JSON-LD`
- profili `Instagram`
- pagine `Facebook`
- pagine interne utili come `contatti`, `about`, `booking`, `info`, `location`
- OCR invisibile su alcune immagini della pagina quando contengono testo utile

L'import ora usa solo metodi classici di scraping e OCR locale, senza dipendere da API AI esterne.

Limite attuale MVP: l'estrazione dipende da quanto il sito o social espone dati pubblici leggibili. Alcuni campi potrebbero restare vuoti o richiedere correzione manuale, soprattutto su siti che bloccano crawler o rendono il contenuto solo via JavaScript.
