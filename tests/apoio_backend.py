"""Carrega o backend uma vez, com AWS e MQTT falsos e o banco filas_teste, e a observabilidade."""

import base64
import importlib
import socket
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import uvicorn
from botocore.exceptions import ClientError


class RekognitionFalso:
    exceptions = SimpleNamespace(InvalidParameterException=type("InvalidParameter", (Exception,), {}))

    def __init__(self):
        self.rostos = {}  # bytes da foto -> usuario_id

    def describe_collection(self, **_):
        return {}

    def search_faces_by_image(self, Image, **_):
        dono = self.rostos.get(Image["Bytes"])
        return {"FaceMatches": [{"Face": {"ExternalImageId": dono}}] if dono else []}

    def index_faces(self, Image, ExternalImageId, **_):
        self.rostos[Image["Bytes"]] = ExternalImageId
        return {"FaceRecords": [{"Face": {"FaceId": f"face-{ExternalImageId}"}}]}

    def delete_faces(self, **_):
        pass


class S3Falso:
    def __init__(self):
        self.chaves = []
        self.apagadas = []

    def limpar(self):
        self.chaves.clear()
        self.apagadas.clear()

    def put_object(self, Key, **_):
        self.chaves.append(Key)

    def delete_object(self, Key, **_):
        self.apagadas.append(Key)

    def head_object(self, Key, **_):
        if Key not in self.chaves or Key in self.apagadas:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")

    def generate_presigned_url(self, _operacao, Params, ExpiresIn):
        return f"https://bucket.s3.amazonaws.com/{Params['Key']}?expira={ExpiresIn}"


rekognition = RekognitionFalso()
s3 = S3Falso()


def foto(rosto):
    return base64.b64encode(b"\xff\xd8" + rosto.encode() * 60).decode()


def carregar_backend():
    if "backend.app" not in sys.modules:
        with patch.dict("os.environ", {"REKOGNITION_COLECAO": "teste", "FOTOS_BUCKET": "teste",
                                       "FILAS_DB": "filas_teste"}), \
             patch("boto3.client", side_effect=lambda servico, **_: {"rekognition": rekognition,
                                                                     "s3": s3}[servico]), \
             patch("mqtt_config.conectar"), \
             patch("paho.mqtt.client.Client.loop_start"):
            modulo = importlib.import_module("backend.app")
        modulo.ATRASO_APOS_LOGIN_RECUSADO_SEGUNDOS = 0
    return sys.modules["backend.app"]


def servir_observabilidade():
    """Sobe a API interna da observabilidade (banco filas_teste) numa porta livre.

    Devolve (servidor, url); o backend a alcança por HTTP, como no Docker.
    """
    with patch.dict("os.environ", {"FILAS_DB": "filas_teste"}):
        from observabilidade.app import app
    with socket.socket() as livre:
        livre.bind(("127.0.0.1", 0))
        porta = livre.getsockname()[1]
    servidor = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=porta, log_level="warning"))
    threading.Thread(target=servidor.run, daemon=True).start()
    while not servidor.started:
        time.sleep(0.05)
    return servidor, f"http://127.0.0.1:{porta}"
