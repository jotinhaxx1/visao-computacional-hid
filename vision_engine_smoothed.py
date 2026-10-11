import sys
import traceback
import time
import ctypes
import numpy as np
import cv2
import mss
import random
import math
import serial
import serial.tools.list_ports
import threading
import os
from queue import Queue, Empty

# ==========================================
# 1. HARDWARE & JOGO
# ==========================================
PORTA_SERIAL = 'COM8'
BAUD_RATE = 115200
FOV = 250
VK_RBUTTON = 0x02  

PATH_CONFIG = r"C:\ProgramData\Realtek_Audio_Drivers\contas pra pagar.txt"

# ==========================================
# 2. ESPECTRO DE COR 
# ==========================================
TARGET_LOWER_1 = np.array([135, 80, 70])
TARGET_UPPER_1 = np.array([170, 255, 255])

# ==========================================
# 3. CONSTANTES (CALIBRADAS P/ SENSI 0.125)
# ==========================================
MULTIPLICADOR_SENSI = 9.0   # Aumentado para vencer o atraso no acompanhamento
DURACAO_SOFT_START = 0.05 
MAX_PIXELS_PASSO = 40       # Permite passos mais largos de longe
FATOR_PREDICAO = 1.3        

MIN_AREA = 12
MAX_AREA = 4000
KERNEL_SIZE = 5
THREAD_TIMEOUT = 0.05
CAPTURA_QUEUE_SIZE = 2
PROCESSA_QUEUE_SIZE = 2

# ==========================================
# FUNÇÃO DE LEITURA DINÂMICA
# ==========================================
def carregar_config_dinamica():
    smoothing_default = 0.35
    deadzone_default = 2
    try:
        if not os.path.exists(PATH_CONFIG):
            with open(PATH_CONFIG, "w", encoding='utf-8') as f:
                f.write(f"forca_imã = {smoothing_default}\ndeadzone = {deadzone_default}")
            return smoothing_default, deadzone_default
        
        with open(PATH_CONFIG, "r", encoding='utf-8') as f:
            linhas = f.readlines()
            
        smoothing_val, deadzone_val = smoothing_default, deadzone_default
        for linha in linhas:
            if "=" in linha:
                chave, valor = linha.split("=")
                chave = chave.strip().lower()
                valor = valor.strip()
                if chave == "forca_imã": smoothing_val = float(valor)
                elif chave == "deadzone": deadzone_val = int(valor)
                
        return max(0.01, min(1.0, smoothing_val)), max(0, min(10, deadzone_val))
    except Exception:
        return smoothing_default, deadzone_default

# ==========================================
# THREADS DE CAPTURA E PROCESSAMENTO
# ==========================================
running = True
captura_queue = Queue(maxsize=CAPTURA_QUEUE_SIZE)
processa_queue = Queue(maxsize=PROCESSA_QUEUE_SIZE)

def is_aiming():
    return ctypes.windll.user32.GetAsyncKeyState(VK_RBUTTON) & 0x8000

def conectar_serial():
    try:
        ser = serial.Serial(PORTA_SERIAL, BAUD_RATE, timeout=0)
        return ser
    except serial.SerialException:
        sys.exit(1)

def thread_captura():
    global running
    user32 = ctypes.windll.user32
    SCREEN_W, SCREEN_H = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    MONITOR_REGION = {"top": SCREEN_H // 2 - FOV // 2, "left": SCREEN_W // 2 - FOV // 2, "width": FOV, "height": FOV}
    
    with mss.mss() as sct:
        while running:
            try:
                if captura_queue.full():
                    try: captura_queue.get_nowait()
                    except Empty: pass
                img = sct.grab(MONITOR_REGION)
                captura_queue.put((time.perf_counter(), np.array(img)))
            except Exception: pass

def thread_processa():
    global running
    kernel_cross = cv2.getStructuringElement(cv2.MORPH_CROSS, (KERNEL_SIZE, KERNEL_SIZE))
    while running:
        try:
            timestamp, img_raw = captura_queue.get(timeout=THREAD_TIMEOUT)
            img_bgr = cv2.cvtColor(img_raw, cv2.COLOR_BGRA2BGR)
            h_orig, w_orig = img_bgr.shape[:2]
            centro_x_orig, centro_y_orig = w_orig // 2, h_orig // 2
            
            img_small = cv2.resize(img_bgr, (w_orig//2, h_orig//2))
            hsv = cv2.cvtColor(img_small, cv2.COLOR_BGR2HSV)
            
            mask = cv2.inRange(hsv, TARGET_LOWER_1, TARGET_UPPER_1)
            mask = cv2.dilate(mask, kernel_cross, iterations=2)
            mask = cv2.erode(mask, kernel_cross, iterations=1)
            
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            melhor_alvo, menor_dist = None, float('inf')
            
            for cnt in contours:
                area = cv2.contourArea(cnt)
                if MIN_AREA < area < MAX_AREA:
                    x, y, w, h = cv2.boundingRect(cnt)
                    ratio = w / float(h) if h > 0 else 0
                    if 0.25 < ratio < 2.2:
                        x_orig, y_orig, w_orig_alvo, h_orig_alvo = x*2, y*2, w*2, h*2
                        altura_fator = 0.08 if h_orig_alvo > 50 else 0.12
                        alvo_x = x_orig + w_orig_alvo // 2
                        alvo_y = y_orig + int(h_orig_alvo * altura_fator)
                        
                        dist = math.sqrt((alvo_x - centro_x_orig)**2 + (alvo_y - centro_y_orig)**2)
                        if dist < menor_dist:
                            menor_dist = dist
                            melhor_alvo = (alvo_x, alvo_y)
            
            if melhor_alvo and not processa_queue.full():
                processa_queue.put((melhor_alvo[0], melhor_alvo[1], timestamp))
        except Empty: continue
        except Exception: pass

# ==========================================
# THREAD 3: MOTOR COM AMORTECEDOR DE SAÍDA
# ==========================================
def thread_envio(arduino):
    global running
    res_x, res_y = 0.0, 0.0
    is_aiming_since = 0.0 
    last_frame_aiming = False 
    ultimo_envio = 0.0
    
    last_tx, last_ty = 0, 0
    vel_x_filtrada, vel_y_filtrada = 0.0, 0.0
    
    # NOVAS VARIÁVEIS DO AMORTECEDOR FÍSICO (Anti-Robô)
    smooth_out_x = 0.0
    smooth_out_y = 0.0
    
    while running:
        try:
            aiming_state = is_aiming()

            if not aiming_state:
                if last_frame_aiming:
                    res_x, res_y = 0.0, 0.0
                    last_tx, last_ty = 0, 0
                    vel_x_filtrada, vel_y_filtrada = 0.0, 0.0
                    smooth_out_x, smooth_out_y = 0.0, 0.0
                    while not processa_queue.empty():
                        try: processa_queue.get_nowait()
                        except Empty: break
                        
                last_frame_aiming = False
                time.sleep(0.001)
                continue
            
            if aiming_state and not last_frame_aiming:
                is_aiming_since = time.perf_counter()
                res_x, res_y = 0.0, 0.0
                last_tx, last_ty = 0, 0
                vel_x_filtrada, vel_y_filtrada = 0.0, 0.0
                smooth_out_x, smooth_out_y = 0.0, 0.0
            last_frame_aiming = aiming_state

            alvo_data = processa_queue.get(timeout=THREAD_TIMEOUT)
            if alvo_data:
                target_x, target_y, timestamp = alvo_data
                
                if last_tx != 0 and last_ty != 0:
                    vx_bruta = target_x - last_tx
                    vy_bruta = target_y - last_ty
                    if vx_bruta != 0 or vy_bruta != 0:
                        vel_x_filtrada = (vel_x_filtrada * 0.85) + (vx_bruta * 0.15)
                        vel_y_filtrada = (vel_y_filtrada * 0.85) + (vy_bruta * 0.15)
                
                last_tx, last_ty = target_x, target_y
                
                alvo_futuro_x = target_x + (vel_x_filtrada * FATOR_PREDICAO)
                alvo_futuro_y = target_y + (vel_y_filtrada * FATOR_PREDICAO)
                
                diff_x = alvo_futuro_x - (FOV // 2)
                diff_y = alvo_futuro_y - (FOV // 2)
                
                distancia = math.sqrt(diff_x**2 + diff_y**2)
                smoothing_atual_conf, deadzone_atual_conf = carregar_config_dinamica()
                
                if distancia <= deadzone_atual_conf:
                    # Zerar o amortecedor suavemente para ele parar limpo
                    smooth_out_x *= 0.5
                    smooth_out_y *= 0.5
                    continue
                
                tempo_rajada = time.perf_counter() - is_aiming_since
                fator_rampa = min(1.0, tempo_rajada / DURACAO_SOFT_START)
                forca_final = smoothing_atual_conf * fator_rampa
                
                move_x_raw = (diff_x * forca_final) * MULTIPLICADOR_SENSI
                move_y_raw = (diff_y * forca_final) * MULTIPLICADOR_SENSI
                
                # --- A MÁGICA ACONTECE AQUI: O AMORTECEDOR DE SAÍDA ---
                # Isso impede o Arduino de dar socos no mouse. Ele obriga o movimento a deslizar.
                smooth_out_x = (smooth_out_x * 0.60) + (move_x_raw * 0.40)
                smooth_out_y = (smooth_out_y * 0.60) + (move_y_raw * 0.40)
                
                smooth_out_x += res_x
                smooth_out_y += res_y
                
                mx = math.trunc(smooth_out_x)
                my = math.trunc(smooth_out_y)
                
                res_x = smooth_out_x - mx
                res_y = smooth_out_y - my
                
                limite = int(MAX_PIXELS_PASSO * MULTIPLICADOR_SENSI)
                mx = max(-limite, min(limite, mx))
                my = max(-limite, min(limite, my))
                
                mx = max(-127, min(127, mx))
                my = max(-127, min(127, my))
                
                if mx != 0 or my != 0:
                    tempo_atual = time.perf_counter()
                    if tempo_atual - ultimo_envio > 0.007:
                        packet = bytearray([0x55, 0xAA, mx & 0xFF, my & 0xFF])
                        arduino.write(packet)
                        arduino.flush()
                        ultimo_envio = tempo_atual
                        
        except Empty: continue
        except Exception: pass

if __name__ == "__main__":
    arduino_serial = None
    try:
        arduino_serial = conectar_serial()
        carregar_config_dinamica()
        threads = [
            threading.Thread(target=thread_captura, daemon=True),
            threading.Thread(target=thread_processa, daemon=True),
            threading.Thread(target=thread_envio, args=(arduino_serial,), daemon=True),
        ]
        for t in threads: t.start()
        while running: time.sleep(1)
    except Exception: pass
    finally:
        running = False
        time.sleep(0.5)
        if arduino_serial: arduino_serial.close()