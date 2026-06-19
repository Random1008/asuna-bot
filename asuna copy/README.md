# Lancer le bot

Il faut que tu fasse 
``` bash
git clone https://github.com/Random1008/asuna-bot.git
cd /asuna-bot/
ls
# si il y a encore un dossier asuna-bot refait cd /asuna-bot si il y a un bot.py continue
```
> Le `.env` est déjà rempli a l'exception du token fait :
> nano .env
> #rentre ton token

```bash
cd "asuna copy"
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

Pour réinstaller plus tard, juste :
>
> ```bash
> source .venv/bin/activate
> python bot.py
> ```
