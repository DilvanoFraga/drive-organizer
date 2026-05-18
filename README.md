# Organizador Google Drive

Ferramenta para auditar, planejar e executar a reorganizacao do Google Drive pessoal.
Interface web via Streamlit + CLI para automacao.

---

## Funcionalidades

- **Audit** — lista tudo na raiz do Drive
- **Plan** — classifica os itens e mostra o que seria movido (sem executar)
- **Execute** — salva snapshot automatico e move os arquivos
- **Undo** — reverte qualquer execucao anterior pelo snapshot
- **Config** — edita regras de classificacao pela interface ou direto no config.yaml

---

## Instalacao

```bash
git clone https://github.com/DilvanoFraga/drive-organizer.git
cd drive-organizer
pip install -r requirements.txt
```

Coloque o `credentials.json` (OAuth2 Desktop) na raiz do projeto.

---

## Credencial Google

1. Acesse [console.cloud.google.com](https://console.cloud.google.com)
2. APIs & Services > Credentials > Create > OAuth 2.0 Client ID > Desktop App
3. Habilite a Google Drive API no projeto
4. Adicione sua conta em Publico-alvo > Usuarios de teste
5. Baixe o JSON e salve como `credentials.json`

---

## Interface web (recomendado)

```bash
streamlit run app.py
```

Abre no browser em `http://localhost:8501`

---

## CLI

```bash
python organizador_drive.py audit
python organizador_drive.py plan
python organizador_drive.py execute
python organizador_drive.py execute --yes
python organizador_drive.py undo
python organizador_drive.py undo --list
python organizador_drive.py undo --snapshot snapshots/snapshot_TIMESTAMP.json
```

---

## Estrutura

```
drive-organizer/
├── app.py                  # Interface Streamlit (v3)
├── organizador_drive.py    # CLI (v2)
├── config.yaml             # Regras de classificacao
├── requirements.txt        # Dependencias
├── snapshots/              # Historico para undo (gitignored)
└── README.md
```

---

## Personalizacao (config.yaml)

```yaml
pastas_ignoradas:
  - MinhaEmpresa

pasta_arquivo_morto: "Arquivo Morto"

regras:
  Financeiro:
    - nota fiscal
    - extrato
    - imposto
  Trabalho:
    - contrato
    - proposta
```

---

## Roadmap

- [x] v1.0 - script funcional com regras hardcoded
- [x] v1.1 - config.yaml externo
- [x] v2.0 - modo undo com snapshots
- [x] v3.0 - interface web Streamlit
- [ ] v4.0 - modo watch (monitoramento automatico da raiz)

---

## .gitignore

```
credentials.json
token_drive.json
plano_organizacao.json
erros_organizacao.json
erros_undo.json
snapshots/
```
