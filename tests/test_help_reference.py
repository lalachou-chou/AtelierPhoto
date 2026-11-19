"""The detailed reference shown in the help is the one published in docs/."""
from pathlib import Path

from PySide6.QtWidgets import QDialog, QTextBrowser

from atelier import help_ui
from atelier.help_reference import REFERENCE

DOCS = Path(__file__).resolve().parents[1] / "docs" / "FONCTIONNEMENT_DETAILLE.md"


def test_docs_copy_matches_the_in_app_reference():
    assert DOCS.read_text(encoding="utf-8") == REFERENCE.lstrip()


def test_reference_covers_every_part_of_the_application():
    for title in ("Principes et garanties", "Architecture et processus", "Formats et décodage",
                  "Analyse d'une photo", "Tri par scène", "Apprentissage du profil", "Rendu",
                  "clarté, courbe, TSL", "Retouches par consigne", "Recadrage", "Export", "XMP",
                  "pause et reprise", "récupération", "confidentialité", "Autodiagnostic", "Limites connues"):
        assert title in REFERENCE, title


def test_advanced_help_tab_includes_the_reference(qapp, monkeypatch):
    def inspect(dialog):
        text = dialog.findChild(QTextBrowser, "advancedHelp").toPlainText()
        assert "Fonctionnement détaillé" in text
        assert "pooler_output" in text and "MaskGroupBasedCorrections" in text
        assert "| --- |" not in text and "| Table |" not in text  # tables rendered, not raw Markdown
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", inspect)
    help_ui.show_help(None)
