from flask import Flask, request
import os

app = Flask(__name__)
SAVE_DIR = "/var/kampu/imagens"

@app.route('/upload', methods=['POST'])
def upload_image():
    if 'file' not in request.files:
        return "Nenhum arquivo enviado", 400
        
    file = request.files['file']
    filename = file.filename
    file.save(os.path.join(SAVE_DIR, filename))
    
    return "Imagem salva com sucesso no Orange Pi", 200

if __name__ == '__main__':
    # Usado apenas para teste local, em produção usaremos Gunicorn
    app.run(host='0.0.0.0', port=5000)
