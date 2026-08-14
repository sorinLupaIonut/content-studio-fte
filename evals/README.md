# Setul de evaluare — Decizia 10

`cazuri.json` ține cele douăsprezece cazuri urâte din §5 al planului și trei
trigger evals. Fiecare are conversația și comportamentul corect unul lângă altul.

Runnerul folosește worker-ul real, skill-urile reale în E2B și serverul MCP real:

```bash
uv run python -m mcp_server.server
uv run python evals/ruleaza.py
```

Poți rula un singur caz sau numai verificările complet automate:

```bash
uv run python evals/ruleaza.py --id 8
uv run python evals/ruleaza.py --doar-automat
```

Rezultatul detaliat ajunge în `evals/raport-latest.json` (ignorat de Git). Cele
marcate `cu_ochiul` sunt rulate și verificate mecanic unde se poate, dar vocea și
judecata se citesc din `raspuns_final`. Cazul 11 rămâne explicit `amanat` până
există capabilitatea Internet; runnerul nu maschează lipsa ei.

În evaluări, `save_postare` și `update_profil` sunt întotdeauna respinse la
poartă. Setul nu lasă postări sau schimbări de profil în urmă.
