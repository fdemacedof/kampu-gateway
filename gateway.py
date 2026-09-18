import os
import time
import threading
import json
import piexif
import requests
import subprocess
from flask import Flask, request, jsonify

app = Flask(__name__)

# ==========================================
# 1. CONFIGURAÇÕES GERAIS
# ==========================================

# --- IP DO NODEMCU (Sensor DHT11 + Relé) ---
IP_DO_NODEMCU = "192.168.0.43"
URL_NODEMCU = f"http://{IP_DO_NODEMCU}"

# Pasta raiz do Orange Pi (espelhada no Ubuntu via SSHFS)
PASTA_ASSETS = "/var/kampu/imagens"
if not os.path.exists(PASTA_ASSETS):
    os.makedirs(PASTA_ASSETS, exist_ok=True)

clima_atual = {
    "umidade": "0", "temperatura": "0", "luminosidade": "0",
    "umidificador": "OFF", "modo_rele": "automatico", "ultimo_update": "--:--"
}

# ==========================================
# 2. INJEÇÃO DE METADADOS
# ==========================================

def injetar_metadados(caminho):
    """Lê a foto tirada pela webcam e injeta o clima no EXIF."""
    dados_sensor = {
        "temp": clima_atual["temperatura"],
        "humi": clima_atual["umidade"],
        "lux": clima_atual["luminosidade"],
        "timestamp": time.strftime("%Y:%m:%d %H:%M:%S")
    }
    comment_str = json.dumps(dados_sensor)
    
    exif_dict = {
        "0th": {
            piexif.ImageIFD.DateTime: time.strftime("%Y:%m:%d %H:%M:%S"),
            piexif.ImageIFD.Software: u"Kampu Edge Gateway"
        },
        "Exif": {
            piexif.ExifIFD.DateTimeOriginal: time.strftime("%Y:%m:%d %H:%M:%S"),
            piexif.ExifIFD.UserComment: comment_str.encode('utf-8')
        }
    }
    
    try:
        exif_bytes = piexif.dump(exif_dict)
        piexif.insert(exif_bytes, caminho)
        print(f"✅ Foto salva (Webcam): {caminho} | 🌡️ Temp: {clima_atual['temperatura']}°C | 💧 Umi: {clima_atual['umidade']}%")
    except Exception as e:
        print(f"⚠️ Erro ao injetar metadados EXIF: {e}")

# ==========================================
# 3. THREAD DE CAPTURA LOCAL (WEBCAM)
# ==========================================

def rotina_captura_periodica():
    while True:
        try:
            nome_arquivo = f"kampu_{int(time.time())}.jpg"
            caminho = os.path.join(PASTA_ASSETS, nome_arquivo)
            
            # Chama o fswebcam via sistema (Resolução de exemplo: 1280x720. Altere se sua webcam for diferente)
            comando = ["fswebcam", "-r", "1280x720", "--no-banner", "--jpeg", "85", caminho]
            subprocess.run(comando, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Se o fswebcam conseguiu criar o arquivo, colocamos o EXIF
            if os.path.exists(caminho):
                injetar_metadados(caminho)
                
        except Exception as e:
            print(f"⚠️ Erro ao capturar a foto da Webcam: {e}")
            
        time.sleep(10) 

threading.Thread(target=rotina_captura_periodica, daemon=True).start()

# ==========================================
# 4. ROTAS FLASK (TELEMETRIA E CONTROLE)
# ==========================================

@app.route('/api/clima', methods=['GET'])
def get_clima(): 
    return jsonify(clima_atual)

@app.route('/api/sensores', methods=['POST'])
def receber_sensores():
    global clima_atual
    dados = request.get_json()
    if not dados: return jsonify({"erro": "Nenhum dado JSON recebido"}), 400

    if 'temperatura_ar' in dados: clima_atual['temperatura'] = round(dados['temperatura_ar'], 1)
    if 'umidade_ar' in dados: clima_atual['umidade'] = round(dados['umidade_ar'], 1)
    if 'luminosidade' in dados: clima_atual['luminosidade'] = dados['luminosidade']
    if 'umidificador' in dados: clima_atual['umidificador'] = dados['umidificador']
    if 'modo' in dados: clima_atual['modo_rele'] = dados['modo']
    
    clima_atual['ultimo_update'] = time.strftime("%H:%M:%S")
    return jsonify({"status": "sucesso"}), 200

# ==========================================
# 5. CONTROLE DO RELÉ (Proxy)
# ==========================================

def chamar_nodemcu(caminho):
    try:
        resposta = requests.get(f"{URL_NODEMCU}{caminho}", timeout=5)
        return resposta.json(), resposta.status_code
    except requests.exceptions.RequestException as e:
        return {"erro": "Sem conexão com NodeMCU", "detalhe": str(e)}, 503

@app.route('/api/rele/on', methods=['POST'])
def rele_ligar():
    dados, status = chamar_nodemcu("/rele/on")
    if status == 200:
        clima_atual['umidificador'], clima_atual['modo_rele'] = "ON", "manual"
    return jsonify(dados), status

@app.route('/api/rele/off', methods=['POST'])
def rele_desligar():
    dados, status = chamar_nodemcu("/rele/off")
    if status == 200:
        clima_atual['umidificador'], clima_atual['modo_rele'] = "OFF", "manual"
    return jsonify(dados), status

@app.route('/api/rele/auto', methods=['POST'])
def rele_modo_automatico():
    dados, status = chamar_nodemcu("/rele/auto")
    if status == 200: clima_atual['modo_rele'] = "automatico"
    return jsonify(dados), status

@app.route('/api/rele/status', methods=['GET'])
def rele_status():
    dados, status = chamar_nodemcu("/status")
    return jsonify(dados), status

if __name__ == '__main__':
    print("🚀 Kampu Edge Gateway iniciado (Modo Webcam UVC)!")
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)