# PyTimelapse

Sistema de timelapse via câmera do notebook com interface gráfica (GUI).

**Versão 2.0** — Interface Tkinter + Preview de câmera em tempo real + Persistência JSON

---

## Instalação de dependências

```bash
pip install opencv-python Pillow
```

> **Linux (Ubuntu/Debian):** caso o Tkinter não esteja disponível:
> ```bash
> sudo apt install python3-tk
> ```

## Uso

```bash
python timelapse.py
```

A janela principal abre automaticamente — nenhum argumento de linha de comando é necessário.

---

## Funcionalidades

- **Ícone de aplicação** gerado automaticamente via Pillow (câmera estilizada)
- **Interface gráfica** (Tkinter) — sem necessidade de terminal
- **Preview em tempo real** da câmera dentro da própria janela
- **Indicador visual** (borda vermelha piscante) a cada frame capturado
- **Persistência de configurações** em `config.json` com auto-save
- **Compilação automática** de frames em vídeo `.mp4` ao encerrar a sessão
- **Barra de progresso** durante a compilação
- Suporte a múltiplas câmeras (configurável por índice)

### Gerenciador de vídeos

O botão **🎬 Vídeos** abre um modal com todos os `.mp4` já gerados no diretório de saída:

- Lista ordenada por data de criação (mais recente primeiro)
- Exibe nome do arquivo, tamanho em MB e data/hora
- Duplo clique ou botão **Abrir Vídeo** abre com o player padrão do sistema
- Funciona em Linux (`xdg-open`), macOS (`open`) e Windows (`os.startfile`)

### Gravação com timer

O botão **⏱ Iniciar com Timer** inicia uma sessão que para e compila automaticamente:

1. Informe o número de minutos no campo **"Gravar por:"**
2. Clique em **⏱ Iniciar com Timer**
3. A gravação encerra automaticamente após o tempo configurado

> O campo **"Duração máx (min)"** nas configurações também define um limite para o botão **Iniciar Timelapse** normal.

## Configurações (config.json)

| Campo | Padrão | Descrição |
|-------|--------|-----------|
| `interval` | `5` | Intervalo em segundos entre frames |
| `fps` | `24` | FPS do vídeo de saída |
| `duration` | `null` | Duração máxima em minutos para modo normal (`null` = ilimitado) |
| `camera_index` | `0` | Índice da câmera (0 = padrão) |
| `output_dir` | `./timelapse_output` | Diretório de saída |
| `keep_frames` | `false` | Preservar frames `.jpg` após compilação |

## Estrutura de saída

```
timelapse_output/
  session_2026-03-12_14-30-00/
    frames/
      frame_00001.jpg
      ...
    timelapse_2026-03-12_14-30-00.mp4
    timelapse.log
config.json
```

## Requisitos

- Python 3.10+
- opencv-python >= 4.5
- Pillow >= 9.0
- tkinter (nativo do Python)

## Licença

MIT
