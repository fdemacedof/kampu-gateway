import os
import time
import threading
import json
import piexif
import requests
import urllib.request
from flask import Flask, request, jsonify

app = Flask(__name__)

# ==========================================
# 1. CONFIGURAÇÕES GERAIS
# ==========================================

# --- IP DA CÂMERA ESP32 ---
IP_DO_ESP = "192.168.0.42"
URL_CAPTURE = f"http://{IP_DO_ESP}/capture"

# --- IP DO NODEMCU (Sensor DHT11 + Relé) ---
IP_DO_NODEMCU = "192.168.0.43"
URL_NODEMCU = f"http://{IP_DO_NODEMCU}"

# Pasta raiz do Orange Pi (que será espelhada no Ubuntu via SSHFS)
PASTA_ASSETS = "/var/kampu/imagens"
if not os.path.exists(PASTA_ASSETS):
    os.makedirs(PASTA_ASSETS, exist_ok=True)

clima_atual = {
    "umidade": "0", "temperatura": "0", "luminosidade": "0",
    "umidificador": "OFF", "modo_rele": "automatico", "ultimo_update": "--:--"
}

# ==========================================
# 2. CAPTURA E INJEÇÃO DE METADADOS
# ==========================================

def salvar_foto_com_metadados(raw_jpeg_bytes, caminho):
    """Salva os bytes da imagem, injeta o EXIF e imprime os dados climáticos atuais."""
    
    # 1. Salva o JPEG puro direto no disco
    with open(caminho, 'wb') as f:
        f.write(raw_jpeg_bytes)
    
    # 2. Prepara os metadados do momento
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
    
    # 3. Injeta o EXIF diretamente no arquivo já salvo
    try:
        exif_bytes = piexif.dump(exif_dict)
        piexif.insert(exif_bytes, caminho)
        
        # Imprime o log formatado com o arquivo e os estados atuais dos sensores
        print(f"✅ Foto salva: {caminho} | 🌡️ Temp: {clima_atual['temperatura']}°C | 💧 Umidade: {clima_atual['umidade']}% | ☀️ Lux: {clima_atual['luminosidade']} | 💨 Umidificador: {clima_atual['umidificador']}")
        
    except Exception as e:
        print(f"⚠️ Erro ao injetar metadados EXIF: {e}")

# ==========================================
# 3. THREAD DE REDE (COLETA CONTÍNUA)
# ==========================================

def rotina_captura_periodica():
    while True:
        try:
            # Faz o download direto dos bytes da imagem
            resposta = urllib.request.urlopen(URL_CAPTURE, timeout=10)
            raw_jpeg = resposta.read()
            
            if raw_jpeg:
                nome_arquivo = f"kampu_{int(time.time())}.jpg"
                caminho = os.path.join(PASTA_ASSETS, nome_arquivo)
                
                # Envia os bytes para salvar no disco
                salvar_foto_com_metadados(raw_jpeg, caminho)
                
        except Exception as e:
            print(f"⚠️ Erro ao capturar a foto da Câmera: {e}")
            
        time.sleep(10) 

# Inicia a thread em segundo plano
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
    if not dados:
        return jsonify({"erro": "Nenhum dado JSON recebido"}), 400

    if 'temperatura_ar' in dados:
        clima_atual['temperatura'] = round(dados['temperatura_ar'], 1)
    
    if 'umidade_ar' in dados:
        clima_atual['umidade'] = round(dados['umidade_ar'], 1)

    if 'luminosidade' in dados:
        clima_atual['luminosidade'] = dados['luminosidade']

    if 'umidificador' in dados:
        clima_atual['umidificador'] = dados['umidificador']

    if 'modo' in dados:
        clima_atual['modo_rele'] = dados['modo']
    
    clima_atual['ultimo_update'] = time.strftime("%H:%M:%S")

    print(f"🌡️ Leitura do NodeMCU: Temp {clima_atual['temperatura']}°C | Umidade {clima_atual['umidade']}%")
    return jsonify({"status": "sucesso", "clima_atual": clima_atual}), 200

# ==========================================
# 5. CONTROLE DO RELÉ (Proxy)
# ==========================================

def chamar_nodemcu(caminho):
    try:
        resposta = requests.get(f"{URL_NODEMCU}{caminho}", timeout=5)
        return resposta.json(), resposta.status_code
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Erro ao comunicar com o NodeMCU: {e}")
        return {"erro": "Sem conexão com NodeMCU", "detalhe": str(e)}, 503

@app.route('/api/rele/on', methods=['POST'])
def rele_ligar():
    dados, status_code = chamar_nodemcu("/rele/on")
    if status_code == 200:
        clima_atual['umidificador'] = "ON"
        clima_atual['modo_rele'] = "manual"
    return jsonify(dados), status_code

@app.route('/api/rele/off', methods=['POST'])
def rele_desligar():
    dados, status_code = chamar_nodemcu("/rele/off")
    if status_code == 200:
        clima_atual['umidificador'] = "OFF"
        clima_atual['modo_rele'] = "manual"
    return jsonify(dados), status_code

@app.route('/api/rele/auto', methods=['POST'])
def rele_modo_automatico():
    dados, status_code = chamar_nodemcu("/rele/auto")
    if status_code == 200:
        clima_atual['modo_rele'] = "automatico"
    return jsonify(dados), status_code

@app.route('/api/rele/status', methods=['GET'])
def rele_status():
    dados, status_code = chamar_nodemcu("/status")
    return jsonify(dados), status_code

if __name__ == '__main__':
    print("🚀 Kampu Edge Gateway iniciado!")
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)