#!/bin/bash
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
  atelier_python="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  atelier_python="$(command -v python)"
else
  echo "Installez Python 3.12, 3.13 ou 3.14 en suivant LIRE SUR MAC.md."
  if [ -t 0 ]; then read -r -p "Appuyez sur Entrée pour fermer."; fi
  exit 1
fi
"$atelier_python" scripts/macos_builder.py
atelier_status=$?
if [ -t 0 ]; then
  if [ "$atelier_status" -ne 0 ]; then echo "Construction en échec : conservez les messages ci-dessus."; fi
  read -r -p "Appuyez sur Entrée pour fermer."
fi
exit "$atelier_status"
