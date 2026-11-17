# Bot YouTube e Telegram

## Configurazione

1. Crea un ambiente virtuale e installa le dipendenze:

   ```powershell
   py -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

2. Copia `.env.example` in `.env` e inserisci i tuoi token, le chiavi API e gli ID.
   Il file `.env` contiene dati privati e non va condiviso.
3. Avvia il bot:

   ```powershell
   .venv\Scripts\python.exe main.py
   ```
