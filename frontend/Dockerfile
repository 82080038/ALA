FROM node:20-alpine

WORKDIR /app

# package-lock.json menjamin install deterministik di mesin manapun
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev"]
