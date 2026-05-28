# GitHub Profile Analyzer

CLI tool that fetches profile + repository data from the GitHub REST API, aggregates stats, prints formatted tables, and saves charts as PNG.

## Features

- **Profile** — name, bio, followers, following, account age
- **Repos** — total stars, forks, code size, stars-per-repo ratio
- **Top repos** — 5 most starred and 5 most forked repos
- **Languages** — byte-level breakdown across all repos (bar + pie chart)
- **Organizations** — displays orgs the user belongs to
- **Recent activity** — last 5 public events (pushes, PRs, issues)
- **Inactive repos** — repos untouched for >1 year
- **Charts saved as PNG**
  - `{username}_profile.png` — language distribution pie chart
  - `{username}_star_fork.png` — stars vs forks grouped bar chart

## Requirements

- Python 3.9+
- Dependencies: `requests`, `matplotlib`, `rich`

## Installation

```bash
# Clone or download the repo, then:
pip install -r requirements.txt
```

## Usage

```bash
# Basic usage (unauthenticated — 60 requests/hour)
python app.py --username torvalds

# With a personal access token (5000 requests/hour)
python app.py --username torvalds --token ghp_xxxxxxxxxxxx

# Or set the token as an environment variable
export GITHUB_TOKEN=ghp_xxxxxxxxxxxx
python app.py --username torvalds
```

> **Tip:** Get a free token at https://github.com/settings/tokens (no scopes needed for public data).

## Example Output

```
GitHub Profile - torvalds

  Metric                 Value
 ──────────────────────────────────────────────
  Name                   Linus Torvalds
  Bio                    Founder & CEO of ...
  Followers              220000+
  Following              0
  Public repos           6
  Member since           2011-09-07
  Account age            14.7 years (5378 days)

  Repository stats
    Repos fetched        6
    Total stars          210000+
    Total forks          50000+
    ...
  Top 5 repos by stars
    1. linux              * 180000 stars ...
    2. ...
```

Two PNG charts are saved in the current directory.

## Project Structure

```
GitHub Profile Analyzer/
  app.py              # Main CLI tool
  test_app.py         # Unit tests (49 tests, no external deps)
  requirements.txt    # Python dependencies
  README.md           # This file
```

## Running Tests

```bash
python test_app.py
```

All 49 tests run offline (no API calls). They mock network responses to verify every code path — API error handling, pagination, table rendering, chart generation, and CLI argument parsing.

## GitHub Upload

Upload these **3 files** via drag-and-drop:

| File | Purpose |
|------|---------|
| `app.py` | Main analyzer script |
| `requirements.txt` | Dependency list |
| `README.md` | Documentation |

Optional but recommended: `test_app.py` for test suite.
