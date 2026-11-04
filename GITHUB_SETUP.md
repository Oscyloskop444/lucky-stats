# Running it on GitHub (no computer needed)

Once set up, GitHub runs the app every school-day morning, saves the number to
`lucky_numbers.csv` in your repository, and publishes the dashboard at
`https://<your-username>.github.io/lucky-stats/`. You can open that address on any device.

**The website is password-protected.** A GitHub Pages site can be opened by anyone who
has the link, even when the repository is private, and the dashboard contains your
classmates' names. So the published page is encrypted and only opens with a password
you choose. The names are never stored readable anywhere on GitHub: the class list is
kept as a secret.

---

## 1. Create the repository

Go to <https://github.com/new>, name it `lucky-stats`, and **don't** add a README.

**Public or private?**

| | Public | Private |
|---|---|---|
| GitHub Pages | free | needs GitHub Pro (free for students through the [GitHub Student Developer Pack](https://education.github.com/pack)) |
| Who can see `lucky_numbers.csv` | anyone (dates and numbers only, no names) | only you |
| Debug screenshots when something breaks | not kept (they can show grades) | kept for 3 days |

Both work. If you have Pro or the Student Pack, choose **private**. Otherwise, public is fine.

## 2. Upload the project

In a terminal, inside your `lucky-stats` folder (replace `<you>` with your GitHub username):

```
git init -b main
git add .
git status
```

Check that the list **does not** include `config.json` or `roster.csv`. The included
`.gitignore` keeps them out, but it's worth a look. Then:

```
git commit -m "Lucky number stats"
git remote add origin https://github.com/<you>/lucky-stats.git
git push -u origin main
```

Your existing `lucky_numbers.csv` goes up with it, so the history you already have is kept.

## 3. Add the secrets

In the repository, go to **Settings → Secrets and variables → Actions → New repository secret**.
Add each of these:

| Name | Value |
|---|---|
| `EDUVULCAN_LOGIN` | your eduVULCAN login |
| `EDUVULCAN_PASSWORD` | your eduVULCAN password |
| `DASHBOARD_PASSWORD` | **a new password** for opening the website. Don't reuse your eduVULCAN one. |
| `ROSTER_CSV` | the whole contents of your `roster.csv` (open it in a text editor, copy everything, paste) |
| `EDUVULCAN_STUDENT` | *(optional)* your name as shown on "Dostęp do Dziennika", same as `"student"` in `config.json` |

Nobody can read secrets back after saving them, and GitHub hides them in the logs.

## 4. Turn on the website

Go to **Settings → Pages**. Under *Build and deployment → Source*, choose **GitHub Actions**.

## 5. First run

Go to the **Actions** tab, click **Lucky number** on the left, then **Run workflow → Run workflow**.

It takes about 2–3 minutes. When the run turns green:

- the dashboard is at `https://<you>.github.io/lucky-stats/`. Enter your `DASHBOARD_PASSWORD`, and tick *Remember on this device* if you like.
- a new commit "Lucky number …" appears with today's number.

To fill in past days from GitHub, use **Run workflow** again and enter a date in
*"Optional: also try to download past days since this date"*.

## When it runs

- Monday–Friday at **06:47** (07:47 in summer time), with a safety run at **10:13** (11:13).
  The second run doesn't log in again if the first one already got the number.
- GitHub sometimes starts scheduled runs 10–30 minutes late when it's busy. That's normal.
- If a run fails, GitHub emails you. Open the run in the Actions tab to see where it stopped.

## Good to know

- **The first run is the real test.** GitHub's computers are in data centres abroad, and
  eduVULCAN might treat a login from there differently from your home. It might send a
  "new login" email, show a captcha, or block it. If the run fails with *"Login didn't go
  through"* even though the password is right, that's probably why. In that case, keep
  running it on your own computer (see README.md).
- **Summer holidays:** in a **public** repository, GitHub pauses scheduled runs after
  60 days without any new commits. In September, open the Actions tab and click
  **Enable workflow**.
- **Changed your eduVULCAN password?** Update the `EDUVULCAN_PASSWORD` secret.
- **New classmate or a correction to the class list?** Edit `ROSTER_CSV`. The page updates on the next run.
- **Changed `DASHBOARD_PASSWORD`?** Devices that "remembered" the old one will ask for the new password.
- **A day was missed?** Add it on your computer with `python lucky.py add 2026-11-05 12`,
  then run `git pull`, commit and push `lucky_numbers.csv`. Or edit the file directly on GitHub.
