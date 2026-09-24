"""O repo é público: nenhum arquivo versionado pode carregar dado de quem o mantém.

Os termos privados não aparecem aqui em forma nenhuma: só o sha256 de cada token (minúsculo).
A varredura tokeniza cada arquivo por [a-z0-9]+ e compara o hash de cada token e das junções de
2 e 3 tokens vizinhos (pega nome-composto e nome_composto). Padrões que não identificam ninguém
(home do superusuário, domínio interno, e-mail de provedor gratuito, id de card) ficam em regex.
Como acrescentar um termo: veja CONTRIBUTING.md.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# termos privados do mantenedor, guardados como hash de propósito
HASHES_PROIBIDOS = frozenset({
    "0b74ed7ff22b86fd0838fd29a78940a8d54377951e968867948a57b3e53646fc",
    "1768c21fc46884dfc50dda89562fca6d9eff9d714c30db4a5575ce849632fb61",
    "28c070eec721da66479d69cdaab279a29bf65b97da424adeebc8ed22f4167403",
    "2f55f3a6b96eae7c7d6fcfdb3e598ad237ed3729bfb480c668a24fe5f70d4c90",
    "339432fabfff77c9170b26713b73d598bf059c18998c1a64a59c085cfe145187",
    "3639f78bcf5e58956019df8ab707600b6a8a91dba060a8ff27571eb110f38a88",
    "3975a18c2114c4d05cf045572f1aa70fdecff1f999127a537d189765e990ae8b",
    "40b8eb616595529a0cf5eec61dac808be95ec05935c0612ff8d98ed66903a1a9",
    "51513da6478ceee16118ae665e7e2cb643ba6cb8189942081bb206a98de28fb7",
    "645e3597571c5c8bc2bd6ced66a307541af8f63eaad00ff658326400259435b5",
    "65595aae456fbdfb73fef280d62aa4b792259872cb09d630f5426ca9cb82a467",
    "65884f2219a4f49cf52f26a01cb28394f4f56f6fa25a5b497cd09e93ff4bc95b",
    "8575ce2731c3b4bd8e7ba88d9ce60986eda5b24b27f7012b4bab74eddbe6d894",
    "99bde068af2d49ed7fc8b8fa79abe13a6059e0db320bb73459fd96624bb4b33f",
    "9ae8534f8447b74bd4502f7f0d98887a031b539574680fd78df49caeab44c869",
    "9cc0b0748689efcfcbd2fff8008b8a31293ff0d69085b72ca12d2fd4043d6857",
    "aedd936cbb50c8c1db2cbfa0097d3257d86e05e7c97ee11cd48211871efdba89",
    "b30adb83fdd89156e4c16ee06413e0d83c61ce7a4655089c4a9ea933b5b1575d",
    "b98153dba40602eb218905d9e212938e4cb954fd70d9b2aed629c322263df41f",
    "c34cfa6a258d4e6871f7c3f9a10babcda2acab3ff5dac977afce59060a57600b",
    "ce10a4d16c976e19419b5ae798c686e39e7a33273514029c2c68388b7003c7c7",
    "e022135adc4807a1246ad14933477c398c7d57a3ebd95ae25386a47596d99bae",
    "fefaa42da40ecf93662a6f2852c1d4315ff7593420cd3538f6eaf6afee38f1a2",
})

# genéricos: não identificam ninguém. As classes de um caractere só existem pra este arquivo
# não acusar a si mesmo.
PADROES_GENERICOS = (
    re.compile(r"/ro[o]t/"),
    re.compile(r"[.]intern[a]l\b", re.IGNORECASE),
    re.compile(r"@(?:g[m]ail|hotm[a]il|outl[o]ok|yah[o]o|icl[o]ud|prot[o]n)", re.IGNORECASE),
    re.compile(r"\bT-[0-9a-f]{5}\b"),
)

# a licença leva o nome do titular por obrigação legal; é o único arquivo fora da varredura
ISENTOS = frozenset({"LICENSE"})


class VarreduraDePrivacidade:
    _TOKEN = re.compile(r"[a-z0-9]+")

    def __init__(self, raiz, hashes=HASHES_PROIBIDOS, padroes=PADROES_GENERICOS, isentos=ISENTOS):
        self._raiz = Path(raiz)
        self._hashes = frozenset(hashes)
        self._padroes = tuple(padroes)
        self._isentos = frozenset(isentos)

    def arquivos(self):
        saida = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=str(self._raiz), capture_output=True, text=True, check=True).stdout
        return [n for n in saida.splitlines() if n not in self._isentos and (self._raiz / n).is_file()]

    def achados(self):
        """Lista de 'arquivo:linha: motivo'. O motivo nunca repete o termo: só o prefixo do hash."""
        achados = []
        for nome in self.arquivos():
            dados = (self._raiz / nome).read_bytes()
            if b"\0" in dados:  # binario (imagem): texto privado nao mora ali
                continue
            texto = dados.decode("utf-8", errors="replace")
            for n, linha in enumerate(texto.splitlines(), 1):
                for motivo in self._motivos(linha):
                    achados.append("%s:%d: %s" % (nome, n, motivo))
        return achados

    def _motivos(self, linha):
        motivos = []
        if chr(0x2014) in linha:
            motivos.append("travessão")
        for padrao in self._padroes:
            if padrao.search(linha):
                motivos.append("padrão genérico %s" % padrao.pattern)
        tokens = self._TOKEN.findall(linha.lower())
        for i in range(len(tokens)):
            for largura in (1, 2, 3):
                pedaco = tokens[i:i + largura]
                if len(pedaco) < largura:
                    break
                resumo = hashlib.sha256("".join(pedaco).encode("utf-8")).hexdigest()
                if resumo in self._hashes:
                    motivos.append("termo privado (hash %s, %d token)" % (resumo[:8], largura))
        return motivos


class TestRepoLimpo(unittest.TestCase):
    def test_arquivos_versionados_estao_limpos(self):
        self.assertEqual(VarreduraDePrivacidade(RAIZ).achados(), [])


class TestVarredura(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.raiz = Path(self._tmp.name)
        subprocess.run(["git", "init", "-q"], cwd=str(self.raiz), check=True)
        self.extra = {hashlib.sha256(b"acmesecreto").hexdigest()}

    def _varrer(self, nome, conteudo, **kw):
        (self.raiz / nome).write_text(conteudo, encoding="utf-8")
        return VarreduraDePrivacidade(self.raiz, **kw).achados()

    def test_token_proibido_e_acusado(self):
        achados = self._varrer("a.txt", "linha limpa\nfalei do AcmeSecreto aqui\n", hashes=self.extra)
        self.assertEqual(len(achados), 1)
        self.assertTrue(achados[0].startswith("a.txt:2:"))
        self.assertNotIn("acmesecreto", achados[0].lower())

    def test_juncao_de_vizinhos_e_acusada(self):
        for texto in ("acme-secreto", "acme_secreto", "acme secreto", "a/acme/secreto.py"):
            self.assertEqual(len(self._varrer("b.txt", texto + "\n", hashes=self.extra)), 1, texto)

    def test_palavra_que_so_contem_o_termo_passa(self):
        self.assertEqual(self._varrer("c.txt", "acmesecretos e superacmesecreto\n", hashes=self.extra), [])

    def test_padroes_genericos(self):
        casos = ["/ro" "ot/x", "host.inter" "nal", "fulano@gm" "ail.com", "card T-" "0a1b2"]
        for texto in casos:
            self.assertEqual(len(self._varrer("d.txt", texto + "\n")), 1, texto)

    def test_binario_fica_fora(self):
        # bytes aleatorios de imagem casam hash de 2 tokens por acaso (docs/img/erratum.webp)
        (self.raiz / "e.webp").write_bytes(b"RIFF\x00\x01acmesecreto\n")
        self.assertEqual(VarreduraDePrivacidade(self.raiz, hashes=self.extra).achados(), [])

    def test_isento_fica_fora(self):
        self.assertEqual(self._varrer("LICENSE", "acmesecreto\n", hashes=self.extra), [])


if __name__ == "__main__":
    unittest.main()
