#!/bin/bash
cd "$(dirname "$0")" || exit 1
source scripts/macos_python.sh || exit 1
if ! atelier_python="$(atelier_find_python)"; then
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
