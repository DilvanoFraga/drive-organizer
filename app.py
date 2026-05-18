"""
app.py - Organizador Google Drive v3.0
Interface web Streamlit

Uso:
  streamlit run app.py
"""

import os
import sys
import json
import yaml
import glob
from datetime import datetime

import streamlit as st
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE       = "token_drive.json"
CONFIG_FILE      = "config.yaml"
SNAPSHOTS_DIR    = "snapshots"
SCOPES           = ["https://www.googleapis.com/auth/drive"]


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


@st.cache_data(ttl=60, show_spinner=False)
def listar_raiz_cached(_ts):
    service = st.session_state.service
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


def mover_arquivo(service, file_id, destino_id, origem_id):
    service.files().update(
        fileId=file_id,
        addParents=destino_id,
        removeParents=origem_id,
        fields="id, parents",
    ).execute()


def get_root_id(service):
    return service.files().get(fileId="root", fields="id").execute()["id"]


def carregar_config():
    if not os.path.exists(CONFIG_FILE):
        return {"pastas_ignoradas": [], "pasta_arquivo_morto": "Arquivo Morto", "regras": {}}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def salvar_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def salvar_snapshot(items, plano):
    os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(SNAPSHOTS_DIR, f"snapshot_{ts}.json")
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


def listar_snapshots():
    os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
    return sorted(glob.glob(os.path.join(SNAPSHOTS_DIR, "snapshot_*.json")), reverse=True)


# ─── UI ───────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Organizador Google Drive", page_icon="📁", layout="wide")
st.title("📁 Organizador Google Drive")

# Auth
if "service" not in st.session_state:
    if not os.path.exists(CREDENTIALS_FILE):
        st.error("credentials.json nao encontrado. Coloque o arquivo na pasta do projeto.")
        st.stop()
    with st.spinner("Conectando ao Google Drive..."):
        try:
            st.session_state.service  = autenticar()
            st.session_state.root_id  = get_root_id(st.session_state.service)
            st.session_state.cache_ts = datetime.now().isoformat()
        except Exception as e:
            st.error(f"Erro ao autenticar: {e}")
            st.stop()

service = st.session_state.service
st.success("Conectado ao Google Drive", icon="✅")

tab_audit, tab_plan, tab_execute, tab_undo, tab_config = st.tabs([
    "🔍 Audit", "🗺️ Plan", "⚙️ Execute", "↩️ Undo", "🛠️ Config"
])

# ─── AUDIT ────────────────────────────────────────────────────────────────────

with tab_audit:
    st.subheader("Conteudo atual da raiz do Drive")
    if st.button("🔄 Atualizar lista"):
        st.session_state.cache_ts = datetime.now().isoformat()
        st.cache_data.clear()

    cfg       = carregar_config()
    ignoradas = set(cfg.get("pastas_ignoradas", []))

    with st.spinner("Listando arquivos..."):
        items = listar_raiz_cached(st.session_state.cache_ts)

    pastas   = [i for i in items if i["mimeType"] == "application/vnd.google-apps.folder"]
    arquivos = [i for i in items if i["mimeType"] != "application/vnd.google-apps.folder"]

    c1, c2, c3 = st.columns(3)
    c1.metric("Total", len(items))
    c2.metric("Pastas", len(pastas))
    c3.metric("Arquivos soltos", len(arquivos))

    st.markdown("#### 📁 Pastas")
    for p in sorted(pastas, key=lambda x: x["name"]):
        tag = " 🔒" if p["name"] in ignoradas else ""
        st.write(f"- **{p['name']}**{tag}")

    st.markdown("#### 📄 Arquivos soltos")
    if arquivos:
        st.dataframe(
            [{"Nome": a["name"],
              "Tipo": a["mimeType"].split("/")[-1].replace("vnd.google-apps.", ""),
              "Modificado": a.get("modifiedTime", "")[:10]}
             for a in sorted(arquivos, key=lambda x: x["name"])],
            use_container_width=True, hide_index=True
        )

# ─── PLAN ─────────────────────────────────────────────────────────────────────

with tab_plan:
    st.subheader("Plano de organizacao")
    st.caption("Visualize como os itens serao classificados. Ajuste manualmente se necessario.")

    cfg       = carregar_config()
    regras    = cfg.get("regras", {})
    ignoradas = set(cfg.get("pastas_ignoradas", []))
    morto     = cfg.get("pasta_arquivo_morto", "Arquivo Morto")

    with st.spinner("Montando plano..."):
        items = listar_raiz_cached(st.session_state.cache_ts)

    if "plano" not in st.session_state:
        plano = {}
        for item in items:
            if item["name"] in ignoradas:
                continue
            destino = classificar(item["name"], regras, morto)
            plano.setdefault(destino, []).append(item)
        st.session_state.plano = plano
        st.session_state.items = items

    plano = st.session_state.plano

    # Resumo
    st.dataframe(
        [{"Destino": d, "Itens": len(v)} for d, v in sorted(plano.items())],
        use_container_width=True, hide_index=True
    )

    # Detalhe expansivel por destino
    for destino in sorted(plano.keys()):
        with st.expander(f"📁 {destino}  ({len(plano[destino])} itens)"):
            for i in sorted(plano[destino], key=lambda x: x["name"]):
                icone = "📁" if i["mimeType"] == "application/vnd.google-apps.folder" else "📄"
                st.write(f"{icone} {i['name']}")

    # Ajuste manual
    st.divider()
    st.markdown("#### Ajustar classificacao manualmente")
    todos = [(item["name"], item["id"], dest)
             for dest, lista in plano.items() for item in lista]
    opcoes = [f"{nome}  →  {dest}" for nome, _, dest in todos]

    sel = st.selectbox("Item", opcoes, key="sel_item_plan")
    if sel:
        idx       = opcoes.index(sel)
        item_id   = todos[idx][1]
        item_nome = todos[idx][0]
        dest_cur  = todos[idx][2]
        novo_dest = st.selectbox(
            "Mover para",
            sorted(plano.keys()),
            index=sorted(plano.keys()).index(dest_cur),
            key="novo_dest_plan"
        )
        if st.button("Aplicar ajuste"):
            plano[dest_cur] = [i for i in plano[dest_cur] if i["id"] != item_id]
            obj = next((i for i in items if i["id"] == item_id), None)
            if obj:
                plano.setdefault(novo_dest, []).append(obj)
                st.session_state.plano = plano
                st.success(f"'{item_nome}' → '{novo_dest}'")
                st.rerun()

    if st.button("🔄 Recalcular plano"):
        if "plano" in st.session_state:
            del st.session_state["plano"]
        st.rerun()

# ─── EXECUTE ──────────────────────────────────────────────────────────────────

with tab_execute:
    st.subheader("Executar organizacao")

    if "plano" not in st.session_state:
        st.warning("Gere o plano primeiro na aba Plan.")
    else:
        plano = st.session_state.plano
        items = st.session_state.items
        total = sum(len(v) for v in plano.values())

        st.info(f"Pronto para mover **{total} itens** para **{len(plano)} pastas**.")

        for dest, lista in sorted(plano.items()):
            st.write(f"- **{dest}**: {len(lista)} itens")

        st.divider()
        ok = st.checkbox("Revisei o plano e confirmo a execucao")

        if ok and st.button("▶️ Executar agora", type="primary"):
            snap_path = salvar_snapshot(items, plano)
            todos     = [(dest, item) for dest, lista in plano.items() for item in lista]
            progress  = st.progress(0, text="Iniciando...")
            erros     = []
            movidos   = 0

            for i, (dest, item) in enumerate(todos):
                try:
                    dest_id    = get_or_create_folder(service, dest)
                    origem_id  = item.get("parents", [st.session_state.root_id])[0]
                    mover_arquivo(service, item["id"], dest_id, origem_id)
                    movidos += 1
                except Exception as e:
                    erros.append({"item": item["name"], "erro": str(e)})

                progress.progress(int((i + 1) / len(todos) * 100),
                                  text=f"{i+1}/{len(todos)} — {item['name']}")

            st.cache_data.clear()
            st.session_state.cache_ts = datetime.now().isoformat()
            if "plano" in st.session_state:
                del st.session_state["plano"]
            progress.empty()

            if erros:
                st.error(f"{len(erros)} erros.")
                st.json(erros)
            else:
                st.success(f"✅ {movidos} itens movidos!")
                st.info(f"Snapshot: `{snap_path}` — use a aba Undo para reverter.")

# ─── UNDO ─────────────────────────────────────────────────────────────────────

with tab_undo:
    st.subheader("Reverter organizacao")

    snapshots = listar_snapshots()
    if not snapshots:
        st.info("Nenhum snapshot encontrado. Execute primeiro para poder reverter.")
    else:
        opcoes_snap = {}
        for path in snapshots:
            with open(path, "r", encoding="utf-8") as f:
                s = json.load(f)
            label = f"{s['timestamp']}  ({s['total_itens']} itens)"
            opcoes_snap[label] = (path, s)

        sel_snap       = st.selectbox("Snapshot", list(opcoes_snap.keys()))
        snap_path, snap_data = opcoes_snap[sel_snap]

        c1, c2 = st.columns(2)
        c1.write(f"**Data:** {snap_data['timestamp']}")
        c2.write(f"**Itens:** {snap_data['total_itens']}")

        with st.expander("Ver itens do snapshot"):
            for item in snap_data["itens"]:
                st.write(f"- {item['nome']}  →  `{item['destino']}`")

        st.divider()
        ok_undo = st.checkbox("Confirmo que quero reverter esta operacao")

        if ok_undo and st.button("↩️ Reverter agora", type="primary"):
            root_id  = st.session_state.root_id
            total_s  = len(snap_data["itens"])
            progress = st.progress(0, text="Revertendo...")
            erros    = []
            revertidos = 0

            for i, item in enumerate(snap_data["itens"]):
                try:
                    meta = service.files().get(
                        fileId=item["id"], fields="id, parents"
                    ).execute()
                    parent_atual    = meta.get("parents", [None])[0]
                    parent_original = item["parent_id"] if item["parent_id"] != "root" else root_id

                    if parent_atual != parent_original:
                        service.files().update(
                            fileId=item["id"],
                            addParents=parent_original,
                            removeParents=parent_atual,
                            fields="id, parents",
                        ).execute()
                        revertidos += 1
                except Exception as e:
                    erros.append({"item": item["nome"], "erro": str(e)})

                progress.progress(int((i + 1) / total_s * 100),
                                  text=f"{i+1}/{total_s} — {item['nome']}")

            st.cache_data.clear()
            st.session_state.cache_ts = datetime.now().isoformat()
            progress.empty()

            usado = snap_path.replace(".json", "_revertido.json")
            os.rename(snap_path, usado)

            if erros:
                st.error(f"{len(erros)} erros.")
                st.json(erros)
            else:
                st.success(f"✅ {revertidos} itens revertidos!")

# ─── CONFIG ───────────────────────────────────────────────────────────────────

with tab_config:
    st.subheader("Configuracao das regras")
    st.caption("Edite e salve. As mudancas atualizam config.yaml imediatamente.")

    cfg = carregar_config()

    st.markdown("#### Pastas ignoradas")
    ignoradas_txt = st.text_area(
        "Uma por linha (nome exato)",
        value="\n".join(cfg.get("pastas_ignoradas", [])),
        height=80, key="ignoradas_txt"
    )

    st.markdown("#### Pasta para itens sem classificacao")
    morto_input = st.text_input(
        "Nome", value=cfg.get("pasta_arquivo_morto", "Arquivo Morto"), key="morto_input"
    )

    st.markdown("#### Regras")
    regras = cfg.get("regras", {})
    novas_regras = {}

    for cat in list(regras.keys()):
        with st.expander(f"📁 {cat}"):
            col_a, col_b = st.columns([5, 1])
            txt = col_a.text_area(
                "Palavras-chave (uma por linha)",
                value="\n".join(regras[cat]),
                height=130, key=f"regra_{cat}"
            )
            remover = col_b.button("🗑️ Remover", key=f"rm_{cat}")
            if not remover:
                novas_regras[cat] = [p.strip() for p in txt.splitlines() if p.strip()]

    st.divider()
    st.markdown("#### Nova categoria")
    col_c, col_d = st.columns(2)
    nova_cat      = col_c.text_input("Nome", key="nova_cat")
    nova_palavras = col_d.text_area("Palavras-chave", height=100, key="nova_palavras")

    if st.button("➕ Adicionar"):
        if nova_cat and nova_cat not in novas_regras:
            novas_regras[nova_cat] = [p.strip() for p in nova_palavras.splitlines() if p.strip()]
            st.success(f"'{nova_cat}' adicionada.")

    st.divider()
    if st.button("💾 Salvar configuracao", type="primary"):
        salvar_config({
            "pastas_ignoradas":    [p.strip() for p in ignoradas_txt.splitlines() if p.strip()],
            "pasta_arquivo_morto": morto_input.strip(),
            "regras":              novas_regras,
        })
        st.cache_data.clear()
        if "plano" in st.session_state:
            del st.session_state["plano"]
        st.success("config.yaml atualizado!")
        st.rerun()
