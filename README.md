# Curious Coffee — Fan-Made Landing Page

A landing page for [Curious Coffee](https://www.curious-coffee.com), Ann Arbor, MI.  
Coffee cards auto-update daily by scraping the live Wix shop.

---

## Setup (one time, ~5 minutes)

### 1. Create a GitHub repository

1. Go to [github.com](https://github.com) and sign in (or create a free account)
2. Click **New repository** (the green button)
3. Name it: `curious-coffee` (or anything you like)
4. Set it to **Public**
5. Do NOT check "Add a README" — we already have one
6. Click **Create repository**

### 2. Upload the files

On your new empty repo page, click **uploading an existing file** and drag in:

```
index.html
update_coffees.py
README.md
.github/
  workflows/
    update-coffees.yml
```

Or use the command line:

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/curious-coffee.git
git push -u origin main
```

### 3. Enable GitHub Pages (deploy the site)

1. Go to your repo on GitHub
2. Click **Settings** → **Pages** (left sidebar)
3. Under **Source**, select **Deploy from a branch**
4. Choose **main** branch, **/ (root)** folder
5. Click **Save**
6. Your site will be live at: `https://YOUR_USERNAME.github.io/curious-coffee/`

(Takes about 1-2 minutes the first time.)

### 4. Enable Actions permissions

GitHub Actions needs permission to commit the updated `index.html` back to the repo.

1. Go to **Settings** → **Actions** → **General**
2. Scroll to **Workflow permissions**
3. Select **Read and write permissions**
4. Click **Save**

That's it. The automation is now active.

---

## How the automation works

Every day at **6pm EST**, GitHub Actions runs `update_coffees.py` which:

1. Scrapes `curious-coffee.com` for all coffee products
2. Checks each product page for name, price, stock status, images, and description
3. Rebuilds the coffee card grid in `index.html`
4. Sorts cards: **in-stock first**, then out-of-stock
5. Commits the updated `index.html` back to the repo
6. GitHub Pages automatically redeploys the updated site

If nothing changed on the Wix shop, no commit is made.

---

## Triggering a manual update

You can trigger the scraper at any time (no need to wait for 6pm):

1. Go to your repo on GitHub
2. Click **Actions** tab
3. Click **Update Coffee Cards** in the left sidebar
4. Click **Run workflow** → **Run workflow**

---

## Updating the category map

If a new coffee is added to the site and you want it labelled **Standard** instead of the default **Premium**, edit `update_coffees.py` and add its URL slug to `CATEGORY_MAP`:

```python
CATEGORY_MAP = {
    "new-coffee-slug": "standard",
    # ...
}
```

Commit the change and it will apply on the next run.

---

## Video background

The coffee bean video is not included in the repo (too large for GitHub).  
To enable it:

1. Download from [Pexels](https://www.pexels.com/video/close-up-of-falling-coffee-beans-8608580/)
2. Create a `video/` folder in the repo
3. Save as `video/coffee-beans.mp4`
4. Commit and push

Other video options are listed in the `<!-- VIDEO OPTIONS -->` comment inside `index.html`.

---

## File structure

```
/
├── index.html              ← landing page (auto-updated daily)
├── update_coffees.py       ← scraper script
├── README.md               ← this file
└── .github/
    └── workflows/
        └── update-coffees.yml   ← daily automation schedule
```
