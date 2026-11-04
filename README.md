# Lucky Number Stats 🍀

Every school day it logs in to eduVULCAN with your login and password, reads
the *szczęśliwy numerek*, saves it to a history file, and rebuilds
`dashboard.html`: who got it most, who least, who never.

It drives a real (hidden) Chrome window, so it logs in the same way you do in
a browser.

> **Want it to run by itself and see the dashboard from anywhere?**
> See **[GITHUB_SETUP.md](GITHUB_SETUP.md)**. GitHub runs it every morning and
> publishes a password-protected dashboard.

## 1. Install (once)

Needs Python 3.9+.

```
pip install -r requirements.txt
python -m playwright install chromium
```

## 2. Your login

Copy `config.example.json` to `config.json` and fill it in:

```json
{
  "login": "your eduVULCAN login (email)",
  "password": "your password",
  "student": ""
}
```

- `student`: leave empty if the account has one student. Otherwise, put part of the student's name to pick the right one.
- `panel_url` (optional): if the app can't find the student panel by itself, open the panel in your browser and paste its address here, e.g. `https://uczen.eduvulcan.pl/yourtown/App/...`.

**`config.json` contains your password. Keep it only on your own computer.**
If you'd rather not store it in a file, set the environment variables
`EDUVULCAN_LOGIN` and `EDUVULCAN_PASSWORD` instead.

## 3. First run — watch it

```
python lucky.py daily --show
```

A browser window opens and you can watch it log in and open the panel. You should see
`Today's lucky number: N`. If something goes wrong, look in the `debug` folder:

- `error.png` is a screenshot of where it got stuck.
- `api_calls.txt` lists which panel addresses were loaded. It contains no grades or personal data.

Send me what it printed (and `api_calls.txt` if asked) and I can adjust it.

## 4. Add the class list

Copy `roster.example.csv` to `roster.csv` and put in the real names:

```
number,name
1,Adamczyk Zofia
2,Bąk Jakub
```

Without a roster, the dashboard shows numbers instead of names.

## 5. Earlier days

Try downloading past days:

```
python lucky.py backfill --since 2026-09-01
```

This checks whether eduVULCAN will return the lucky number for an earlier
date. If it will, it downloads every school day since `--since`. If not, it
says so and changes nothing.

Numbers you remember (or someone noted) can always be added by hand:

```
python lucky.py add 2026-10-15 7
```

## 6. Run it every school day

**Windows (Task Scheduler)**, in a terminal, with your path:
```
schtasks /create /tn "LuckyNumber" /sc weekly /d MON,TUE,WED,THU,FRI /st 07:45 /tr "python C:\path\to\lucky-stats\lucky.py daily"
```

**macOS / Linux (cron)**: run `crontab -e` and add:
```
45 7 * * 1-5 cd /path/to/lucky-stats && /usr/bin/python3 lucky.py daily
```

The computer needs to be on at that time. If a day is missed, add it with `add`.

## Commands

| Command | What it does |
|---|---|
| `daily [--show]` | fetch today + rebuild dashboard |
| `fetch [--show]` | fetch today only |
| `backfill --since YYYY-MM-DD` | try to download past days |
| `add YYYY-MM-DD N` | enter or correct a number by hand |
| `report` | rebuild `dashboard.html` |

History is kept in `lucky_numbers.csv` (date,number), which you can open in Excel.

## Notes

- This isn't an official VULCAN tool. If they change their login page, the app
  may need a small update. Use `--show` to see where it stops.
- It logs in once a day, which is the same load as you opening the website.
