# Shared interpreter discovery for the two Mac launchers (Bash 3 compatible).
atelier_python_supported() {
  "$1" -c 'import platform, sys; sys.exit(0 if sys.platform == "darwin" and platform.machine() == "arm64" and (3, 12) <= sys.version_info[:2] <= (3, 14) else 1)' >/dev/null 2>&1
}

atelier_find_python() {
  if [ -n "${ATELIER_PYTHON:-}" ]; then
    if atelier_python_supported "$ATELIER_PYTHON"; then
      printf '%s\n' "$ATELIER_PYTHON"
      return 0
    fi
    echo "ATELIER_PYTHON doit désigner un Python macOS arm64 3.12, 3.13 ou 3.14." >&2
    return 1
  fi
  for atelier_candidate in \
    "./.venv/bin/python" \
    python3.14 python3.13 python3.12 python3 python \
    /opt/homebrew/bin/python3.14 /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3 \
    /usr/local/bin/python3.14 /usr/local/bin/python3.13 /usr/local/bin/python3.12 /usr/local/bin/python3 \
    /Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14 \
    /Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13 \
    /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12; do
    if atelier_python_supported "$atelier_candidate"; then
      printf '%s\n' "$atelier_candidate"
      return 0
    fi
  done
  echo "Python macOS arm64 3.12, 3.13 ou 3.14 introuvable. Consultez les instructions d’installation Python dans README.md." >&2
  return 1
}
