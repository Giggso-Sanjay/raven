# Vibe-coder picture map (0% code required)

You do **not** need to understand code. You need a **picture** of how the app is wired: login, security, database, screens, money…

## One-time: open the map

```bash
cd /path/to/raven-or-project
python3 scripts/dashboard.py --html --open
```

Opens **`~/RavenVault/dashboard.html`** — tokenomics **and** knowledge graph with icons.

Look for:

1. **Picture dictionary** — icons with plain English  
2. **Colored chips** — your apps  
3. **Picture map** — boxes with icons; click any  
4. **List under the map** — same boxes as buttons  


## What the icons mean

| Icon idea | Means |
|-----------|--------|
| 📦 project | Whole app / repo |
| 💡 concept | A system piece (login, DB…) |
| ✅ decision | A choice we locked in |
| ⏱️ session | One day of work |
| 🔐 login | Auth / passwords / SSO |
| 🛡️ security | Guards, secrets, CVE |
| 🗄️ database | Data store |
| 🔌 api | Backend APIs |
| 🖥️ ui | Screens / reports |
| 💳 money | Payments / cards |
| ☁️ cloud | Deploy / cloud |
| 🔄 workflow | Pipelines / flow |
| 💻 code | Module / scripts |
| ❓ unknown | Not labeled yet |

Icons ship in `assets/kg-icons/*.svg` (tiny files, offline).

---

## How to grow the map (you only talk)

Paste this to Claude in the **app repo** you care about:

```text
Vibe-coder map mode. I do not read code well.

1) Update ~/RavenVault/projects/{this-repo}.md Current state in 5 plain bullets.
2) Create concept notes under ~/RavenVault/concepts/ with YAML frontmatter:
   type: concept
   project: {this-repo}
   icon: login | security | database | api | ui | money | cloud | workflow | code | data
   Each note: 3 bullets what it does + [[projects/{this-repo}]] + links to related concepts.
3) Use emoji in the title if helpful (🔐 Login).
4) Run:
   python3 /path/to/raven/scripts/knowledge_graph.py
   python3 /path/to/raven/scripts/dashboard.py --html --open
```

Then **only look at the picture**. Click login → security → database to “walk” the system.

---

## Daily loop (stupid simple)

1. Work (vibe).  
2. End of day: rebuild dashboard command above.  
3. Lost? Open dashboard → click the **icon** that matches what you’re scared of (login, DB, money…).  
4. Want code? Click **Local 📁** or **GitHub** only when ready.

---

## Agent memory (why this helps next chat)

Next session, Raven loads a short digest of hub + open questions + last sessions — same notes the map uses.  
Your picture **is** the memory, not a separate PowerPoint.

---

*Shipped with Raven assets/kg-icons + dashboard legend.*
