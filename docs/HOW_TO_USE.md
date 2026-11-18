# Guia Prático de Uso (How to Use) — LocalStudies_IA

Passo a passo para operar o **LM Studio + LM Link (Mestre e Servos)**, o **Cofre Obsidian (`vault_samarco/`)**, a **Alocação Automática de Modelos** e a **Modelagem 3D no Blender via MCP** sem sair do **VS Code**.

---

## 1. Checklist de 1 Minuto (Antes de Começar)

1. **No Blender (`Magalhães_note`):**
   * Abra o Blender.
   * Pressione `N` na Viewport 3D → aba **BlenderMCP** → clique em **Connect to MCP server** (porta `9876`).
2. **No Obsidian (`Magalhães_note`):**
   * Abra o Obsidian → **Open folder as vault** → selecione a pasta `vault_samarco/` dentro deste repositório.
3. **No Terminal do VS Code:**
   * Garanta que o servidor HTTP local do LM Studio está ativo:
     ```powershell
     lms server start --port 1234
     ```

---

## 2. Alocação Automática dos Modelos nos Servos (`auto_allocator`)

O repositório analisa automaticamente os modelos baixados em cada máquina do LM Link (`lms ls --json`), verifica a VRAM de cada GPU e carrega o modelo ideal em cada servo (bloqueando modelos que estourariam a VRAM, como o 14B na `nuttec` de 7,6 GB):

* **Ver o plano de alocação (Dry-Run, sem carregar na VRAM):**
  ```powershell
  uv run python -m localstudies.auto_allocator
  ```
* **Alocar e carregar automaticamente todos os modelos nos servos:**
  ```powershell
  uv run python -m localstudies.auto_allocator --apply
  ```
* **Alocar apenas um papel específico (ex: só o modelo 3D na `berinjela`):**
  ```powershell
  uv run python -m localstudies.auto_allocator --apply --role coder_3d
  ```

### O que o Alocador faz em cada máquina:
| Máquina | VRAM | Papel / Identifier | Modelo Selecionado Automaticamente |
| :--- | :--- | :--- | :--- |
| **`berinjela`** | 15,6 GB | `coder_3d` | `qwen3.8-14b-instruct-turbo-i1` (`8,68 GB`, `ctx: 24576`) |
| **`nixos_4060`** | 7,6 GB | `vision_audit` | `qwen2.5-vl-7b-instruct@q3_k_m` (`6,51 GB`, `ctx: 8192`) |
| **`nuttec`** | 7,6 GB | `embeddings_rag` + `fast_triage` | `text-embedding-bge-m3@q8_0` (`0,63 GB`) + `qwen3-4b` (`2,49 GB`) |
| **`Magalhães_note`** | 8,0 GB | `workstation` | **Livre (0 GB)** — reserva 100% da GPU local para o Blender |

---

## 3. Usando o Terminal Interativo no VS Code (`localstudies-chat`)

Para iniciar o chat conectado automaticamente à frota LM Link, ao Cofre Obsidian e ao Blender MCP:

```powershell
uv run localstudies-chat --blender --auto-allocate
```
*(Se já tiver alocado antes, basta rodar `uv run localstudies-chat --blender`.)*

### Comandos Rápidos dentro do Chat
Digite qualquer um destes comandos no prompt `Você>`:
* `/allocate` — Roda o alocador automático e carrega os modelos nos servos do LM Link.
* `/fleet` — Exibe a tabela das 5 máquinas, GPUs, VRAM e modelos configurados.
* `/vault` — Lista as notas atuais do Cofre Obsidian (`vault_samarco/`).
* `/status` — Mostra o status do `lms link status` e `lms ps` (modelos na VRAM).
* `/models` — Lista os modelos ativos na API `http://localhost:1234/v1/models`.
* `/auto` — Liga/desliga confirmação automática para comandos `lms`.
* `/reset` — Limpa o histórico da conversa (a memória técnica continua salva no Cofre Obsidian).
* `/sair` — Encerra o terminal.

---

## 4. Fluxo Completo: Do Arquivo DWG da `Samarco/` até a Peça 3D Detalhada no Blender

### Passo 1 — Indexar a pasta `Samarco/` (1 vez)
```powershell
uv run python -m localstudies.samarco_index
```
Isso cataloga os **2.195 arquivos** (`1.583 .dwg`, `.pdf`, `.tif`, `.xls`, `.doc`) em `build/samarco_catalog.json`.

### Passo 2 — Conversar com o Agente no `localstudies-chat --blender`
Exemplos de prompts reais que você pode enviar em sequência:

1. **Buscar o DWG desejado:**
   > *"Busque os arquivos DWG da pasta Samarco que contenham `ZTK_U030905`."*
2. **Ingerir no Cofre Obsidian (Anti-Alucinação):**
   > *"Ingira o arquivo `<caminho-do-dxf-ou-dwg>` no Cofre Obsidian e me resuma as layers, cores ACI, cotas e blocos encontrados."*
   *(Obs: para converter `.dwg` bruto automaticamente para `.dxf`, configure `ODA_CONVERTER_PATH` no arquivo `.env` apontando para o executável do **ODA File Converter**).*
3. **Modelar no Blender com Riqueza Máxima de Dados:**
   > *"Com base na nota dessa prancha no Cofre Obsidian, gere e execute no Blender as peças principais usando `generate_detailed_part_script` para salvar todas as Custom Properties, materiais PBR e chanfro Bevel, e atualize o status de cada peça no Cofre Obsidian."*

---

## 5. Como Visualizar os Metadados de Cada Peça dentro do Blender

Quando o modelo cria uma peça no Blender usando o nosso `blender_part_builder.py`:
1. **No Outliner (canto superior direito do Blender):**
   * Veja a hierarquia organizada em `Collections`: `Prancha_DWG → Sistema → Layer_CAD`.
   * Cada peça tem o nome padronizado `<Layer>__<TAG>__<Handle>`.
2. **Na aba Object Properties (ícone de quadrado laranja à direita) → painel `Custom Properties`:**
   * Clique em qualquer peça 3D e abra `Custom Properties` para ver:
     * `dwg_source`, `dwg_handle`, `dwg_layer`, `dwg_type`, `part_tag`, `material_spec`, `aci_color`, `dimensions_m`, `extrude_height_m`, `wall_thickness_m`, `elevation_m`, `cad_attribs_json`, `nearby_notes`.
3. **Na Viewport 3D:**
   * Ative o modo **Material Preview (`Z` → Material Preview)** ou **Rendered** para ver os materiais PBR (`Principled BSDF` com cor ACI) e o acabamento de bordas (`CAD_Bevel` + `CAD_WeightedNormal`).

---

## 6. Atalhos de 1 Clique no VS Code (`Tasks`)

Pressione `Ctrl+Shift+P` → digite **`Tasks: Run Task`** e escolha:
* `LM Studio: Check LM Link Status`
* `LM Studio: Start Local API Server`
* `LocalStudies: Auto-Allocate Fleet Models`
* `LocalStudies: Index Samarco Files`
* `LocalStudies: Initialize Obsidian Vault`
* `LocalStudies: Open LM Studio Manager Chat`
