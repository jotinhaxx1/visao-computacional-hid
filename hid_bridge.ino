#include <usbhid.h>
#include <hidboot.h>
#include <usbhub.h>
#include <HID-Project.h>

USB Usb;
HIDBoot<USB_HID_PROTOCOL_MOUSE> HidMouse(&Usb);

class MouseRptParser : public MouseReportParser {
protected:
    void OnMouseMove(MOUSEINFO *mi) { Mouse.move(mi->dX, mi->dY); };
    void OnLeftButtonDown(MOUSEINFO *mi) { Mouse.press(MOUSE_LEFT); };
    void OnLeftButtonUp(MOUSEINFO *mi) { Mouse.release(MOUSE_LEFT); };
    void OnRightButtonDown(MOUSEINFO *mi) { Mouse.press(MOUSE_RIGHT); };
    void OnRightButtonUp(MOUSEINFO *mi) { Mouse.release(MOUSE_RIGHT); };
};

MouseRptParser Prs;

uint8_t estado_sincronia = 0;
int8_t valor_x = 0;
int bytes_lidos_neste_ciclo = 0;

void setup() {
    if (Usb.Init() == -1) {
        pinMode(LED_BUILTIN, OUTPUT);
        while (1) { 
            digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
            delay(500);
        }
    }
    
    HidMouse.SetReportParser(0, &Prs);
    Mouse.begin();
    
    // Baud Rate precisa casar com o do Python
    Serial1.begin(115200);
}

void loop() {
    // 1. MANTÉM O MOUSE FÍSICO VIVO (Sempre executa no início do loop)
    Usb.Task(); 
    
    // 2. LÊ A PORTA SERIAL (Limita a 16 bytes por ciclo para nunca travar o Usb.Task)
    bytes_lidos_neste_ciclo = 0;
    while (Serial1.available() > 0 && bytes_lidos_neste_ciclo < 16) {
        uint8_t b = Serial1.read();
        bytes_lidos_neste_ciclo++;
        
        switch (estado_sincronia) {
            case 0:
                if (b == 0x55) estado_sincronia = 1;
                break;
            case 1:
                if (b == 0xAA) estado_sincronia = 2;
                else if (b == 0x55) estado_sincronia = 1;
                else estado_sincronia = 0;
                break;
            case 2:
                // Força a conversão para inteiro com sinal (permite movimentos negativos)
                valor_x = (int8_t)b;
                estado_sincronia = 3;
                break;
            case 3:
                int8_t valor_y = (int8_t)b;
                
                if (valor_x != 0 || valor_y != 0) {
                    Mouse.move(valor_x, valor_y); // Executa o movimento
                }
                estado_sincronia = 0; // Reseta para a próxima leitura
                break;
        }
    }
}