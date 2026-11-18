# Catálogo de Modelos por Máquina — LocalStudies_IA (LM Link)

Guia de instalação dos modelos GGUF recomendados para cada nó da arquitetura **Mestre e Servos**, dimensionados para a VRAM real de cada GPU.

---

## Resumo Rápido por Máquina

| Máquina | Device ID | GPU (VRAM) | Papel | Modelo Principal Recomendado | Quantização | Contexto Ideal |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. `berinjela`** *(Preferred)* | `c9d558e8a7f1ab7610cba197267c4d38` | RTX 2000 Ada (**15.6 GB**) | `coder_3d` (Blender MCP + `bpy`) | `lmstudio-community/Qwen3-14B-GGUF` | `Q4_K_M` (~9.0 GB) ou `Q5_K_M` (~10.5 GB) | `24576` (24k) |
| **2. `nixos` (Ada)** | `8d27c8a9351745605bfede9f7cd6dc07` | RTX 2000 Ada (**15.6 GB**) | `dwg_planner` (Planejamento CAD/Obsidian) | `lmstudio-community/Qwen3-30B-A3B-GGUF` ou `unsloth/Qwen3-14B-GGUF` | 30B-A3B `Q3_K_L` (~13 GB) ou 14B `Q5_K_M` | `16384`–`24576` |
| **3. `nixos` (4060)** | `3a54719e8256bdd028946faa0a585341` | RTX 4060 (**7.6 GB**) | `vision_audit` (`.tif`/`.pdf` + prints Viewport) | `unsloth/Qwen2.5-VL-7B-Instruct-GGUF` | `Q4_K_M` (~5.2 GB + `mmproj`) | `8192` (8k) |
| **4. `nuttec`** | `98c80cdab4b745a990b39b3c7662ff27` | RTX 4060 (**7.6 GB**) | `embeddings_rag` + `fast_triage` | `lm-kit/bge-m3-gguf` + `lmstudio-community/Qwen3-4B-GGUF` | `bge-m3` (635 MB) + 4B `Q4_K_M` (~2.6 GB) | `8192` (8k) |
| **5. `Magalhães_note`** *(Mestre)* | `local` | RTX 4060 Laptop (**~8.0 GB**) | `workstation` (VS Code + Blender) | *Nenhum residente* (fallback: `qwen2.5-coder-7b-instruct`) | `Q4_K_M` (4.68 GB — apenas offline) | `8192` (8k) |

---

## 1. Máquina `berinjela` — RTX 2000 Ada (15,6 GB VRAM | 30,8 GB RAM)
**Papel:** `coder_3d` — Execução de *Tool Calling* no `blender-mcp` e geração de scripts Python `bpy` detalhados (`Custom Properties`, materiais PBR e modificadores `Bevel`/`Solidify`).

### Opção A — Recomendada (Raciocínio + Tool Calling 14B)
* **Hugging Face (LM Studio Community):** https://huggingface.co/lmstudio-community/Qwen3-14B-GGUF
* **Hugging Face (Oficial Qwen):** https://huggingface.co/Qwen/Qwen3-14B-GGUF
* **Hugging Face (Unsloth):** https://huggingface.co/unsloth/Qwen3-14B-GGUF
* **Quantização:** `Q4_K_M` (~9,0 GB) ou `Q5_K_M` (~10,5 GB)
* **Comando CLI (`lms`):**
  ```powershell
  lms get lmstudio-community/Qwen3-14B-GGUF@Q4_K_M --gguf -y
  ```

### Opção B — Especialista em Código Python / `bpy` (14B)
* **Hugging Face (LM Studio Community):** https://huggingface.co/lmstudio-community/Qwen2.5-Coder-14B-Instruct-GGUF
* **Hugging Face (Oficial Qwen):** https://huggingface.co/Qwen/Qwen2.5-Coder-14B-Instruct-GGUF
* **Hugging Face (Unsloth):** https://huggingface.co/unsloth/Qwen2.5-Coder-14B-Instruct-GGUF
* **Comando CLI (`lms`):**
  ```powershell
  lms get lmstudio-community/Qwen2.5-Coder-14B-Instruct-GGUF@Q5_K_M --gguf -y
  ```

---

## 2. Máquina `nixos` (Ada) (`8d27c8a9...`) — RTX 2000 Ada (15,6 GB VRAM | 31,0 GB RAM)
**Papel:** `dwg_planner` — Interpreta o JSON extraído do DWG da Samarco, organiza o plano de modelagem e estrutura as notas no Cofre Obsidian (`vault_samarco/`).

### Opção A — MoE Rápido 30B (3B ativos por token)
* **Hugging Face (LM Studio Community):** https://huggingface.co/lmstudio-community/Qwen3-30B-A3B-GGUF
* **Quantização:** `Q3_K_L` ou `Q4_K_S` (~12,5–13,5 GB)
* **Comando CLI (`lms`):**
  ```bash
  lms get lmstudio-community/Qwen3-30B-A3B-GGUF@Q3_K_L --gguf -y
  ```

### Opção B — Denso 14B em Alta Precisão (`Q5_K_M`, modo *Thinking* ativado)
* **Hugging Face (Unsloth):** https://huggingface.co/unsloth/Qwen3-14B-GGUF
* **Hugging Face (Bartowski):** https://huggingface.co/bartowski/Qwen_Qwen3-14B-GGUF
* **Comando CLI (`lms`):**
  ```bash
  lms get unsloth/Qwen3-14B-GGUF@Q5_K_M --gguf -y
  ```

---

## 3. Máquina `nixos` (4060) (`3a54719e...`) — RTX 4060 (7,6 GB VRAM | 31,0 GB RAM)
**Papel:** `vision_audit` — Leitura multimodal dos **229 `.tif` / 86 `.pdf`** da pasta `Samarco/` e auditoria visual de capturas da Viewport 3D do Blender.

### Modelo Multimodal (Visão + Texto 7B)
* **Hugging Face (Unsloth):** https://huggingface.co/unsloth/Qwen2.5-VL-7B-Instruct-GGUF
* **Hugging Face (Bartowski):** https://huggingface.co/bartowski/Qwen_Qwen2.5-VL-7B-Instruct-GGUF
* **Quantização:** `Q4_K_M` (~5,2 GB + `mmproj` de visão)
* **Comando CLI (`lms`):**
  ```bash
  lms get unsloth/Qwen2.5-VL-7B-Instruct-GGUF@Q4_K_M --gguf -y
  ```
* **Fallback já disponível no seu ambiente:** `gemma-4-e4b-it-qat` (6,15 GB).

---

## 4. Máquina `nuttec` (`98c80cdab...`) — RTX 4060 (7,6 GB VRAM | 31,0 GB RAM)
**Papel:** `embeddings_rag` + `fast_triage` — Busca semântica nos **2.195 arquivos da Samarco** (`.dwg`, `.xls`, `.doc`) e no Cofre Obsidian, rodando **2 modelos leves simultaneamente** nos 7,6 GB de VRAM.

### 4.1 Modelo de Embeddings (Multilíngue PT-BR / EN Técnico)
* **Hugging Face (`lm-kit`):** https://huggingface.co/lm-kit/bge-m3-gguf
* **Hugging Face (`cstr`):** https://huggingface.co/cstr/bge-m3-GGUF
* **Comando CLI (`lms`):**
  ```bash
  lms get text-embedding-bge-m3 -y
  ```

### 4.2 LLM Rápido de Triagem (4B ou 8B)
* **Hugging Face (4B — ~2,6 GB em `Q4_K_M`):** https://huggingface.co/lmstudio-community/Qwen3-4B-GGUF
* **Hugging Face (4B Unsloth):** https://huggingface.co/unsloth/Qwen3-4B-GGUF
* **Hugging Face (8B — ~5,0 GB em `Q4_K_M`):** https://huggingface.co/lmstudio-community/Qwen3-8B-GGUF
* **Comando CLI (`lms`):**
  ```bash
  lms get lmstudio-community/Qwen3-4B-GGUF@Q4_K_M --gguf -y
  ```

---

## 5. Máquina `Magalhães_note` (Mestre Local) — RTX 4060 Laptop (~8,0 GB VRAM | 15,7 GB RAM)
**Papel:** `workstation` — Roda **VS Code**, **Blender + Blender MCP**, conversor CAD (`ezdxf`) e o **Cofre Obsidian (`vault_samarco/`)**.

* **Recomendação em produção:** Descarregar modelos locais (`lms unload --all`) para manter 100% da RTX 4060 Laptop dedicada à Viewport 3D / Eevee / Cycles do Blender.
* **Fallback offline (já instalado):** `qwen2.5-coder-7b-instruct` (4,68 GB).
