"""
tests/test_organizador.py
Suite de testes para organizador_drive.py

Cobertura:
  - Unitarios: classificar, carregar_config, montar_plano, salvar/carregar snapshot
  - Mock API: listar_raiz, get_or_create_folder, mover_arquivo, get_root_id

Rodar:
  pytest tests/ -v
  pytest tests/ -v --tb=short         # traceback resumido
  pytest tests/ -v --co               # lista testes sem rodar
"""

import os
import json
import tempfile
import pytest
from unittest.mock import MagicMock, patch, call

# Importa funcoes a testar
from organizador_drive import (
    classificar,
    carregar_config,
    montar_plano,
    salvar_snapshot,
    carregar_snapshot,
    listar_snapshots,
    get_or_create_folder,
    mover_arquivo,
    get_root_id,
    listar_raiz,
)

# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def cfg_basico():
    return {
        "pastas_ignoradas": ["PromovaWeb"],
        "pasta_arquivo_morto": "Arquivo Morto",
        "regras": {
            "Carreira":  ["curriculo", "cv"],
            "Faculdade": ["aula", "tcc", "banco de dados"],
            "Pessoal":   ["cpf", "carro", "treino"],
        }
    }


@pytest.fixture
def items_exemplo():
    return [
        {"id": "id1", "name": "Curriculo.pdf",      "mimeType": "application/pdf",                       "parents": ["root"]},
        {"id": "id2", "name": "Aula de Python",     "mimeType": "application/vnd.google-apps.folder",    "parents": ["root"]},
        {"id": "id3", "name": "Foto pessoal.jpg",   "mimeType": "image/jpeg",                            "parents": ["root"]},
        {"id": "id4", "name": "PromovaWeb",         "mimeType": "application/vnd.google-apps.folder",    "parents": ["root"]},
        {"id": "id5", "name": "Treino PPL.docx",    "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "parents": ["root"]},
        {"id": "id6", "name": "Banco de dados.pdf", "mimeType": "application/pdf",                       "parents": ["root"]},
    ]


@pytest.fixture
def service_mock():
    """Mock completo do googleapiclient service."""
    return MagicMock()


# ─── Testes: classificar() ────────────────────────────────────────────────────

class TestClassificar:

    def test_bate_primeira_regra(self, cfg_basico):
        regras = cfg_basico["regras"]
        assert classificar("meu curriculo 2024.pdf", regras, "Arquivo Morto") == "Carreira"

    def test_case_insensitive(self, cfg_basico):
        regras = cfg_basico["regras"]
        assert classificar("CURRICULO.PDF", regras, "Arquivo Morto") == "Carreira"

    def test_substring_no_nome(self, cfg_basico):
        regras = cfg_basico["regras"]
        assert classificar("banco de dados resumo.pdf", regras, "Arquivo Morto") == "Faculdade"

    def test_sem_match_vai_para_arquivo_morto(self, cfg_basico):
        regras = cfg_basico["regras"]
        assert classificar("foto_viagem.jpg", regras, "Arquivo Morto") == "Arquivo Morto"

    def test_pasta_morto_customizada(self, cfg_basico):
        regras = cfg_basico["regras"]
        assert classificar("qualquercoisa.txt", regras, "Lixo") == "Lixo"

    def test_regras_vazias_vai_para_morto(self):
        assert classificar("arquivo.txt", {}, "Arquivo Morto") == "Arquivo Morto"

    def test_multiplas_palavras_chave_primeira_bate(self, cfg_basico):
        regras = cfg_basico["regras"]
        # "tcc" bate em Faculdade
        assert classificar("tcc_final.pdf", regras, "Arquivo Morto") == "Faculdade"

    def test_treino_vai_para_pessoal(self, cfg_basico):
        regras = cfg_basico["regras"]
        assert classificar("Treino PPL.docx", regras, "Arquivo Morto") == "Pessoal"


# ─── Testes: carregar_config() ────────────────────────────────────────────────

class TestCarregarConfig:

    def test_carrega_yaml_valido(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "pastas_ignoradas:\n  - PromovaWeb\n"
            "pasta_arquivo_morto: 'Arquivo Morto'\n"
            "regras:\n  Carreira:\n    - curriculo\n",
            encoding="utf-8"
        )
        cfg = carregar_config(str(cfg_file))
        assert cfg["pasta_arquivo_morto"] == "Arquivo Morto"
        assert "PromovaWeb" in cfg["pastas_ignoradas"]
        assert "curriculo" in cfg["regras"]["Carreira"]

    def test_arquivo_inexistente_chama_sys_exit(self, tmp_path):
        with pytest.raises(SystemExit):
            carregar_config(str(tmp_path / "naoexiste.yaml"))

    def test_config_com_multiplas_categorias(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "pastas_ignoradas: []\n"
            "pasta_arquivo_morto: 'Morto'\n"
            "regras:\n"
            "  Cat1:\n    - palavra1\n"
            "  Cat2:\n    - palavra2\n",
            encoding="utf-8"
        )
        cfg = carregar_config(str(cfg_file))
        assert len(cfg["regras"]) == 2
        assert "Cat1" in cfg["regras"]
        assert "Cat2" in cfg["regras"]


# ─── Testes: montar_plano() ───────────────────────────────────────────────────

class TestMontarPlano:

    def test_ignora_pasta_ignorada(self, cfg_basico, items_exemplo):
        plano = montar_plano(items_exemplo, cfg_basico)
        # PromovaWeb deve estar ausente
        todos_nomes = [i["name"] for lista in plano.values() for i in lista]
        assert "PromovaWeb" not in todos_nomes

    def test_curriculo_vai_para_carreira(self, cfg_basico, items_exemplo):
        plano = montar_plano(items_exemplo, cfg_basico)
        nomes_carreira = [i["name"] for i in plano.get("Carreira", [])]
        assert "Curriculo.pdf" in nomes_carreira

    def test_aula_vai_para_faculdade(self, cfg_basico, items_exemplo):
        plano = montar_plano(items_exemplo, cfg_basico)
        nomes_faculdade = [i["name"] for i in plano.get("Faculdade", [])]
        assert "Aula de Python" in nomes_faculdade

    def test_sem_match_vai_para_arquivo_morto(self, cfg_basico, items_exemplo):
        plano = montar_plano(items_exemplo, cfg_basico)
        nomes_morto = [i["name"] for i in plano.get("Arquivo Morto", [])]
        assert "Foto pessoal.jpg" in nomes_morto

    def test_treino_vai_para_pessoal(self, cfg_basico, items_exemplo):
        plano = montar_plano(items_exemplo, cfg_basico)
        nomes_pessoal = [i["name"] for i in plano.get("Pessoal", [])]
        assert "Treino PPL.docx" in nomes_pessoal

    def test_total_itens_sem_ignorados(self, cfg_basico, items_exemplo):
        plano = montar_plano(items_exemplo, cfg_basico)
        total = sum(len(v) for v in plano.values())
        # 6 items - 1 ignorado (PromovaWeb) = 5
        assert total == 5

    def test_lista_vazia_retorna_plano_vazio(self, cfg_basico):
        plano = montar_plano([], cfg_basico)
        assert plano == {}


# ─── Testes: snapshot ─────────────────────────────────────────────────────────

class TestSnapshot:

    def test_salvar_e_carregar_snapshot(self, tmp_path, items_exemplo, cfg_basico):
        plano = montar_plano(items_exemplo, cfg_basico)
        path  = salvar_snapshot(items_exemplo, plano, snapshots_dir=str(tmp_path))

        assert os.path.exists(path)
        snap = carregar_snapshot(path)

        assert "timestamp" in snap
        assert "total_itens" in snap
        assert "itens" in snap
        assert snap["total_itens"] == len(snap["itens"])

    def test_snapshot_contem_campos_obrigatorios(self, tmp_path, items_exemplo, cfg_basico):
        plano = montar_plano(items_exemplo, cfg_basico)
        path  = salvar_snapshot(items_exemplo, plano, snapshots_dir=str(tmp_path))
        snap  = carregar_snapshot(path)

        for item in snap["itens"]:
            assert "id"        in item
            assert "nome"      in item
            assert "mimeType"  in item
            assert "parent_id" in item
            assert "destino"   in item

    def test_listar_snapshots_ordenado_mais_recente_primeiro(self, tmp_path, items_exemplo, cfg_basico):
        plano = montar_plano(items_exemplo, cfg_basico)
        p1 = salvar_snapshot(items_exemplo, plano, snapshots_dir=str(tmp_path))
        p2 = salvar_snapshot(items_exemplo, plano, snapshots_dir=str(tmp_path))

        snapshots = listar_snapshots(snapshots_dir=str(tmp_path))
        assert snapshots[0] == p2  # mais recente primeiro

    def test_listar_snapshots_pasta_vazia(self, tmp_path):
        snapshots = listar_snapshots(snapshots_dir=str(tmp_path))
        assert snapshots == []

    def test_snapshot_nao_inclui_itens_ignorados(self, tmp_path, items_exemplo, cfg_basico):
        plano = montar_plano(items_exemplo, cfg_basico)
        path  = salvar_snapshot(items_exemplo, plano, snapshots_dir=str(tmp_path))
        snap  = carregar_snapshot(path)

        nomes = [i["nome"] for i in snap["itens"]]
        assert "PromovaWeb" not in nomes


# ─── Testes: mock API — listar_raiz() ─────────────────────────────────────────

class TestListarRaiz:

    def test_retorna_lista_de_items(self, service_mock):
        service_mock.files().list().execute.return_value = {
            "files": [
                {"id": "1", "name": "Arquivo.pdf", "mimeType": "application/pdf",
                 "modifiedTime": "2024-01-01", "parents": ["root"]},
            ],
            # sem nextPageToken = uma unica pagina
        }
        items = listar_raiz(service_mock)
        assert len(items) == 1
        assert items[0]["name"] == "Arquivo.pdf"

    def test_pagina_multipla(self, service_mock):
        # Primeira chamada retorna nextPageToken, segunda nao
        service_mock.files().list().execute.side_effect = [
            {"files": [{"id": "1", "name": "A.pdf", "mimeType": "application/pdf",
                        "modifiedTime": "2024-01-01", "parents": ["root"]}],
             "nextPageToken": "token123"},
            {"files": [{"id": "2", "name": "B.pdf", "mimeType": "application/pdf",
                        "modifiedTime": "2024-01-02", "parents": ["root"]}]},
        ]
        items = listar_raiz(service_mock)
        assert len(items) == 2

    def test_raiz_vazia(self, service_mock):
        service_mock.files().list().execute.return_value = {"files": []}
        items = listar_raiz(service_mock)
        assert items == []


# ─── Testes: mock API — get_or_create_folder() ────────────────────────────────

class TestGetOrCreateFolder:

    def test_retorna_id_se_pasta_existe(self, service_mock):
        service_mock.files().list().execute.return_value = {
            "files": [{"id": "folder_existente"}]
        }
        result = get_or_create_folder(service_mock, "Carreira")
        assert result == "folder_existente"
        service_mock.files().create.assert_not_called()

    def test_cria_pasta_se_nao_existe(self, service_mock):
        service_mock.files().list().execute.return_value = {"files": []}
        service_mock.files().create().execute.return_value = {"id": "nova_pasta"}

        result = get_or_create_folder(service_mock, "Carreira")
        assert result == "nova_pasta"
        service_mock.files().create.assert_called_once()

    def test_cria_com_nome_correto(self, service_mock):
        service_mock.files().list().execute.return_value = {"files": []}
        service_mock.files().create().execute.return_value = {"id": "xpto"}

        get_or_create_folder(service_mock, "Minha Pasta")
        chamada = service_mock.files().create.call_args
        body = chamada[1].get("body") or chamada[0][0]
        assert body["name"] == "Minha Pasta"
        assert body["mimeType"] == "application/vnd.google-apps.folder"


# ─── Testes: mock API — mover_arquivo() ───────────────────────────────────────

class TestMoverArquivo:

    def test_chama_update_com_parametros_corretos(self, service_mock):
        service_mock.files().update().execute.return_value = {"id": "file1", "parents": ["dest1"]}

        mover_arquivo(service_mock, "file1", "dest1", "root")

        service_mock.files().update.assert_called_once_with(
            fileId="file1",
            addParents="dest1",
            removeParents="root",
            fields="id, parents",
        )

    def test_execute_e_chamado(self, service_mock):
        mover_arquivo(service_mock, "f1", "d1", "root")
        service_mock.files().update().execute.assert_called_once()


# ─── Testes: mock API — get_root_id() ────────────────────────────────────────

class TestGetRootId:

    def test_retorna_id_correto(self, service_mock):
        service_mock.files().get().execute.return_value = {"id": "root_real_id"}
        result = get_root_id(service_mock)
        assert result == "root_real_id"

    def test_chama_get_com_root(self, service_mock):
        service_mock.files().get().execute.return_value = {"id": "abc"}
        get_root_id(service_mock)
        service_mock.files().get.assert_called_once_with(fileId="root", fields="id")
