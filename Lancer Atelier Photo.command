#!/bin/bash
cd "$(dirname "$0")" || exit 1
if [ -x /opt/homebrew/bin/python3.12 ]; then
  atelier_python=/opt/homebrew/bin/python3.12
elif command -v python3.12 >/dev/null 2>&1; then
  atelier_python="$(command -v python3.12)"
else
  echo "Python 3.12 manque. Suivez LIRE SUR MAC.md, puis relancez ce fichier."
  if [ -t 0 ]; then read -r -p "Appuyez sur Entrée pour fermer."; fi
  exit 1
fi
"$atelier_python" scripts/start_macos.py "$@"
atelier_status=$?
if [ "$atelier_status" -ne 0 ] && [ -t 0 ]; then
  echo "Le lancement a échoué. Conservez le message ci-dessus pour le diagnostic."
  read -r -p "Appuyez sur Entrée pour fermer."
fi
exit "$atelier_status"
