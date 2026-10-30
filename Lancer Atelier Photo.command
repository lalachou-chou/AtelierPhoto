#!/bin/bash
cd "$(dirname "$0")" || exit 1
source scripts/macos_python.sh || exit 1
if ! atelier_python="$(atelier_find_python)"; then
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
