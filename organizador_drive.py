"""
organizador_drive.py - v2.0
Organiza o Google Drive com regras definidas em config.yaml.

Modos:
  audit           - lista tudo na raiz
  plan            - mostra o que seria feito
  execute         - tira snapshot e aplica o plano
  execute --yes   - executa sem confirmacao
  undo            - reverte o ultimo execute
  undo --list     - lista snapshots disponiveis
  undo --snapshot snapshots/snapshot_TIMESTAMP.json

Arquivos necessarios:
  credentials.json  - OAuth2 Desktop
  config.yaml       - regras editaveis
"""

import os
import sys
import json
import yaml
import glob
from datetime import datetime
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE       = "token_drive.json"
CONFIG_FILE      = "config.yaml"
SNAPSHOTS_DIR    = "snapshots"
SCOPES           = ["https://www.googleapis.com/auth/drive"]


def carregar_config(path=CONFIG_FILE):
    if not os.path.exists(path):
        print(f"ERRO: {path} nao encontrado.")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def autenticar():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return build("drive", "v3", credentials=creds)


def listar_raiz(service):
    items, page_token = [], None
    while True:
        resp = service.files().list(
            q="'root' in parents and trashed=false",
            spaces="drive",
            fields="nextPageToken, files(id, name, mimeType, modifiedTime, parents)",
            pageToken=page_token,
            pageSize=1000,
        ).execute()
        items.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return items


def classificar(nome, regras, pasta_morto):
    nome_lower = nome.lower()
    for destino, palavras in regras.items():
        if any(p.lower() in nome_lower for p in palavras):
            return destino
    return pasta_morto


def get_or_create_folder(service, nome):
    q = (
        f"name='{nome}' and mimeType='application/vnd.google-apps.folder' "
        f"and 'root' in parents and trashed=false"
    )
    resp = service.files().list(q=q, spaces="drive", fields="files(id)").execute()
    files = resp.get("files", [])
    if files:
        return files[0]["id"]
    meta = {"name": nome, "mimeType": "application/vnd.google-apps.folder"}
    return service.files().create(body=meta, fields="id").execute()["id"]


def mover_arquivo(service, file_id, destino_id, origem_id="root"):
    service.files().update(
        fileId=file_id,
        addParents=destino_id,
        removeParents=origem_id,
        fields="id, parents",
    ).execute()


def get_root_id(service):
    return service.files().get(fileId="root", fields="id").execute()["id"]


def salvar_snapshot(items, plano, snapshots_dir=SNAPSHOTS_DIR):
    os.makedirs(snapshots_dir, exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(snapshots_dir, f"snapshot_{ts}.json")
    items_map = {i["id"]: i for i in items}
    registros = []
    for destino, itens_destino in plano.items():
        for item in itens_destino:
            original = items_map.get(item["id"], item)
            registros.append({
                "id":        item["id"],
                "nome":      item["name"],
                "mimeType":  item["mimeType"],
                "parent_id": original.get("parents", ["root"])[0],
                "destino":   destino,
            })
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"timestamp": ts, "total_itens": len(registros), "itens": registros},
                  f, ensure_ascii=False, indent=2)
    return path


def listar_snapshots(snapshots_dir=SNAPSHOTS_DIR):
    os.makedirs(snapshots_dir, exist_ok=True)
    return sorted(glob.glob(os.path.join(snapshots_dir, "snapshot_*.json")), reverse=True)


def carregar_snapshot(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def montar_plano(items, cfg):
    regras    = cfg.get("regras", {})
    ignoradas = set(cfg.get("pastas_ignoradas", []))
    morto     = cfg.get("pasta_arquivo_morto", "Arquivo Morto")
    plano = {}
    for item in items:
        if item["name"] in ignoradas:
            continue
        destino = classificar(item["name"], regras, morto)
        plano.setdefault(destino, []).append(item)
    return plano


def modo_audit(service, cfg):
    print("\nAUDIT -- Conteudo atual da raiz do Drive\n")
    items     = listar_raiz(service)
    pastas    = [i for i in items if i["mimeType"] == "application/vnd.google-apps.folder"]
    arquivos  = [i for i in items if i["mimeType"] != "application/vnd.google-apps.folder"]
    ignoradas = set(cfg.get("pastas_ignoradas", []))

    print(f"{'─'*60}\n  Pastas ({len(pastas)})\n{'─'*60}")
    for p in sorted(pastas, key=lambda x: x["name"]):
        tag = "  [ignorada]" if p["name"] in ignoradas else ""
        print(f"  {p['name']}{tag}")

    print(f"\n{'─'*60}\n  Arquivos soltos ({len(arquivos)})\n{'─'*60}")
    for a in sorted(arquivos, key=lambda x: x["name"]):
        tipo = a["mimeType"].split("/")[-1].replace("vnd.google-apps.", "")
        print(f"  {a['name']}  ({tipo})")

    print(f"\n  Total: {len(items)} | {len(pastas)} pastas | {len(arquivos)} arquivos soltos\n")
    return items


def modo_plan(service, cfg):
    print("\nPLAN -- O que sera feito (sem executar nada)\n")
    items = listar_raiz(service)
    plano = montar_plano(items, cfg)

    total = 0
    for destino in sorted(plano.keys()):
        lista = plano[destino]
        print(f"  {destino}  ({len(lista)} itens)")
        for i in sorted(lista, key=lambda x: x["name"]):
            tipo = "[pasta]" if i["mimeType"] == "application/vnd.google-apps.folder" else "[arq]  "
            print(f"      {tipo}  {i['name']}")
        total += len(lista)
        print()

    print(f"  Total: {total} movimentos | Destinos: {sorted(plano.keys())}\n")

    with open("plano_organizacao.json", "w", encoding="utf-8") as f:
        json.dump(
            {d: [{"id": i["id"], "nome": i["name"]} for i in v] for d, v in plano.items()},
            f, ensure_ascii=False, indent=2
        )
    print("  Plano salvo em plano_organizacao.json\n")
    return plano, items


def modo_execute(service, cfg, auto_confirm=False):
    print("\nEXECUTE -- Aplicando organizacao\n")
    plano, items = modo_plan(service, cfg)

    if not auto_confirm:
        if input("  Confirma a execucao? (s/N): ").strip().lower() != "s":
            print("  Operacao cancelada.\n")
            return

    snapshot_path = salvar_snapshot(items, plano)

    erros, movidos = [], 0
    for destino, itens in plano.items():
        print(f"\n  Pasta '{destino}'...")
        try:
            destino_id = get_or_create_folder(service, destino)
        except Exception as e:
            erros.append({"item": destino, "erro": str(e)})
            print(f"    ERRO ao criar pasta: {e}")
            continue

        for item in itens:
            try:
                mover_arquivo(service, item["id"], destino_id)
                tipo = "[pasta]" if item["mimeType"] == "application/vnd.google-apps.folder" else "[arq]  "
                print(f"    OK {tipo} {item['name']}")
                movidos += 1
            except Exception as e:
                erros.append({"item": item["name"], "erro": str(e)})
                print(f"    ERRO '{item['name']}': {e}")

    print()
    if erros:
        print(f"  {len(erros)} erros. Salvo em erros_organizacao.json")
        with open("erros_organizacao.json", "w", encoding="utf-8") as f:
            json.dump(erros, f, ensure_ascii=False, indent=2)
    else:
        print(f"  Concluido! {movidos} itens movidos.")

    print(f"  Para reverter: python organizador_drive.py undo")
    print(f"  Snapshot: {snapshot_path}\n")


def modo_undo(service, snapshot_path=None):
    print("\nUNDO -- Revertendo organizacao\n")

    if snapshot_path:
        if not os.path.exists(snapshot_path):
            print(f"  ERRO: snapshot nao encontrado: {snapshot_path}")
            sys.exit(1)
    else:
        snapshots = listar_snapshots()
        if not snapshots:
            print("  Nenhum snapshot encontrado.\n")
            sys.exit(1)
        snapshot_path = snapshots[0]
        print(f"  Usando snapshot mais recente: {snapshot_path}\n")

    snap    = carregar_snapshot(snapshot_path)
    root_id = get_root_id(service)

    print(f"  Snapshot: {snap['timestamp']} | Itens: {snap['total_itens']}\n")

    erros, revertidos = [], 0
    for item in snap["itens"]:
        try:
            meta = service.files().get(fileId=item["id"], fields="id, parents").execute()
        except Exception as e:
            erros.append({"item": item["nome"], "erro": str(e)})
            continue

        parent_atual    = meta.get("parents", [None])[0]
        parent_original = item["parent_id"] if item["parent_id"] != "root" else root_id

        if parent_atual == parent_original:
            continue

        try:
            service.files().update(
                fileId=item["id"],
                addParents=parent_original,
                removeParents=parent_atual,
                fields="id, parents",
            ).execute()
            revertidos += 1
        except Exception as e:
            erros.append({"item": item["nome"], "erro": str(e)})

    print()
    if erros:
        print(f"  {len(erros)} erros.")
        with open("erros_undo.json", "w", encoding="utf-8") as f:
            json.dump(erros, f, ensure_ascii=False, indent=2)
    else:
        print(f"  Undo concluido! {revertidos} itens revertidos.")

    usado = snapshot_path.replace(".json", "_revertido.json")
    os.rename(snapshot_path, usado)
    print(f"  Snapshot marcado como usado: {usado}\n")


def modo_undo_list():
    snapshots = listar_snapshots()
    if not snapshots:
        print("\n  Nenhum snapshot encontrado.\n")
        return
    print(f"\n  Snapshots disponiveis ({len(snapshots)}):\n")
    for i, path in enumerate(snapshots):
        snap = carregar_snapshot(path)
        tag  = " [mais recente]" if i == 0 else ""
        print(f"  [{i+1}] {path}")
        print(f"       Data: {snap['timestamp']} | Itens: {snap['total_itens']}{tag}\n")


def main():
    modos_validos = {"audit", "plan", "execute", "undo"}
    if len(sys.argv) < 2 or sys.argv[1] not in modos_validos:
        print("Uso:")
        print("  python organizador_drive.py audit")
        print("  python organizador_drive.py plan")
        print("  python organizador_drive.py execute [--yes]")
        print("  python organizador_drive.py undo")
        print("  python organizador_drive.py undo --list")
        print("  python organizador_drive.py undo --snapshot snapshots/snapshot_TIMESTAMP.json")
        sys.exit(1)

    modo         = sys.argv[1]
    auto_confirm = "--yes" in sys.argv

    if modo == "undo" and "--list" in sys.argv:
        modo_undo_list()
        return

    for arquivo in [CREDENTIALS_FILE, CONFIG_FILE]:
        if not os.path.exists(arquivo):
            print(f"ERRO: {arquivo} nao encontrado.")
            sys.exit(1)

    cfg = carregar_config()
    print("Autenticando...")
    service = autenticar()
    print("Conectado ao Google Drive\n")

    if modo == "audit":
        modo_audit(service, cfg)
    elif modo == "plan":
        modo_plan(service, cfg)
    elif modo == "execute":
        modo_execute(service, cfg, auto_confirm)
    elif modo == "undo":
        snap = None
        if "--snapshot" in sys.argv:
            idx  = sys.argv.index("--snapshot")
            snap = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
        modo_undo(service, snap)


if __name__ == "__main__":
    main()
