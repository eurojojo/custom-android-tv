#!/bin/sh
# Zet de TheTVDB-sleutel (en optioneel een PIN) in secrets.json zonder dat ze op het scherm of in de shell-geschiedenis komen.
# Gebruik (in ~/services/tvfeed):   sh set-tvdb-key.sh
set -e
cd "$(dirname "$0")"
printf "TheTVDB API-sleutel (onzichtbaar typen of plakken, dan Enter): "
stty -echo; read -r KEY; stty echo; echo
printf "TheTVDB PIN (alleen als je een abonnee-PIN hebt; anders gewoon Enter): "
stty -echo; read -r PIN; stty echo; echo
TVDB_KEY="$KEY" TVDB_PIN="$PIN" python3 - <<'PY'
import json, os
p = "secrets.json"
d = json.load(open(p))
d["tvdb_key"] = os.environ["TVDB_KEY"].strip()
if os.environ.get("TVDB_PIN", "").strip():
    d["tvdb_pin"] = os.environ["TVDB_PIN"].strip()
open(p, "w").write(json.dumps(d))
os.chmod(p, 0o600)
print("opgeslagen; velden:", sorted(d.keys()))
PY
rm -f out/art/*.none out/cards/lib-*.jpg
docker compose restart tvfeed
echo "klaar: de kaarten van films en series worden opnieuw gemaakt (duurt een halve minuut)"
