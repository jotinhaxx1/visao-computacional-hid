import sys
import traceback
import time
import ctypes
import numpy as np
import cv2
import mss
import os
import random
import math
import serial.tools.list_ports

# ==========================================
# CONFIGURAÇÕES OTIMIZADAS
# ==========================================
PORTA_SERIAL = 'COM8'
BAUD_RATE = 115200

# Cores como arrays numpy (mais rápido)
CYAN_LOWER = np.array([85, 100, 100])
CYAN_UPPER = np.array([105, 255, 255])

FOV = 120
STRENGTH = 0.4  # Aumentado para melhor resposta
VK_RBUTTON = 0x02  

# AJUSTES FINOS DE MIRA
MIRA_HEADSHOT = True
ALTURA_CABECA = 0.15  # 15% do topo = cabeça

# AJUSTES DE MOVIMENTO
PASSOS_BEZIER = 5      # Reduzido para resposta mais rápida
ALEATORIEDADE = 1      # Reduzido para menos tremor
TREMOR_SUAVE = True    # Tremor com distribuição natural

# DEADZONE DINÂMICO
DEADZONE_DINAMICO = True
DEADZONE_MIN = 2       # Deadzone mínimo (quase no alvo)
DEADZONE_MAX = 6       # Deadzone máximo (longe do alvo)
OVERSHOOT = 0.15       # 15% de exagero para garantir que chega

# TRACKING (seguir o alvo)
SEM_ALVO_TIMEOUT = 0.2  # 200ms sem alvo antes de resetar
PESO_TRACKING = 0.4     # 40% da posição anterior (suavização)

# ==========================================
# PRÉ-CALCULAR REGIÃO DO MONITOR
# ==========================================
user32 = ctypes.windll.user32
SCREEN_W = user32.GetSystemMetrics(0)
SCREEN_H = user32.GetSystemMetrics(1)

MONITOR_REGION = {
    "top": SCREEN_H // 2 - FOV // 2,
    "left": SCREEN_W // 2 - FOV // 2,
    "width": FOV,
    "height": FOV
}

# ==========================================
# VARIÁVEIS GLOBAIS PARA TRACKING
# ==========================================
ULTIMA_POSICAO = None
ULTIMO_TEMPO_ALVO = 0

# ==========================================
# FUNÇÕES BÁSICAS
# ==========================================
def clamp(val):
    return max(min(int(val), 127), -127)

def is_aiming():
    return ctypes.windll.user32.GetAsyncKeyState(VK_RBUTTON) & 0x8000

def listar_portas():
    """Mostra portas COM disponíveis"""
    print("\n>> Portas COM disponíveis:")
    for port in serial.tools.list_ports.comports():
        print(f"   - {port.device}: {port.description}")
    print()

def bezier_curva(t, p0, p1, p2):
    """Curva de Bezier quadrática"""
    return (1-t)**2 * p0 + 2*(1-t)*t * p1 + t**2 * p2

# ==========================================
# FUNÇÃO DE MOVIMENTO OTIMIZADA
# ==========================================
def calcular_movimento_otimizado(diff_x, diff_y):
    """Calcula movimento com deadzone dinâmico e overshoot"""
    
    if diff_x == 0 and diff_y == 0:
        return 0, 0
    
    # Calcula distância euclidiana
    distancia = math.sqrt(diff_x**2 + diff_y**2)
    
    # Deadzone dinâmico
    if DEADZONE_DINAMICO and distancia > 0:
        if distancia < 10:
            deadzone = DEADZONE_MIN
        elif distancia < 30:
            # Interpolação linear
            fator = (distancia - 10) / 20
            deadzone = DEADZONE_MIN + fator * (DEADZONE_MAX - DEADZONE_MIN)
        else:
            deadzone = DEADZONE_MAX
    else:
        deadzone = DEADZONE_MAX  # Fallback
    
    # Overshoot (só quando perto do alvo)
    overshoot_x = 0
    overshoot_y = 0
    if 5 < distancia < 20:
        overshoot_x = int(OVERSHOOT * diff_x)
        overshoot_y = int(OVERSHOOT * diff_y)
    
    # Aplica deadzone
    if abs(diff_x) <= deadzone:
        mx = overshoot_x
    else:
        mx = int(diff_x * STRENGTH) + overshoot_x
    
    if abs(diff_y) <= deadzone:
        my = overshoot_y
    else:
        my = int(diff_y * STRENGTH) + overshoot_y
    
    return clamp(mx), clamp(my)

# ==========================================
# FUNÇÃO DE MOVIMENTO HUMANO ATUALIZADA
# ==========================================
def gerar_movimento_humano(diff_x, diff_y):
    """Gera movimento com suavização e tremor natural"""
    
    if diff_x == 0 and diff_y == 0:
        return [(0, 0)]
    
    # Usa a função otimizada para calcular movimento base
    mx, my = calcular_movimento_otimizado(diff_x, diff_y)
    
    if mx == 0 and my == 0:
        return [(0, 0)]
    
    # Curva de Bezier para suavização
    p0_x, p0_y = 0, 0
    p2_x, p2_y = mx, my
    
    # Ponto de controle com desvio suave (reduzido)
    desvio = 0.2  # Reduzido para trajetória mais direta
    p1_x = mx * (0.5 + desvio * random.uniform(-0.2, 0.2))
    p1_y = my * (0.5 + desvio * random.uniform(-0.2, 0.2))
    
    movimentos = []
    for i in range(1, PASSOS_BEZIER + 1):
        t = i / PASSOS_BEZIER
        
        if i == 1:
            dx = int(bezier_curva(t, p0_x, p1_x, p2_x))
            dy = int(bezier_curva(t, p0_y, p1_y, p2_y))
        else:
            t_anterior = (i-1) / PASSOS_BEZIER
            x_anterior = bezier_curva(t_anterior, p0_x, p1_x, p2_x)
            y_anterior = bezier_curva(t_anterior, p0_y, p1_y, p2_y)
            x_atual = bezier_curva(t, p0_x, p1_x, p2_x)
            y_atual = bezier_curva(t, p0_y, p1_y, p2_y)
            
            dx = int(x_atual - x_anterior)
            dy = int(y_atual - y_anterior)
        
        # Tremor suave apenas nos últimos passos (ajuste fino)
        if i > PASSOS_BEZIER - 2 and ALEATORIEDADE > 0:
            if TREMOR_SUAVE:
                # Distribuição gaussiana (mais natural)
                tremor_x = int(random.gauss(0, ALEATORIEDADE * 0.5))
                tremor_y = int(random.gauss(0, ALEATORIEDADE * 0.5))
            else:
                tremor_x = random.randint(-ALEATORIEDADE, ALEATORIEDADE)
                tremor_y = random.randint(-ALEATORIEDADE, ALEATORIEDADE)
            
            # Limita tremor a ±1 pixel para não atrapalhar
            dx += max(-1, min(1, tremor_x))
            dy += max(-1, min(1, tremor_y))
        
        dx = clamp(dx)
        dy = clamp(dy)
        
        if dx != 0 or dy != 0:
            movimentos.append((dx, dy))
    
    return movimentos if movimentos else [(mx, my)]

# ==========================================
# CONEXÃO SERIAL
# ==========================================
def conectar_serial():
    try:
        print(f">> [INFO] Tentando abrir {PORTA_SERIAL}...")
        
        ser = serial.Serial(PORTA_SERIAL, BAUD_RATE, timeout=0.1)
        print(f">> [BINGO] Conectado em {PORTA_SERIAL}")
        print(f">> Versão pyserial: {serial.__version__}")
        return ser
        
    except serial.SerialException as e:
        print(f">> [ERRO] Não foi possível abrir {PORTA_SERIAL}")
        print(f">> Detalhe: {e}")
        listar_portas()
        print("\n>> DICA: Verifique se:")
        print("   1. O Arduino está conectado")
        print("   2. A porta COM está correta")
        print("   3. Nenhum outro programa está usando a porta")
        sys.exit(1)

# ==========================================
# FECHAMENTO SEGURO
# ==========================================
def safe_close(ser):
    try:
        if ser and hasattr(ser, 'is_open') and ser.is_open:
            ser.close()
            print(">> Porta serial fechada.")
    except:
        pass

# ==========================================
# LÓGICA PRINCIPAL COM TRACKING
# ==========================================
def aim_logic():
    global ULTIMA_POSICAO, ULTIMO_TEMPO_ALVO
    
    print(f"\n{'='*50}")
    print(f">> SISTEMA STEALTH ON!")
    print(f">> Resolução: {SCREEN_W}x{SCREEN_H} | FOV: {FOV}")
    print(f">> Mira: {'CABEÇA' if MIRA_HEADSHOT else 'PEITO'}")
    print(f">> Deadzone dinâmico: {DEADZONE_MIN}-{DEADZONE_MAX}")
    print(f">> Overshoot: {OVERSHOOT*100:.0f}%")
    print(f">> Tremor: {ALEATORIEDADE} (suave)")
    print(f"{'='*50}\n")
    
    stats = {'frames': 0, 'tiros': 0, 'fps': 0}
    last_time = time.time()

    with mss.mss() as sct:
        while True:
            try:
                if not is_aiming():
                    time.sleep(0.005)
                    # Reseta posição se não está mirando há muito tempo
                    if time.time() - ULTIMO_TEMPO_ALVO > SEM_ALVO_TIMEOUT:
                        ULTIMA_POSICAO = None
                    continue

                # Captura tela
                img = np.array(sct.grab(MONITOR_REGION))
                
                # Processamento de imagem
                img_bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
                
                # Máscara de cor
                mask = cv2.inRange(hsv, CYAN_LOWER, CYAN_UPPER)
                mask = cv2.erode(mask, None, iterations=1)
                mask = cv2.dilate(mask, None, iterations=1)

                contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                
                if contours:
                    # Atualiza tempo do alvo
                    ULTIMO_TEMPO_ALVO = time.time()
                    
                    # Maior contorno
                    c = max(contours, key=cv2.contourArea)
                    if cv2.contourArea(c) > 30:
                        x, y, w, h = cv2.boundingRect(c)
                        
                        # Posição alvo
                        target_x = x + w // 2
                        if MIRA_HEADSHOT:
                            target_y = y + int(h * ALTURA_CABECA)
                        else:
                            target_y = y + h // 3
                        
                        # ===== TRACKING: suavização temporal =====
                        if ULTIMA_POSICAO:
                            # Mistura posição nova com antiga (mais estável)
                            target_x = int((1 - PESO_TRACKING) * target_x + PESO_TRACKING * ULTIMA_POSICAO[0])
                            target_y = int((1 - PESO_TRACKING) * target_y + PESO_TRACKING * ULTIMA_POSICAO[1])
                        
                        ULTIMA_POSICAO = (target_x, target_y)
                        
                        # Calcula diferença do centro
                        diff_x = target_x - FOV // 2
                        diff_y = target_y - FOV // 2
                        
                        # Gera movimento humano
                        movimentos = gerar_movimento_humano(diff_x, diff_y)
                        
                        # Executa movimento
                        for dx, dy in movimentos:
                            if dx != 0 or dy != 0:
                                packet = bytearray([0x55, 0xAA, dx & 0xFF, dy & 0xFF])
                                arduino_serial.write(packet)
                                stats['tiros'] += 1
                                time.sleep(0.001)  # Pequena pausa entre passos
                else:
                    # Sem alvo: reseta posição após timeout
                    if time.time() - ULTIMO_TEMPO_ALVO > SEM_ALVO_TIMEOUT:
                        ULTIMA_POSICAO = None
                
                # Estatísticas
                stats['frames'] += 1
                if stats['frames'] % 300 == 0:
                    now = time.time()
                    fps = 300 / (now - last_time)
                    print(f">> FPS: {fps:.1f} | Correções: {stats['tiros']}")
                    last_time = now
                    
            except Exception as e:
                print(f">> Erro no frame: {e}")
                time.sleep(0.01)
                continue

# ==========================================
# EXECUÇÃO PRINCIPAL
# ==========================================
if __name__ == "__main__":
    arduino_serial = None
    try:
        arduino_serial = conectar_serial()
        aim_logic()
    except KeyboardInterrupt:
        print("\n>> Interrompido pelo usuário")
    except Exception as e:
        print("\n" + "="*50)
        print("ERRO FATAL:")
        traceback.print_exc()
        print("="*50)
    finally:
        safe_close(arduino_serial)
        input("Aperte ENTER para sair...")