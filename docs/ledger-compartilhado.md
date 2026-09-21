# Ledger compartilhado

Um banco por máquina serve todos os projetos: a coluna `project` separa as estatísticas, e a busca
por correção atravessa projetos de propósito. Erro resolvido num repositório é pista em outro.

Padrão: `~/.local/state/erratum/ledger.db`. Para mudar: variável `ERRATUM_DB`.

## Vários usuários ou agentes na mesma máquina

Numa VPS em que agentes rodam com usuários diferentes, ponha o banco num lugar comum:

```sh
sudo groupadd erratum
sudo usermod -aG erratum alice && sudo usermod -aG erratum agente
sudo install -d -m 2770 -g erratum /var/lib/erratum
echo 'ERRATUM_DB=/var/lib/erratum/ledger.db' | sudo tee -a /etc/environment
```

A permissão que importa é a do **diretório**: o SQLite em WAL cria `ledger.db-wal` e
`ledger.db-shm` ao lado do banco, e cada processo precisa criar e escrever nesses arquivos. O
`2770` (setgid) faz os arquivos novos herdarem o grupo; garanta `umask 002` para os usuários do
grupo, ou os arquivos nascem sem escrita para o grupo.

Serviço systemd não lê `/etc/environment`: declare `Environment=ERRATUM_DB=/var/lib/erratum/ledger.db`
no unit. No cron, ponha a variável no topo do crontab.

## O limite, com honestidade

SQLite em WAL aguenta vários processos escrevendo **na mesma máquina**. Ele depende de memória
compartilhada e de travas de arquivo do sistema operacional, então:

- **não** ponha o `.db` em NFS, SMB, Dropbox, Drive ou qualquer volume de rede ou sincronizado:
  corrompe, e corrompe calado;
- container enxerga o banco por bind mount do diretório inteiro (não só do arquivo), no mesmo host;
- entre máquinas não há sincronização. O `erratum import` lê um JSONL de **erros**
  (`{"ts","project","text"}`), mas hoje não existe um `export`, e correções não viajam por ele. Se
  você precisa de um ledger por time, o caminho de hoje é uma máquina comum onde os agentes rodam.

## Backup

Com o banco em uso, use a API de backup do SQLite, que copia um estado consistente:

```sh
python3 -c "
import sqlite3, sys
origem = sqlite3.connect(sys.argv[1]); destino = sqlite3.connect(sys.argv[2])
origem.backup(destino); destino.close(); origem.close()" "$ERRATUM_DB" /backup/ledger-$(date +%F).db
```

Com o binário instalado: `sqlite3 "$ERRATUM_DB" ".backup '/backup/ledger.db'"`. Cópia simples com
`cp` só é segura com todos os processos parados, e tem de levar junto o `-wal` e o `-shm`.

## Esquema

```
errors(id, ts, project, kind, stage, tool, signature, text, context_json, import_key)
fixes(id, ts, project, signature, note, ref, test, source, import_key)
wins(id, ts, project, task, what, cost_usd, context_json)
gate_runs(id, ts, project, gate, verdict, detail)
ledger_fts = fts5(signature, text, note, src)   -- índice de errors, fixes e sementes
```
