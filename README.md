# 🎯 Módulos de Visão Computacional & Atuação Hardware USB HID

Projeto em **Python (OpenCV/NumPy)** e **C++ (Arduino Framework)** para processamento de imagem em tempo real e controle de movimento via comunicação serial e hardware USB HID.

O repositório reúne diferentes abordagens algorítmicas de rastreamento e atuação física via microcontrolador.

---

## 📁 Arquivos do Repositório

### 1. Firmware do Microcontrolador
* **`hid_bridge.ino`**: Código em C++ para Arduino (ATmega32u4) com USB Host Shield. Implementa uma máquina de estados de 4 bytes para decodificar pacotes seriais UART (`0x55 0xAA dX dY`) e atuar como um periférico USB HID sem bloquear o mouse físico.

### 2. Módulos de Processamento e Controle (Python)
* **`vision_engine_smoothed.py`**: Pipeline multithreaded (captura com `mss`, processamento HSV com OpenCV e envio serial) utilizando predição vetorial e filtro amortecedor de saída para movimentação suave.
* **`vision_engine_flick.py`**: Módulo otimizado para latência ultra-baixa, com remoção de rampa de aceleração e passos expandidos para atuação de alta velocidade.
* **`vision_engine_bezier.py`**: Gerador de trajetórias interpoladas utilizando **Curvas de Bézier Quadráticas**, deadzone dinâmico, overshoot de chegada e ruído gaussiano para simulação de movimentos biológicos/humanizados.

---

## 🛠️ Tecnologias Utilizadas

* **Linguagens:** Python 3.x, C++ (Arduino Framework)
* **Bibliotecas Python:** `cv2` (OpenCV), `numpy`, `mss`, `pyserial`
* **Bibliotecas Arduino:** `USB_Host_Shield_2.0`, `HID-Project`
* **Hardware:** Arduino Leonardo / Pro Micro + USB Host Shield 2.0 (MAX3421E)
* **Comunicação:** Serial UART @ 115200 baud
