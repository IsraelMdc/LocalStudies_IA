# LocalStudies_IA

Repositório de engenharia e orquestração para **modelagem 3D no Blender a partir de arquivos DWG**, utilizando modelos locais via **LM Studio**, **LM Link** (topologia **Mestre e Servos** com alocação automática por VRAM), **Cofre Obsidian (`vault_samarco/`)** e **Blender MCP** diretamente no **VS Code**.

## Documentação

- **[docs/HOW_TO_USE.md](docs/HOW_TO_USE.md):** Guia prático passo a passo ("How to Use") — alocação automática dos modelos nos servos, uso do chat interativo, Cofre Obsidian e modelagem 3D no Blender.
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md):** Inventário completo dos **5 nós** (Mestre `Magalhães_note` + 4 Servos via LM Link — **46,4 GB VRAM** total nos servos), diagramas Mermaid, trade-offs, padrão de metadados `Custom Properties` por peça 3D e Cofre Obsidian anti-alucinação.
- **[docs/MODELS.md](docs/MODELS.md):** Links diretos do Hugging Face, quantizações e comandos `lms get` para cada uma das 5 máquinas.
- **[config/fleet_models.json](config/fleet_models.json):** Configuração declarativa da frota consumida pelo alocador automático (`auto_allocator.py`) e pelo terminal interativo (`uv run localstudies-chat`).
