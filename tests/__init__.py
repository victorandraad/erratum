# A suíte antiga afirma a saída em português: roda com ERRATUM_LANG=pt. O inglês padrão
# é coberto em test_idioma, que limpa a variável.
import os

os.environ["ERRATUM_LANG"] = "pt"
