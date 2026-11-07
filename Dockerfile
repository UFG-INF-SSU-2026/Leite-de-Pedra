# Imagem do processador, do backend e da observabilidade. O dashboard (admin/) é compilado aqui e
# servido pelo backend em /painel/. Segredos não entram na imagem: .local/ é
# montado em tempo de execução (docker-compose.yml).

FROM node:22-slim AS painel
WORKDIR /admin
COPY admin/package.json admin/package-lock.json ./
RUN npm ci
COPY admin/ ./
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY mqtt_config.py modelos.py estado_filas.py senhas.py ./
COPY processador/ processador/
COPY backend/ backend/
COPY observabilidade/ observabilidade/
COPY --from=painel /admin/dist admin/dist
# O compose roda com o usuário do host; este é só o padrão fora dele.
USER nobody
